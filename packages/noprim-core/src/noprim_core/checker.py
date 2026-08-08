import ast
import io
import re
import tokenize
from enum import StrEnum

from iterpy import Arr
from pydantic import BaseModel, Field, RootModel


class SourceCode(RootModel[str]):
    pass


class Filename(RootModel[str]):
    pass


class Qualname(RootModel[str]):
    def child(self, name: "Qualname") -> "Qualname":
        if self.root == "":
            return name
        return Qualname(f"{self.root}.{name.root}")

    def leaf(self) -> "Qualname":
        return Qualname(self.root.rsplit(".", 1)[-1])


class DeniedTypes(RootModel[frozenset[str]]):
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
                    "Any",
                    "object",
                }
            )
        )


class CheckConfig(BaseModel):
    denied: DeniedTypes = Field(default_factory=DeniedTypes.default)


class Surface(StrEnum):
    PARAMETER = "parameter"
    RETURN = "return"
    ATTRIBUTE = "attribute"


class AnnotationText(RootModel[str]):
    pass


class LineNumber(RootModel[int]):
    pass


class ColumnNumber(RootModel[int]):
    pass


class TypeNames(RootModel[frozenset[str]]):
    def any_denied(self, denied: DeniedTypes) -> "Verdict":
        return Verdict(len(self.root & denied.root) > 0)


class Verdict(RootModel[bool]):
    def __bool__(self) -> bool:
        return self.root


class Site(BaseModel):
    line: LineNumber
    column: ColumnNumber
    surface: Surface
    qualname: Qualname
    annotation: AnnotationText
    names: TypeNames
    pytest_owned: Verdict


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


class SymbolName(RootModel[str]):
    pass


def _head_name(expression: ast.expr) -> SymbolName:
    match expression:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return SymbolName(name)
        case ast.Subscript(value=value) | ast.Call(func=value):
            return _head_name(value)
        case _:
            # Unresolvable expressions get "", which no deny-list entry can match.
            return SymbolName("")


def _mentions(expressions: Arr[ast.expr], symbol: SymbolName) -> Verdict:
    return Verdict(
        expressions.filter(lambda e: _head_name(e) == symbol).to_list() != []
    )


def _parsed_names(text: AnnotationText) -> TypeNames:
    try:
        return _annotation_names(ast.parse(text.root, mode="eval").body)
    except SyntaxError:
        return TypeNames(frozenset())


def _union_of_names(expressions: Arr[ast.expr]) -> TypeNames:
    return TypeNames(
        frozenset().union(*expressions.map(lambda e: _annotation_names(e).root))
    )


def _annotation_names(annotation: ast.expr) -> TypeNames:
    match annotation:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return TypeNames(frozenset({name}))
        case ast.Subscript(value=value, slice=inner):
            # Literal's arguments are values, not types.
            return (
                TypeNames(frozenset())
                if _head_name(value) == SymbolName("Literal")
                else _annotation_names(inner)
            )
        case ast.BinOp(left=left, right=right):
            return _union_of_names(Arr([left, right]))
        case ast.Tuple(elts=elts) | ast.List(elts=elts):
            return _union_of_names(Arr(elts))
        case ast.Constant(value=str() as text):
            return _parsed_names(AnnotationText(text))
        case _:
            return TypeNames(frozenset())


def _site(
    annotation: ast.expr, surface: Surface, qualname: Qualname, pytest_owned: Verdict
) -> Site:
    return Site(
        line=LineNumber(annotation.lineno),
        column=ColumnNumber(annotation.col_offset + 1),
        surface=surface,
        qualname=qualname,
        annotation=AnnotationText(ast.unparse(annotation)),
        names=_annotation_names(annotation),
        pytest_owned=pytest_owned,
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
        # pyrefly: ignore[bad-argument-type]
        .filter(lambda site: site.names.any_denied(config.denied))
        # pyrefly: ignore[implicit-bool]
        .filter(lambda site: not (exempt and site.pytest_owned))
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
