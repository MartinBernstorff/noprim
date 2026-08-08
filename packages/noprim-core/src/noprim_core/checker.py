import ast
import re

from iterpy import Arr
from pydantic import RootModel

from noprim_core.annotations import AnnotationText, SymbolName, head_name, names_in
from noprim_core.config import CheckConfig
from noprim_core.rules.registry import RULES
from noprim_core.rules.rule import Rule
from noprim_core.site import (
    ColumnNumber,
    Filename,
    LineNumber,
    Owner,
    Qualname,
    Site,
    Surface,
)
from noprim_core.source import SourceCode
from noprim_core.suppression import (
    IgnoredLines,
    PytestOwned,
    SuppressionOutcome,
    Suppressions,
)
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation

Function = ast.FunctionDef | ast.AsyncFunctionDef


def _mentions(expressions: Arr[ast.expr], symbol: SymbolName) -> Verdict:
    return Verdict(expressions.filter(lambda e: head_name(e) == symbol).to_list() != [])


def _site(
    annotation: ast.expr, surface: Surface, qualname: Qualname, owner: Owner
) -> Site:
    return Site(
        line=LineNumber(annotation.lineno),
        column=ColumnNumber(annotation.col_offset + 1),
        surface=surface,
        qualname=qualname,
        annotation=AnnotationText(ast.unparse(annotation)),
        names=names_in(annotation),
        owner=owner,
    )


def _parameters(function: Function) -> Arr[ast.arg]:
    arguments = function.args
    return Arr(
        [
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *([arguments.vararg] if arguments.vararg is not None else []),
            *([arguments.kwarg] if arguments.kwarg is not None else []),
        ]
    ).filter(lambda arg: arg.arg not in {"self", "cls"})


class OverloadedNames(RootModel[frozenset[str]]):
    pass


def _decorated_as_overload(function: Function) -> Verdict:
    return _mentions(Arr(function.decorator_list), SymbolName("overload"))


def _is_dunder(function: Function) -> Verdict:
    return Verdict(function.name.startswith("__") and function.name.endswith("__"))


def _decorated_as_override(function: Function) -> Verdict:
    # A supertype dictated this signature, and the type checker verifies the claim.
    return _mentions(Arr(function.decorator_list), SymbolName("override"))


def _has_exempt_signature(function: Function, overloaded: OverloadedNames) -> Verdict:
    is_overload_implementation = Verdict(function.name in overloaded.root).and_(
        _decorated_as_overload(function).negated
    )
    return Verdict.any(
        Arr(
            [
                _is_dunder(function),
                is_overload_implementation,
                _decorated_as_override(function),
            ]
        )
    )


def _pytest_owns_parameters(function: Function) -> Verdict:
    return Verdict(function.name.startswith("test_")).or_(
        _mentions(Arr(function.decorator_list), SymbolName("fixture"))
    )


def _is_pytest_module(filename: Filename) -> Verdict:
    stem = re.sub(r"^.*[/\\]", "", filename.root).removesuffix(".py")
    return Verdict(stem.startswith("test_") or stem.endswith("_test"))


def _subclasses_root_model(class_def: ast.ClassDef) -> Verdict:
    return _mentions(Arr(class_def.bases), SymbolName("RootModel"))


def _parameter_owner(function: Function, in_pytest_module: Verdict) -> Owner:
    if in_pytest_module.and_(_pytest_owns_parameters(function)):
        return Owner.PYTEST
    return Owner.AUTHOR


def _parameter_sites(
    function: Function, qualname: Qualname, in_pytest_module: Verdict
) -> Arr[Site]:
    owner = _parameter_owner(function, in_pytest_module)
    return Arr(
        [
            _site(
                arg.annotation,
                Surface.PARAMETER,
                qualname.child(Qualname(arg.arg)),
                owner,
            )
            for arg in _parameters(function)
            if arg.annotation is not None
        ]
    )


def _function_sites(
    function: Function,
    scope: Qualname,
    overloaded: OverloadedNames,
    in_pytest_module: Verdict,
) -> Arr[Site]:
    qualname = scope.child(Qualname(function.name))
    if _has_exempt_signature(function, overloaded):
        return _sites_in(function.body, qualname, in_pytest_module)

    returns = function.returns
    return Arr(
        [
            *_parameter_sites(function, qualname, in_pytest_module),
            *(
                [_site(returns, Surface.RETURN, qualname, Owner.AUTHOR)]
                if returns is not None
                else []
            ),
            *_sites_in(function.body, qualname, in_pytest_module),
        ]
    )


def _class_sites(
    class_def: ast.ClassDef, scope: Qualname, in_pytest_module: Verdict
) -> Arr[Site]:
    if _subclasses_root_model(class_def):
        return Arr([])

    qualname = scope.child(Qualname(class_def.name))
    return Arr(
        [
            *(
                _site(
                    node.annotation,
                    Surface.ATTRIBUTE,
                    qualname.child(Qualname(ast.unparse(node.target))),
                    Owner.AUTHOR,
                )
                for node in class_def.body
                if isinstance(node, ast.AnnAssign)
            ),
            *_sites_in(class_def.body, qualname, in_pytest_module),
        ]
    )


def _overloaded_names(body: list[ast.stmt]) -> OverloadedNames:
    return OverloadedNames(
        frozenset(
            node.name
            for node in body
            if isinstance(node, Function) and _decorated_as_overload(node)
        )
    )


def _sites_in(
    body: list[ast.stmt], scope: Qualname, in_pytest_module: Verdict
) -> Arr[Site]:
    overloaded = _overloaded_names(body)
    return (
        Arr(body)
        .map(
            lambda node: (
                _function_sites(node, scope, overloaded, in_pytest_module)
                if isinstance(node, Function)
                else _class_sites(node, scope, in_pytest_module)
                if isinstance(node, ast.ClassDef)
                else Arr[Site]([])
            )
        )
        .flatten()
    )


def _violations_at(
    site: Site, filename: Filename, rules: Arr[Rule], config: CheckConfig
) -> Arr[Violation]:
    return rules.filter(lambda rule: rule.applies(site, config)).map(
        lambda rule: Violation(
            filename=filename,
            code=rule.code,
            line=site.line,
            column=site.column,
            surface=site.surface,
            qualname=site.qualname,
            annotation=site.annotation,
        )
    )


def _suppressions(
    source: SourceCode, sites: Arr[Site], config: CheckConfig
) -> Suppressions:
    return Suppressions(
        lines=IgnoredLines.parse(source),
        names=config.ignored_names,
        pytest_owned=PytestOwned(
            frozenset(
                sites.filter(lambda site: site.owner == Owner.PYTEST).map(
                    lambda site: site.qualname
                )
            )
        ),
    )


def check_source(
    source: SourceCode, filename: Filename, config: CheckConfig
) -> SuppressionOutcome:
    tree = ast.parse(source.root, filename=filename.root)
    enabled = Arr(RULES).filter(lambda rule: config.selection.contains(rule.code))
    sites = _sites_in(tree.body, Qualname(""), _is_pytest_module(filename))
    return _suppressions(source, sites, config).apply(
        sites.map(
            lambda site: _violations_at(site, filename, enabled, config)
        ).flatten()
    )
