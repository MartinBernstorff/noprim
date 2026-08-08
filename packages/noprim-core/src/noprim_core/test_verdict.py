import pytest
from iterpy import Arr

from noprim_core.verdict import Verdict

TRUE = Verdict(root=True)
FALSE = Verdict(root=False)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (TRUE, TRUE, TRUE),
        (TRUE, FALSE, FALSE),
        (FALSE, TRUE, FALSE),
        (FALSE, FALSE, FALSE),
    ],
)
def test_and(left: Verdict, right: Verdict, expected: Verdict) -> None:
    assert left.and_(right) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (TRUE, TRUE, TRUE),
        (TRUE, FALSE, TRUE),
        (FALSE, TRUE, TRUE),
        (FALSE, FALSE, FALSE),
    ],
)
def test_or(left: Verdict, right: Verdict, expected: Verdict) -> None:
    assert left.or_(right) == expected


@pytest.mark.parametrize(("value", "expected"), [(TRUE, FALSE), (FALSE, TRUE)])
def test_negated(value: Verdict, expected: Verdict) -> None:
    assert value.negated == expected


@pytest.mark.parametrize(("value", "expected"), [(TRUE, TRUE), (FALSE, FALSE)])
def test_holds(value: Verdict, expected: Verdict) -> None:
    assert value.holds is expected.root


@pytest.mark.parametrize(("value", "expected"), [(TRUE, TRUE), (FALSE, FALSE)])
def test_truthiness(value: Verdict, expected: Verdict) -> None:
    assert bool(value) is expected.root


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        ([], FALSE),
        ([FALSE], FALSE),
        ([FALSE, TRUE], TRUE),
        ([TRUE, TRUE], TRUE),
    ],
)
def test_any(verdicts: list[Verdict], expected: Verdict) -> None:
    assert Verdict.any(Arr(verdicts)) == expected
