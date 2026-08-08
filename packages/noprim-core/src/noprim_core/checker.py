import ast
import re
from collections.abc import Callable

from iterpy import Arr
from pydantic import BaseModel, RootModel

from noprim_core.annotations import AnnotationText, SymbolName, head_name, names_in
from noprim_core.config import CheckConfig
from noprim_core.rules.registry import RULES
from noprim_core.rules.rule import Rule
from noprim_core.site import (
    ClassChain,
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
    IgnoredFile,
    IgnoredLines,
    OwnedQualnames,
    SuppressionOutcome,
    Suppressions,
    tokens_in,
)
from noprim_core.violation import Violation
from noprim_types.verdict import Verdict

Function = ast.FunctionDef | ast.AsyncFunctionDef


# Where the walk currently is. The class chain is here rather than derived from the
# qualname because only the walk can tell a class segment from a function's.
class Enclosing(BaseModel):
    qualname: Qualname = Qualname("")
    classes: ClassChain = ClassChain(())
    in_pytest_module: Verdict = Verdict(root=False)

    def named(self, name: Qualname) -> Qualname:
        return self.qualname.child(name)

    def in_function(self, name: Qualname) -> "Enclosing":
        return self.model_copy(update={"qualname": self.named(name)})

    def in_class(self, name: Qualname) -> "Enclosing":
        return self.model_copy(
            update={"qualname": self.named(name), "classes": self.classes.child(name)}
        )


def _mentions(expressions: Arr[ast.expr], symbol: SymbolName) -> Verdict:
    return Verdict(expressions.filter(lambda e: head_name(e) == symbol).to_list() != [])


