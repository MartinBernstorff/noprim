import pytest

from noprim_core.annotations import AnnotationText, names_in_text
from noprim_core.config import CheckConfig, DeniedTypes
from noprim_core.rules.predicate_return import PredicateReturn
from noprim_core.rules.registry import default_selection
from noprim_core.site import ColumnNumber, LineNumber, Qualname, Site, Surface


def _site(surface: Surface, annotation: AnnotationText) -> Site:
    return Site(
        line=LineNumber(1),
        column=ColumnNumber(1),
        surface=surface,
        qualname=Qualname("is_ready"),
        annotation=annotation,
        names=names_in_text(annotation),
    )


def _config(denied: DeniedTypes) -> CheckConfig:
    return CheckConfig(selection=default_selection(), denied=denied)


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.RETURN, "bool"),
        (Surface.RETURN, "'bool'"),
    ],
)
def test_applies_to_a_bare_bool_return(surface: Surface, annotation: str) -> None:
    config = _config(DeniedTypes.default())
    assert (
        PredicateReturn()
        .applies(_site(surface, AnnotationText(annotation)), config)
        .root
    )


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.RETURN, "bool | None"),
        (Surface.RETURN, "list[bool]"),
        (Surface.PARAMETER, "bool"),
        (Surface.ATTRIBUTE, "bool"),
    ],
)
def test_leaves_everything_else_alone(surface: Surface, annotation: str) -> None:
    config = _config(DeniedTypes.default())
    assert (
        not PredicateReturn()
        .applies(_site(surface, AnnotationText(annotation)), config)
        .root
    )


def test_allowing_bool_takes_predicates_off_the_table() -> None:
    config = _config(DeniedTypes(DeniedTypes.default().root - {"bool"}))
    assert (
        not PredicateReturn()
        .applies(_site(Surface.RETURN, AnnotationText("bool")), config)
        .root
    )


def test_is_off_by_default() -> None:
    assert not default_selection().contains(PredicateReturn().code).root
