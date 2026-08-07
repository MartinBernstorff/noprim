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


class Site(BaseModel):
    line: int
    surface: Surface
    qualname: str
    annotation: str
    names: frozenset[str]


class Violation(BaseModel):
    filename: str
    line: int
    surface: Surface
    qualname: str
    annotation: str


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


def _head_name(expression: ast.expr) -> str:
    match expression:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Subscript(value=value):
            return _head_name(value)
        case _:
            # Unresolvable expressions get "", which no deny-list entry can match.
            return ""


def _mentions(expressions: Arr[ast.expr], symbol: SymbolName) -> bool:
    return expressions.filter(lambda e: _head_name(e) == symbol.root).to_list() != []


def _parsed_names(text: AnnotationText) -> frozenset[str]:
    try:
        return _annotation_names(ast.parse(text.root, mode="eval").body)
    except SyntaxError:
        return frozenset()


def _annotation_names(annotation: ast.expr) -> frozenset[str]:
    match annotation:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return frozenset({name})
        case ast.Subscript(value=value, slice=inner):
            # Literal's arguments are values, not types.
            if _head_name(value) == "Literal":
                return frozenset()
            return _annotation_names(inner)
        case ast.Tuple(elts=elts) | ast.List(elts=elts):
            return frozenset().union(*Arr(elts).map(_annotation_names))
        case ast.Constant(value=str() as text):
            return _parsed_names(AnnotationText(text))
        case _:
            return frozenset()


def _site(annotation: ast.expr, surface: Surface, qualname: Qualname) -> Site:
    return Site(
        line=annotation.lineno,
        surface=surface,
        qualname=qualname.root,
        annotation=ast.unparse(annotation),
        names=_annotation_names(annotation),
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


def _decorated_as_overload(function: Function) -> bool:
    return _mentions(Arr(function.decorator_list), SymbolName("overload"))


def _is_dunder(function: Function) -> bool:
    return function.name.startswith("__") and function.name.endswith("__")


def _has_exempt_signature(function: Function, overloaded: OverloadedNames) -> bool:
    is_overload_implementation = (
        function.name in overloaded.root and not _decorated_as_overload(function)
    )
    return _is_dunder(function) or is_overload_implementation


def _subclasses_root_model(class_def: ast.ClassDef) -> bool:
    return _mentions(Arr(class_def.bases), SymbolName("RootModel"))


def _function_sites(
    function: Function, scope: Qualname, overloaded: OverloadedNames
) -> Arr[Site]:
    qualname = scope.child(Qualname(function.name))
    if _has_exempt_signature(function, overloaded):
        return _sites_in(function.body, qualname)

    returns = function.returns
    return Arr(
        [
            *(
                _site(
                    arg.annotation, Surface.PARAMETER, qualname.child(Qualname(arg.arg))
                )
                for arg in _parameters(function)
                if arg.annotation is not None
            ),
            *(
                [_site(returns, Surface.RETURN, qualname)]
                if returns is not None
                else []
            ),
            *_sites_in(function.body, qualname),
        ]
    )


def _class_sites(class_def: ast.ClassDef, scope: Qualname) -> Arr[Site]:
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
    return (
        _sites_in(tree.body, Qualname(""))
        .filter(lambda site: len(site.names & config.denied.root) > 0)
        .filter(lambda site: site.line not in ignored.root)
        .map(
            lambda site: Violation(
                filename=filename.root,
                line=site.line,
                surface=site.surface,
                qualname=site.qualname,
                annotation=site.annotation,
            )
        )
    )
