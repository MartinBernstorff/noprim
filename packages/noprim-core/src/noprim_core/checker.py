import ast
import io
import re
import tokenize

from iterpy import Arr
from pydantic import RootModel

from noprim_core.annotations import AnnotationText, SymbolName, head_name, names_in
from noprim_core.config import CheckConfig, IgnoredNames
from noprim_core.rules.registry import RULES
from noprim_core.rules.rule import Rule
from noprim_core.site import (
    ColumnNumber,
    Filename,
    LineNumber,
    Qualname,
    Site,
    Surface,
)
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation


class SourceCode(RootModel[str]):
    pass


class IgnoredLines(RootModel[frozenset[int]]):
    @classmethod
    def parse(cls, source: SourceCode) -> "IgnoredLines":
        # Anchored to end-of-line so `# noprim: ignore[NOPRIM002]` stays free for later.
        # Searched, not matched, so it can stack after another tool's suppression.
        pattern = re.compile(r"#\s*noprim:\s*ignore\s*$")
        tokens = tokenize.generate_tokens(io.StringIO(source.root).readline)
        return cls(
            frozenset(
                Arr(tokens)
                .filter(lambda token: token.type == tokenize.COMMENT)
                .filter(lambda token: pattern.search(token.string) is not None)
                .map(lambda token: token.start[0])
            )
        )


Function = ast.FunctionDef | ast.AsyncFunctionDef


def _mentions(expressions: Arr[ast.expr], symbol: SymbolName) -> Verdict:
    return Verdict(expressions.filter(lambda e: head_name(e) == symbol).to_list() != [])


def _site(annotation: ast.expr, surface: Surface, qualname: Qualname) -> Site:
    return Site(
        line=LineNumber(annotation.lineno),
        column=ColumnNumber(annotation.col_offset + 1),
        surface=surface,
        qualname=qualname,
        annotation=AnnotationText(ast.unparse(annotation)),
        names=names_in(annotation),
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


def _has_exempt_signature(function: Function, overloaded: OverloadedNames) -> Verdict:
    is_overload_implementation = (
        function.name in overloaded.root and not _decorated_as_overload(function).root
    )
    return Verdict(_is_dunder(function).root or is_overload_implementation)


def _pytest_owns_parameters(function: Function) -> Verdict:
    return Verdict(
        function.name.startswith("test_")
        or _mentions(Arr(function.decorator_list), SymbolName("fixture")).root
    )


def _is_pytest_module(filename: Filename) -> Verdict:
    stem = re.sub(r"^.*[/\\]", "", filename.root).removesuffix(".py")
    return Verdict(stem.startswith("test_") or stem.endswith("_test"))


def _subclasses_root_model(class_def: ast.ClassDef) -> Verdict:
    return _mentions(Arr(class_def.bases), SymbolName("RootModel"))


def _parameter_sites(
    function: Function, qualname: Qualname, in_pytest_module: Verdict
) -> Arr[Site]:
    # pytest dictates the signature of tests and fixtures, so their parameters aren't
    # the author's to choose.
    if in_pytest_module.root and _pytest_owns_parameters(function).root:
        return Arr([])
    return Arr(
        [
            _site(arg.annotation, Surface.PARAMETER, qualname.child(Qualname(arg.arg)))
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
    if _has_exempt_signature(function, overloaded):  # pyrefly: ignore[implicit-bool]
        return _sites_in(function.body, qualname, in_pytest_module)

    returns = function.returns
    return Arr(
        [
            *_parameter_sites(function, qualname, in_pytest_module),
            *(
                [_site(returns, Surface.RETURN, qualname)]
                if returns is not None
                else []
            ),
            *_sites_in(function.body, qualname, in_pytest_module),
        ]
    )


def _class_sites(
    class_def: ast.ClassDef, scope: Qualname, in_pytest_module: Verdict
) -> Arr[Site]:
    if _subclasses_root_model(class_def):  # pyrefly: ignore[implicit-bool]
        return Arr([])

    qualname = scope.child(Qualname(class_def.name))
    return Arr(
        [
            *(
                _site(
                    node.annotation,
                    Surface.ATTRIBUTE,
                    qualname.child(Qualname(ast.unparse(node.target))),
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
            # pyrefly: ignore[implicit-bool]
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


def _named_as_ignored(site: Site, ignored: IgnoredNames) -> Verdict:
    # A return type carries the function's name, not a symbol name of its own.
    return Verdict(
        site.surface != Surface.RETURN and bool(ignored.contains(site.qualname.leaf()))
    )


def _violations_at(
    site: Site, filename: Filename, rules: Arr[Rule], config: CheckConfig
) -> Arr[Violation]:
    return rules.filter(lambda rule: bool(rule.applies(site, config))).map(
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


def check_source(
    source: SourceCode, filename: Filename, config: CheckConfig
) -> Arr[Violation]:
    tree = ast.parse(source.root, filename=filename.root)
    ignored = IgnoredLines.parse(source)
    enabled = Arr(RULES).filter(lambda rule: bool(config.selection.contains(rule.code)))
    return (
        _sites_in(tree.body, Qualname(""), _is_pytest_module(filename))
        .filter(lambda site: not bool(_named_as_ignored(site, config.ignored_names)))
        .filter(lambda site: site.line.root not in ignored.root)
        .map(lambda site: _violations_at(site, filename, enabled, config))
        .flatten()
    )
