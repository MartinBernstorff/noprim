import pytest

from noprim_core.annotations import AnnotationText, names_in_text
from noprim_core.config import CheckConfig, DeniedTypes
from noprim_core.rules.primitive_attribute import PrimitiveAttribute
from noprim_core.rules.registry import default_selection
from noprim_core.site import ColumnNumber, LineNumber, Qualname, Site, Surface


def _site(surface: Surface, annotation: AnnotationText) -> Site:
    return Site(
        line=LineNumber(1),
        column=ColumnNumber(1),
        surface=surface,
        qualname=Qualname("Thing.count"),
        annotation=annotation,
        names=names_in_text(annotation),
    )


def _config(denied: DeniedTypes) -> CheckConfig:
    return CheckConfig(selection=default_selection(), denied=denied)


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.ATTRIBUTE, "int"),
        (Surface.ATTRIBUTE, "ClassVar[int]"),
        (Surface.ATTRIBUTE, "bool"),
    ],
)
def test_applies_to_a_denied_type_on_an_attribute(
    surface: Surface, annotation: str
) -> None:
    config = _config(DeniedTypes.default())
    assert (
        PrimitiveAttribute()
        .applies(_site(surface, AnnotationText(annotation)), config)
        .root
    )


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.ATTRIBUTE, "Name"),
        (Surface.PARAMETER, "int"),
        (Surface.RETURN, "int"),
    ],
)
def test_leaves_everything_else_alone(surface: Surface, annotation: str) -> None:
    config = _config(DeniedTypes.default())
    assert (
        not PrimitiveAttribute()
        .applies(_site(surface, AnnotationText(annotation)), config)
        .root
    )
