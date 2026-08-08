import pytest

from noprim_core.annotations import AnnotationText, names_in_text
from noprim_core.config import CheckConfig, DeniedTypes
from noprim_core.rules.primitive_return import PrimitiveReturn
from noprim_core.rules.registry import default_selection
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


def _config(denied: DeniedTypes) -> CheckConfig:
    return CheckConfig(selection=default_selection(), denied=denied)


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.RETURN, "int"),
        (Surface.RETURN, "list[bool]"),
        (Surface.RETURN, "bool | None"),
    ],
)
def test_applies_to_a_denied_type_on_a_return(
    surface: Surface, annotation: str
) -> None:
    config = _config(DeniedTypes.default())
    assert (
        PrimitiveReturn()
        .applies(_site(surface, AnnotationText(annotation)), config)
        .root
    )


@pytest.mark.parametrize(
    ("surface", "annotation"),
    [
        (Surface.RETURN, "Name"),
        # A bare bool return is the predicate rule's business, not this one's.
        (Surface.RETURN, "bool"),
        (Surface.RETURN, "'bool'"),
        (Surface.PARAMETER, "int"),
        (Surface.ATTRIBUTE, "int"),
    ],
)
def test_leaves_everything_else_alone(surface: Surface, annotation: str) -> None:
    config = _config(DeniedTypes.default())
    assert (
        not PrimitiveReturn()
        .applies(_site(surface, AnnotationText(annotation)), config)
        .root
    )
