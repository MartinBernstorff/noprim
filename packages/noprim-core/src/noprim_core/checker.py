import ast
from enum import StrEnum

from iterpy import Arr
from pydantic import BaseModel, Field, RootModel


class SourceCode(RootModel[str]):
    pass


class Filename(RootModel[str]):
    pass


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


class Violation(BaseModel):
    filename: str
    line: int
    surface: Surface
    qualname: str
    annotation: str


# Unresolvable annotations get "", which no deny-list entry can match.
def _annotation_name(annotation: ast.expr | None) -> str:
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
            return ""


Site = tuple[ast.expr, Surface, str]


def _violations_at(
    sites: Arr[Site], filename: Filename, config: CheckConfig
) -> Arr[Violation]:
    return Arr(
        Violation(
            filename=filename.root,
            line=node.lineno,
            surface=surface,
            qualname=qualname,
            annotation=_annotation_name(node),
        )
        for node, surface, qualname in sites
        if _annotation_name(node) in config.denied.root
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


def _function_sites(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Arr[Site]:
    parameters = Arr[Site](
        (arg.annotation, Surface.PARAMETER, f"{function.name}.{arg.arg}")
        for arg in _parameters(function)
        if arg.annotation is not None
    )
    if function.returns is None:
        return parameters
    return Arr([*parameters, (function.returns, Surface.RETURN, function.name)])


def _class_sites(class_def: ast.ClassDef) -> Arr[Site]:
    return Arr(
        (
            node.annotation,
            Surface.ATTRIBUTE,
            f"{class_def.name}.{ast.unparse(node.target)}",
        )
        for node in class_def.body
        if isinstance(node, ast.AnnAssign)
    )


def check_source(
    source: SourceCode, filename: Filename, config: CheckConfig
) -> Arr[Violation]:
    nodes = list(ast.walk(ast.parse(source.root, filename=filename.root)))
    sites = Arr[Site](
        [
            *Arr(
                node
                for node in nodes
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            )
            .map(_function_sites)
            .flatten(),
            *Arr(node for node in nodes if isinstance(node, ast.ClassDef))
            .map(_class_sites)
            .flatten(),
        ]
    )
    return _violations_at(sites, filename, config)
