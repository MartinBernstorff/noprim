import pytest

from noprim_core.annotations import AnnotationText, names_in_text
from noprim_core.config import CheckConfig, DeniedTypes
from noprim_core.rules.primitive_parameter import PrimitiveParameter
from noprim_core.rules.registry import default_selection
from noprim_core.rules.rule import RuleMessage
from noprim_core.site import (
    ColumnNumber,
    Filename,
    LineNumber,
    Owner,
    Qualname,
    Site,
    Surface,
)
from noprim_core.violation import Violation


def _site(surface: Surface, annotation: AnnotationText) -> Site:
    return Site(
        line=LineNumber(1),
        column=ColumnNumber(1),
        surface=surface,
        qualname=Qualname("f.x"),
        annotation=annotation,
        names=names_in_text(annotation),
    )


def _config(denied: DeniedTypes) -> CheckConfig:
    return CheckConfig(selection=default_selection(), denied=denied)


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.PARAMETER, "str"),
        (Surface.PARAMETER, "list[str]"),
        (Surface.PARAMETER, "str | None"),
    ],
)
def test_applies_to_a_denied_type_on_a_parameter(
    surface: Surface, annotation: str
) -> None:
    config = _config(DeniedTypes.default())
    assert (
        PrimitiveParameter()
        .applies(_site(surface, AnnotationText(annotation)), config)
        .root
    )


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.PARAMETER, "Name"),
        (Surface.PARAMETER, "Any"),
        (Surface.RETURN, "str"),
        (Surface.ATTRIBUTE, "str"),
    ],
)
def test_leaves_everything_else_alone(surface: Surface, annotation: str) -> None:
    config = _config(DeniedTypes.default())
    assert (
        not PrimitiveParameter()
        .applies(_site(surface, AnnotationText(annotation)), config)
        .root
    )


def test_follows_the_configured_deny_list() -> None:
    config = _config(DeniedTypes(frozenset({"Name"})))
    assert (
        PrimitiveParameter()
        .applies(_site(Surface.PARAMETER, AnnotationText("Name")), config)
        .root
    )
    assert (
        not PrimitiveParameter()
        .applies(_site(Surface.PARAMETER, AnnotationText("str")), config)
        .root
    )


def _violation(annotation: AnnotationText, owner: Owner) -> Violation:
    return Violation(
        filename=Filename("cli.py"),
        code=PrimitiveParameter().code,
        line=LineNumber(1),
        column=ColumnNumber(1),
        surface=Surface.PARAMETER,
        qualname=Qualname("ship.env"),
        annotation=annotation,
        owner=owner,
    )


def _message(annotation: AnnotationText, owner: Owner) -> RuleMessage:
    return PrimitiveParameter().message(_violation(annotation, owner))


def test_a_typer_parameter_is_told_what_to_use_instead() -> None:
    assert _message(AnnotationText("str"), Owner.TYPER) == RuleMessage(
        'parameter "env" is annotated "str"; Typer renders an enum.Enum natively, '
        "and typer.Option(parser=...) takes any type"
    )


@pytest.mark.parametrize(
    ("annotation", "owner"),
    [
        # Nothing else can spell a bare flag, so there is nothing to recommend.
        ("bool", Owner.TYPER),
        ("Annotated[bool, typer.Option()]", Owner.TYPER),
        ("str", Owner.AUTHOR),
    ],
)
def test_everything_else_keeps_the_generic_message(
    annotation: str, owner: Owner
) -> None:
    assert _message(AnnotationText(annotation), owner) == RuleMessage(
        f'parameter "env" is annotated "{annotation}"'
    )
