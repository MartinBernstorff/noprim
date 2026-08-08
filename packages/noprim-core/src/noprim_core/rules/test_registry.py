import pytest
from iterpy import Arr

from noprim_core.rules.code import RuleCode, Selection, Selector, Selectors
from noprim_core.rules.registry import (
    RULES,
    UnknownRuleCodeError,
    UnknownSelectorError,
    default_selection,
    rule_for,
    selection,
)


def _every_code() -> Selection:
    return Selection(frozenset(Arr(RULES).map(lambda rule: rule.code)))


def _nothing() -> Selectors:
    return Selectors(())


def test_every_code_is_unique() -> None:
    assert len(_every_code().root) == len(RULES)


def test_the_defaults_are_the_primitive_rules() -> None:
    assert default_selection() == Selection(
        frozenset({RuleCode("NOPRIM001"), RuleCode("NOPRIM002"), RuleCode("NOPRIM003")})
    )


def test_select_replaces_the_defaults() -> None:
    chosen = selection(Selectors((Selector("NOPRIM007"),)), _nothing(), _nothing())
    assert chosen == Selection(frozenset({RuleCode("NOPRIM007")}))


def test_a_selector_is_a_prefix() -> None:
    assert (
        selection(Selectors((Selector("NOPRIM"),)), _nothing(), _nothing())
        == _every_code()
    )


def test_ignore_subtracts_from_the_defaults() -> None:
    chosen = selection(None, _nothing(), Selectors((Selector("NOPRIM002"),)))
    assert chosen == Selection(
        frozenset({RuleCode("NOPRIM001"), RuleCode("NOPRIM003")})
    )


def test_ignore_wins_over_select() -> None:
    chosen = selection(
        Selectors((Selector("NOPRIM"),)), _nothing(), Selectors((Selector("NOPRIM00"),))
    )
    assert chosen == Selection(frozenset())


def test_extend_select_adds_to_the_defaults() -> None:
    chosen = selection(None, Selectors((Selector("NOPRIM004"),)), _nothing())
    assert chosen == Selection(
        frozenset(
            {
                RuleCode("NOPRIM001"),
                RuleCode("NOPRIM002"),
                RuleCode("NOPRIM003"),
                RuleCode("NOPRIM004"),
            }
        )
    )


@pytest.mark.parametrize(
    ("select", "extend", "ignore"),
    [
        (Selectors((Selector("NOPRIM999"),)), Selectors(()), Selectors(())),
        (None, Selectors((Selector("NOPRIM999"),)), Selectors(())),
        (None, Selectors(()), Selectors((Selector("XYZ"),))),
    ],
    ids=["select", "extend-select", "ignore"],
)
def test_a_selector_that_names_no_rule_is_rejected(
    select: Selectors | None, extend: Selectors, ignore: Selectors
) -> None:
    with pytest.raises(UnknownSelectorError):
        _ = selection(select, extend, ignore)


def test_rule_for_finds_the_rule_that_owns_a_code() -> None:
    assert rule_for(RuleCode("NOPRIM001")).code == RuleCode("NOPRIM001")


def test_rule_for_rejects_a_code_no_rule_owns() -> None:
    with pytest.raises(UnknownRuleCodeError):
        _ = rule_for(RuleCode("NOPRIM999"))
