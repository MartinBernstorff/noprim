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


class Site(BaseModel):
    line: int
    surface: Surface
    qualname: str
    annotation: str


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


def _annotation_name(annotation: ast.expr) -> str:
    match annotation:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=name):
            return name
        case ast.Subscript(value=value, slice=inner) if (
            _annotation_name(value) == "ClassVar"
        ):
            return _annotation_name(inner)
        case _:
            # Unresolvable annotations get "", which no deny-list entry can match.
            return ""


def _site(annotation: ast.expr, surface: Surface, qualname: Qualname) -> Site:
    return Site(
        line=annotation.lineno,
        surface=surface,
        qualname=qualname.root,
        annotation=_annotation_name(annotation),
    )


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Arr[ast.arg]:
    arguments = function.args
    return Arr(
        [
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *([arguments.vararg] if arguments.vararg is not None else []),
            *([arguments.kwarg] if arguments.kwarg is not None else []),
        ]
    )


def _function_sites(
    function: ast.FunctionDef | ast.AsyncFunctionDef, scope: Qualname
) -> Arr[Site]:
    qualname = scope.child(Qualname(function.name))
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


def _sites_in(body: list[ast.stmt], scope: Qualname) -> Arr[Site]:
    return (
        Arr(body)
        .map(
            lambda node: (
                _function_sites(node, scope)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
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
        .filter(lambda site: site.annotation in config.denied.root)
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
