import ast

from iterpy import Arr
from pydantic import ConfigDict, RootModel

from noprim_types.verdict import Verdict


class SymbolName(RootModel[str]):
    pass


class AnnotationText(RootModel[str]):
    # Hashed as part of a baseline key.
    model_config = ConfigDict(frozen=True)


class TypeNames(RootModel[frozenset[str]]):
    pass


def head_name(expression: ast.expr) -> SymbolName:
    match expression:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return SymbolName(name)
        case ast.Subscript(value=value) | ast.Call(func=value):
            return head_name(value)
        case _:
            # Unresolvable expressions get "", which no deny-list entry can match.
            return SymbolName("")


def _parse(text: AnnotationText) -> ast.expr | None:
    try:
        return ast.parse(text.root, mode="eval").body
    except SyntaxError:
        return None


def _union_of_names(expressions: Arr[ast.expr]) -> TypeNames:
    return TypeNames(frozenset().union(*expressions.map(lambda e: names_in(e).root)))


def names_in(annotation: ast.expr) -> TypeNames:
    match annotation:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return TypeNames(frozenset({name}))
        case ast.Subscript(value=value, slice=inner):
            # Literal's arguments are values, not types.
            return (
                TypeNames(frozenset())
                if head_name(value) == SymbolName("Literal")
                else names_in(inner)
            )
        case ast.BinOp(left=left, right=right):
            return _union_of_names(Arr([left, right]))
        case ast.Tuple(elts=elts) | ast.List(elts=elts):
            return _union_of_names(Arr(elts))
        case ast.Constant(value=str() as text):
            return names_in_text(AnnotationText(text))
        case _:
            return TypeNames(frozenset())


def names_in_text(text: AnnotationText) -> TypeNames:
    parsed = _parse(text)
    return TypeNames(frozenset()) if parsed is None else names_in(parsed)


def text_is_exactly(text: AnnotationText, name: SymbolName) -> Verdict:
    parsed = _parse(text)
    return Verdict(root=False) if parsed is None else is_exactly(parsed, name)


def is_exactly(annotation: ast.expr, name: SymbolName) -> Verdict:
    match annotation:
        case ast.Name(id=found) | ast.Attribute(attr=found):
            return Verdict(found == name.root)
        case ast.Constant(value=str() as text):
            parsed = _parse(AnnotationText(text))
            return Verdict(root=False) if parsed is None else is_exactly(parsed, name)
        case _:
            return Verdict(root=False)