def _site(
    annotation: ast.expr,
    surface: Surface,
    qualname: Qualname,
    owner: Owner,
    scope: Enclosing,
) -> Site:
    return Site(
        line=LineNumber(annotation.lineno),
        column=ColumnNumber(annotation.col_offset + 1),
        surface=surface,
        qualname=qualname,
        annotation=AnnotationText(ast.unparse(annotation)),
        names=names_in(annotation),
        owner=owner,
        enclosing_classes=scope.classes,
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


def _decorated_with(function: Function, symbol: SymbolName) -> Verdict:
    return _mentions(Arr(function.decorator_list), symbol)


def _is_dunder(function: Function) -> Verdict:
    return Verdict(function.name.startswith("__") and function.name.endswith("__"))


def _has_exempt_signature(function: Function, overloaded: OverloadedNames) -> Verdict:
    is_overload_implementation = Verdict(function.name in overloaded.root).and_(
        _decorated_with(function, SymbolName("overload")).negated
    )
    return Verdict.any(
        Arr(
            [
                _is_dunder(function),
                is_overload_implementation,
                _decorated_with(function, SymbolName("override")),
            ]
        )
    )


def _pytest_owns_parameters(function: Function) -> Verdict:
    return Verdict(function.name.startswith("test_")).or_(
        _decorated_with(function, SymbolName("fixture"))
    )


def _attribute_name(decorator: ast.expr) -> SymbolName:
    match decorator:
        case ast.Attribute(attr=name):
            return SymbolName(name)
        case ast.Call(func=inner):
            return _attribute_name(inner)
        case _:
            return SymbolName("")


# Matched on the attribute the app object is asked for, so it holds however that object
# is named — and a bare `@command`, which typer never spells, stays checked.
def _typer_owns_parameters(function: Function) -> Verdict:
    return Verdict(
        Arr(function.decorator_list)
        .map(_attribute_name)
        .filter(lambda name: name.root in {"command", "callback"})
        .to_list()
        != []
    )


def _is_pytest_module(filename: Filename) -> Verdict:
    stem = re.sub(r"^.*[/\\]", "", filename.root).removesuffix(".py")
    return Verdict(stem.startswith("test_") or stem.endswith("_test"))


def _subclasses_root_model(class_def: ast.ClassDef) -> Verdict:
    return _mentions(Arr(class_def.bases), SymbolName("RootModel"))


def _parameter_owner(function: Function, in_pytest_module: Verdict) -> Owner:
    if in_pytest_module.and_(_pytest_owns_parameters(function)):
        return Owner.PYTEST
    if _typer_owns_parameters(function):
        return Owner.TYPER
    return Owner.AUTHOR


def _parameter_sites(function: Function, scope: Enclosing) -> Arr[Site]:
    owner = _parameter_owner(function, scope.in_pytest_module)
    return Arr(
        [
            _site(
                arg.annotation,
                Surface.PARAMETER,
                scope.named(Qualname(arg.arg)),
                owner,
                scope,
            )
            for arg in _parameters(function)
            if arg.annotation is not None
        ]
    )


def _function_sites(
    function: Function, scope: Enclosing, overloaded: OverloadedNames
) -> Arr[Site]:
    inside = scope.in_function(Qualname(function.name))
    if _has_exempt_signature(function, overloaded):
        return _sites_in(function.body, inside)

    returns = function.returns
    return Arr(
        [
            *_parameter_sites(function, inside),
            *(
                [_site(returns, Surface.RETURN, inside.qualname, Owner.AUTHOR, inside)]
                if returns is not None
                else []
            ),
            *_sites_in(function.body, inside),
        ]
    )


def _class_sites(class_def: ast.ClassDef, scope: Enclosing) -> Arr[Site]:
    if _subclasses_root_model(class_def):
        return Arr([])

    inside = scope.in_class(Qualname(class_def.name))
    return Arr(
        [
            *(
                _site(
                    node.annotation,
                    Surface.ATTRIBUTE,
                    inside.named(Qualname(ast.unparse(node.target))),
                    Owner.AUTHOR,
                    inside,
                )
                for node in class_def.body
                if isinstance(node, ast.AnnAssign)
            ),
            *_sites_in(class_def.body, inside),
        ]
    )


def _overloaded_names(body: list[ast.stmt]) -> OverloadedNames:
    return OverloadedNames(
        frozenset(
            node.name
            for node in body
            if isinstance(node, Function)
            and _decorated_with(node, SymbolName("overload"))
        )
    )


def _sites_in(body: list[ast.stmt], scope: Enclosing) -> Arr[Site]:
    overloaded = _overloaded_names(body)
    return (
        Arr(body)
        .map(
            lambda node: (
                _function_sites(node, scope, overloaded)
                if isinstance(node, Function)
                else _class_sites(node, scope)
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


def _owned(sites: Arr[Site], by: Callable[[Site], Verdict]) -> OwnedQualnames:
    return OwnedQualnames(frozenset(sites.filter(by).map(lambda site: site.qualname)))


def _suppressions(
    source: SourceCode, sites: Arr[Site], config: CheckConfig
) -> Suppressions:
    tokens = tokens_in(source)
    return Suppressions(
        file=IgnoredFile.parse(tokens),
        lines=IgnoredLines.parse(tokens),
        parameter_names=config.ignored_parameter_names,
        attribute_names=config.ignored_attribute_names,
        inner_class_owned=_owned(
            sites,
            lambda site: config.ignored_inner_classes.matches_any(
                site.enclosing_classes.inner()
            ),
        ),
        pytest_owned=_owned(sites, lambda site: Verdict(site.owner == Owner.PYTEST)),
        typer_owned=_owned(
            sites,
            lambda site: config.exempt_typer_args.and_(
                Verdict(site.owner == Owner.TYPER)
            ),
        ),
    )


def check_source(
    source: SourceCode, filename: Filename, config: CheckConfig
) -> SuppressionOutcome:
    tree = ast.parse(source.root, filename=filename.root)
    enabled = Arr(RULES).filter(lambda rule: config.selection.contains(rule.code))
    sites = _sites_in(
        tree.body, Enclosing(in_pytest_module=_is_pytest_module(filename))
    )
    return _suppressions(source, sites, config).apply(
        sites.map(
            lambda site: _violations_at(site, filename, enabled, config)
        ).flatten()
    )
