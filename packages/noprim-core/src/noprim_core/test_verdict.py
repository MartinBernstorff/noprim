import pytest
from iterpy import Arr

from noprim_core.verdict import Verdict

YES = Verdict(root=True)
NO = Verdict(root=False)


@pytest.mark.parametrize(
    ("left", "right", "conjunction", "disjunction"),
    [
        (YES, YES, YES, YES),
        (YES, NO, NO, YES),
        (NO, YES, NO, YES),
        (NO, NO, NO, NO),
    ],
)
def test_combines_two_verdicts(
    left: Verdict, right: Verdict, conjunction: Verdict, disjunction: Verdict
) -> None:
    assert left.and_(right) == conjunction
    assert left.or_(right) == disjunction


@pytest.mark.parametrize(("given", "expected"), [(YES, NO), (NO, YES)])
def test_negates(given: Verdict, expected: Verdict) -> None:
    assert given.negated == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (Arr([]), NO),
        (Arr([NO, NO]), NO),
        (Arr([NO, YES]), YES),
        (Arr([YES, YES]), YES),
    ],
    ids=["none", "all-no", "one-yes", "all-yes"],
)
def test_any_holds_when_one_does(given: Arr[Verdict], expected: Verdict) -> None:
    assert Verdict.any(given) == expected
