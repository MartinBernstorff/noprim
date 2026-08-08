import pytest

from noprim_core.annotations import AnnotationText, names_in_text
from noprim_core.config import CheckConfig, DeniedTypes
from noprim_core.rules.registry import default_selection
from noprim_core.rules.top_type_parameter import TopTypeParameter
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


def _config() -> CheckConfig:
    return CheckConfig(selection=default_selection())


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.PARAMETER, "Any"),
        (Surface.PARAMETER, "object"),
        (Surface.PARAMETER, "dict[str, Any]"),
    ],
)
def test_applies_to_a_top_type(surface: Surface, annotation: str) -> None:
    assert (
        TopTypeParameter()
        .applies(_site(surface, AnnotationText(annotation)), _config())
        .root
    )


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.PARAMETER, "Name"),
        (Surface.PARAMETER, "str"),
        (Surface.RETURN, "Any"),
        (Surface.ATTRIBUTE, "Any"),
    ],
)
def test_leaves_everything_else_alone(surface: Surface, annotation: str) -> None:
    assert (
        not TopTypeParameter()
        .applies(_site(surface, AnnotationText(annotation)), _config())
        .root
    )


def test_the_deny_list_does_not_reach_it() -> None:
    config = CheckConfig(
        selection=default_selection(), denied=DeniedTypes(frozenset({"Name"}))
    )
    assert (
        TopTypeParameter()
        .applies(_site(Surface.PARAMETER, AnnotationText("Any")), config)
        .root
    )
    assert (
        not TopTypeParameter()
        .applies(_site(Surface.PARAMETER, AnnotationText("Name")), config)
        .root
    )


def test_is_off_by_default() -> None:
    assert not default_selection().contains(TopTypeParameter().code)
