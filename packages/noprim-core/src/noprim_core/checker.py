import ast

from iterpy import Arr
from pydantic import BaseModel, RootModel


class SourceCode(RootModel[str]):
    pass


class Filename(RootModel[str]):
    pass


class PrimitiveNames(RootModel[frozenset[str]]):
    @classmethod
    def default(cls) -> "PrimitiveNames":
        return cls(frozenset({"int", "str", "float", "bool", "bytes", "complex"}))


class Violation(BaseModel):
    filename: str
    line: int
    function: str
    parameter: str
    annotation: str


def _annotation_name(annotation: ast.expr | None) -> str | None:
    match annotation:
        case ast.Name(id=name):
            return name
        case _:
            return None


def _violations_in(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    filename: Filename,
    primitives: PrimitiveNames,
) -> Arr[Violation]:
    arguments = function.args
    all_args = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *([arguments.vararg] if arguments.vararg is not None else []),
        *([arguments.kwarg] if arguments.kwarg is not None else []),
    ]
    return (
        Arr(all_args)
        .map(lambda arg: (arg, _annotation_name(arg.annotation)))
        .filter(lambda pair: pair[1] in primitives.root)
        .map(
            lambda pair: Violation(
                filename=filename.root,
                line=pair[0].lineno,
                function=function.name,
                parameter=pair[0].arg,
                annotation=pair[1] if pair[1] is not None else "",
            )
        )
    )


def check_source(
    source: SourceCode,
    filename: Filename,
    primitives: PrimitiveNames | None = None,
) -> Arr[Violation]:
    resolved = primitives if primitives is not None else PrimitiveNames.default()
    tree = ast.parse(source.root, filename=filename.root)
    functions = Arr(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )
    return functions.map(
        lambda node: _violations_in(node, filename, resolved)
    ).flatten()
