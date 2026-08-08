import ast

import pytest

from noprim_core.annotations import (
    AnnotationText,
    SymbolName,
    head_name,
    is_exactly,
    names_in_text,
)
from noprim_core.verdict import Verdict


def _expression(text: AnnotationText) -> ast.expr:
    return ast.parse(text.root, mode="eval").body


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("str", {"str"}),
        ("Name", {"Name"}),
        ("datetime.datetime", {"datetime"}),
        ("dt.datetime", {"datetime"}),
        ("T", {"T"}),
        ("42", set()),
    ],
)
def test_names_in_plain_annotations(annotation: str, expected: set[str]) -> None:
    assert names_in_text(AnnotationText(annotation)).root == expected


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("list", {"list"}),
        ("list[str]", {"str"}),
        ("list[Name]", {"Name"}),
        ("dict[str, UserId]", {"str", "UserId"}),
        ("Callable[[Event], str]", {"Event", "str"}),
        ("Annotated[str, Field(gt=0)]", {"str"}),
        ("MyGeneric[str]", {"str"}),
        ("list[list[dict[Name, str]]]", {"Name", "str"}),
    ],
)
def test_bare_container_is_a_name_but_a_subscripted_one_is_only_its_arguments(
    annotation: str, expected: set[str]
) -> None:
    assert names_in_text(AnnotationText(annotation)).root == expected


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("str | None", {"str"}),
        ("None | str", {"str"}),
        ("Name | str", {"Name", "str"}),
        ("list[Name] | str", {"Name", "str"}),
        ("Name | None", {"Name"}),
        ("Name | Other", {"Name", "Other"}),
    ],
)
def test_names_in_unions(annotation: str, expected: set[str]) -> None:
    assert names_in_text(AnnotationText(annotation)).root == expected


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("Literal['a', 'b']", set()),
        ("typing.Literal[1, 2]", set()),
        ("dict[Name, Literal['a']]", {"Name"}),
    ],
)
def test_literal_arguments_are_values_not_types(
    annotation: str, expected: set[str]
) -> None:
    assert names_in_text(AnnotationText(annotation)).root == expected


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ('"str"', {"str"}),
        ('list["str"]', {"str"}),
        ('"list[str]"', {"str"}),
        ('"str | None"', {"str"}),
        ('"Name"', {"Name"}),
    ],
)
def test_names_in_string_annotations(annotation: str, expected: set[str]) -> None:
    assert names_in_text(AnnotationText(annotation)).root == expected


@pytest.mark.parametrize("annotation", ["not python!!", "", "list[", '"list["'])
def test_unparseable_annotations_name_nothing(annotation: str) -> None:
    assert names_in_text(AnnotationText(annotation)).root == set()


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("bool", Verdict(root=True)),
        ("builtins.bool", Verdict(root=True)),
        ('"bool"', Verdict(root=True)),
        ("bool | None", Verdict(root=False)),
        ("list[bool]", Verdict(root=False)),
        ("Literal[True]", Verdict(root=False)),
        ("Name", Verdict(root=False)),
        ('"not python!!"', Verdict(root=False)),
    ],
)
def test_is_exactly_bool(annotation: str, expected: Verdict) -> None:
    assert (
        is_exactly(_expression(AnnotationText(annotation)), SymbolName("bool"))
        == expected
    )


@pytest.mark.parametrize(
    ("annotation", "name", "expected"),
    [
        ("Name", "Name", Verdict(root=True)),
        ("uuid.UUID", "UUID", Verdict(root=True)),
        ("Name", "bool", Verdict(root=False)),
    ],
)
def test_is_exactly_any_name(annotation: str, name: str, expected: Verdict) -> None:
    assert (
        is_exactly(_expression(AnnotationText(annotation)), SymbolName(name))
        == expected
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("Path", "Path"),
        ("pathlib.Path", "Path"),
        ("dict[str, int]", "dict"),
        ("pytest.fixture()", "fixture"),
        ("[Name]", ""),
    ],
)
def test_head_name(expression: str, expected: str) -> None:
    assert head_name(_expression(AnnotationText(expression))).root == expected
