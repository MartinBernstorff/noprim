import pytest

from noprim_core.annotations import AnnotationText, names_in_text
from noprim_core.config import CheckConfig, DeniedTypes
from noprim_core.rules.primitive_parameter import PrimitiveParameter
from noprim_core.rules.registry import default_selection
from noprim_core.site import ColumnNumber, LineNumber, Qualname, Site, Surface


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
