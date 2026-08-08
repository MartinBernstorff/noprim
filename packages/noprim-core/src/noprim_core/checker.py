import ast
import io
import re
import tokenize
from enum import StrEnum

from iterpy import Arr
from pydantic import BaseModel, ConfigDict, Field, RootModel

from noprim_core.annotations import (
    AnnotationText,
    SymbolName,
    TypeNames,
    head_name,
    is_exactly,
    names_in,
)
from noprim_core.verdict import Verdict


class SourceCode(RootModel[str]):
    pass


class Filename(RootModel[str]):
    # Hashed as part of a baseline key.
    model_config = ConfigDict(frozen=True)


class Qualname(RootModel[str]):
    model_config = ConfigDict(frozen=True)

    def child(self, name: "Qualname") -> "Qualname":
        if self.root == "":
            return name
        return Qualname(f"{self.root}.{name.root}")

    def leaf(self) -> "Qualname":
        return Qualname(self.root.rsplit(".", 1)[-1])


class DeniedTypes(RootModel[frozenset[str]]):
    def matches(self, names: TypeNames) -> Verdict:
        return Verdict(len(names.root & self.root) > 0)

    @classmethod
    def default(cls) -> "DeniedTypes":
        return cls(
            frozenset(
                {
                    "int",
                    "str",
                    "float",
                    "bool",
                    "bytes",
                    "bytearray",
                    "complex",
                    "Path",
                    "PurePath",
                    "UUID",
                    "datetime",
                    "date",
                    "time",
                    "timedelta",
                    "Decimal",
                    "Fraction",
                    "list",
                    "dict",
                    "set",
                    "frozenset",
                    "tuple",
                }
            )
        )


class TopTypes(RootModel[frozenset[str]]):
    @classmethod
    def default(cls) -> "TopTypes":
        return cls(frozenset({"Any", "object"}))


class IgnoredNames(RootModel[frozenset[str]]):
    def contains(self, name: "Qualname") -> "Verdict":
        return Verdict(name.root in self.root)


class CheckConfig(BaseModel):
    denied: DeniedTypes = Field(default_factory=DeniedTypes.default)
    check_predicates: Verdict = Verdict(root=False)
    ignored_names: IgnoredNames = IgnoredNames(frozenset())
    # A top type says the type is unknown, not that it is too narrow, so it is a
    # different smell from primitive obsession and is opted into on its own.
    top_types: Verdict = Verdict(root=False)

    def all_denied(self) -> DeniedTypes:
        if not self.top_types.root:
            return self.denied
        return DeniedTypes(self.denied.root | TopTypes.default().root)


class Surface(StrEnum):
    PARAMETER = "parameter"
    RETURN = "return"
    ATTRIBUTE = "attribute"


class LineNumber(RootModel[int]):
    pass


class ColumnNumber(RootModel[int]):
    pass


class Site(BaseModel):
    line: LineNumber
    column: ColumnNumber
    surface: Surface
    qualname: Qualname
    annotation: AnnotationText
    names: TypeNames
    pytest_owned: Verdict
    predicate_return: Verdict


class Violation(BaseModel):
    filename: Filename
    line: LineNumber
    column: ColumnNumber
    surface: Surface
    qualname: Qualname
    annotation: AnnotationText


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


def _site(
    annotation: ast.expr, surface: Surface, qualname: Qualname, pytest_owned: Verdict
) -> Site:
    return Site(
        line=LineNumber(annotation.lineno),
        column=ColumnNumber(annotation.col_offset + 1),
        surface=surface,
        qualname=qualname,
        annotation=AnnotationText(ast.unparse(annotation)),
        names=names_in(annotation),
        pytest_owned=pytest_owned,
        predicate_return=Verdict(
            surface == Surface.RETURN
            and is_exactly(annotation, SymbolName("bool")).root
        ),
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


def _function_sites(
    function: Function, scope: Qualname, overloaded: OverloadedNames
) -> Arr[Site]:
    qualname = scope.child(Qualname(function.name))
    if _has_exempt_signature(function, overloaded):  # pyrefly: ignore[implicit-bool]
        return _sites_in(function.body, qualname)

    returns = function.returns
    owned = _pytest_owns_parameters(function)
    return Arr(
        [
            *(
                _site(
                    arg.annotation,
                    Surface.PARAMETER,
                    qualname.child(Qualname(arg.arg)),
                    owned,
                )
                for arg in _parameters(function)
                if arg.annotation is not None
            ),
            *(
                [_site(returns, Surface.RETURN, qualname, Verdict(root=False))]
                if returns is not None
                else []
            ),
            *_sites_in(function.body, qualname),
        ]
    )


def _class_sites(class_def: ast.ClassDef, scope: Qualname) -> Arr[Site]:
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
                    Verdict(root=False),
                )
                for node in class_def.body
                if isinstance(node, ast.AnnAssign)
            ),
            *_sites_in(class_def.body, qualname),
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


def _sites_in(body: list[ast.stmt], scope: Qualname) -> Arr[Site]:
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


def _named_as_ignored(site: Site, ignored: IgnoredNames) -> Verdict:
    # A return type carries the function's name, not a symbol name of its own.
    return Verdict(
        site.surface != Surface.RETURN and bool(ignored.contains(site.qualname.leaf()))
    )


def check_source(
    source: SourceCode, filename: Filename, config: CheckConfig
) -> Arr[Violation]:
    tree = ast.parse(source.root, filename=filename.root)
    ignored = IgnoredLines.parse(source)
    # pytest dictates the signature of tests and fixtures, so their parameters aren't
    # the author's to choose.
    exempt = _is_pytest_module(filename)
    return (
        _sites_in(tree.body, Qualname(""))
        .filter(lambda site: bool(config.all_denied().matches(site.names)))
        .filter(lambda site: not bool(bool(exempt) and site.pytest_owned))
        .filter(
            lambda site: (
                bool(config.check_predicates) or not bool(site.predicate_return)
            )
        )
        .filter(lambda site: not bool(_named_as_ignored(site, config.ignored_names)))
        .filter(lambda site: site.line.root not in ignored.root)
        .map(
            lambda site: Violation(
                filename=filename,
                line=site.line,
                column=site.column,
                surface=site.surface,
                qualname=site.qualname,
                annotation=site.annotation,
            )
        )
    )
