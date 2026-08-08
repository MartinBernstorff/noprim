import pytest

from noprim_core.annotations import AnnotationText, names_in_text
from noprim_core.config import CheckConfig
from noprim_core.rules.registry import default_selection
from noprim_core.rules.top_type_attribute import TopTypeAttribute
from noprim_core.site import ColumnNumber, LineNumber, Qualname, Site, Surface


def _site(surface: Surface, annotation: AnnotationText) -> Site:
    return Site(
        line=LineNumber(1),
        column=ColumnNumber(1),
        surface=surface,
        qualname=Qualname("Thing.payload"),
        annotation=annotation,
        names=names_in_text(annotation),
    )


def _config() -> CheckConfig:
    return CheckConfig(selection=default_selection())


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.ATTRIBUTE, "Any"),
        (Surface.ATTRIBUTE, "object"),
        (Surface.ATTRIBUTE, "dict[str, Any]"),
    ],
)
def test_applies_to_a_top_type(surface: Surface, annotation: str) -> None:
    assert (
        TopTypeAttribute()
        .applies(_site(surface, AnnotationText(annotation)), _config())
        .root
    )


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.ATTRIBUTE, "Name"),
        (Surface.ATTRIBUTE, "str"),
        (Surface.PARAMETER, "Any"),
        (Surface.RETURN, "Any"),
    ],
)
def test_leaves_everything_else_alone(surface: Surface, annotation: str) -> None:
    assert (
        not TopTypeAttribute()
        .applies(_site(surface, AnnotationText(annotation)), _config())
        .root
    )


def test_is_off_by_default() -> None:
    assert not default_selection().contains(TopTypeAttribute().code)
