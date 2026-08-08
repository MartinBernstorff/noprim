import pytest

from noprim_core.annotations import AnnotationText, names_in_text
from noprim_core.config import CheckConfig
from noprim_core.rules.registry import core_selection
from noprim_core.rules.top_type_return import TopTypeReturn
from noprim_core.site import ColumnNumber, LineNumber, Qualname, Site, Surface


def _site(surface: Surface, annotation: AnnotationText) -> Site:
    return Site(
        line=LineNumber(1),
        column=ColumnNumber(1),
        surface=surface,
        qualname=Qualname("f"),
        annotation=annotation,
        names=names_in_text(annotation),
    )


def _config() -> CheckConfig:
    return CheckConfig(selection=core_selection())


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.RETURN, "Any"),
        (Surface.RETURN, "object"),
        (Surface.RETURN, "dict[str, Any]"),
    ],
)
def test_applies_to_a_top_type(surface: Surface, annotation: str) -> None:
    assert (
        TopTypeReturn()
        .applies(_site(surface, AnnotationText(annotation)), _config())
        .root
    )


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.RETURN, "Name"),
        (Surface.RETURN, "str"),
        (Surface.PARAMETER, "Any"),
        (Surface.ATTRIBUTE, "Any"),
    ],
)
def test_leaves_everything_else_alone(surface: Surface, annotation: str) -> None:
    assert (
        not TopTypeReturn()
        .applies(_site(surface, AnnotationText(annotation)), _config())
        .root
    )


def test_is_outside_the_core_preset() -> None:
    assert not core_selection().contains(TopTypeReturn().code)
