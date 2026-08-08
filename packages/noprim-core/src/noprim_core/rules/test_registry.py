import importlib
import pkgutil
from types import ModuleType

import pytest
from iterpy import Arr

import noprim_core.rules
from noprim_core.rules.code import RuleCode, Selection, Selector, Selectors
from noprim_core.rules.preset import Preset
from noprim_core.rules.registry import (
    RULES,
    UnknownRuleCodeError,
    UnknownSelectorError,
    core_selection,
    rule_for,
    selection,
)
from noprim_core.rules.rule import Rule


def _rule_modules() -> Arr[ModuleType]:
    return (
        Arr(pkgutil.iter_modules(noprim_core.rules.__path__))
        .filter(lambda found: not found.name.startswith("test_"))
        .map(lambda found: importlib.import_module(f"noprim_core.rules.{found.name}"))
    )


def _rules_defined_in(module: ModuleType) -> Arr[type[Rule]]:
    # `__mro__` rather than `issubclass`: `Rule` is not runtime_checkable.
    return (
        Arr(vars(module).values())
        .filter(lambda value: isinstance(value, type))
        .filter(lambda value: Rule in value.__mro__ and value is not Rule)
        .filter(lambda value: value.__module__ == module.__name__)
    )


def test_every_rule_that_exists_is_registered() -> None:
    assert (
        _rule_modules().map(_rules_defined_in).flatten().to_set()
        == Arr(RULES).map(type).to_set()
    )


def test_a_module_defines_at_most_one_rule() -> None:
    crowded = _rule_modules().filter(lambda m: _rules_defined_in(m).len() > 1).to_list()
    assert crowded == []


def _every_code() -> Selection:
    return Selection(frozenset(Arr(RULES).map(lambda rule: rule.code)))


def _nothing() -> Selectors:
    return Selectors(())


def test_every_code_is_unique() -> None:
    assert len(_every_code().root) == len(RULES)


def test_every_name_is_unique() -> None:
    assert len(Arr(RULES).map(lambda rule: rule.name).to_set()) == len(RULES)


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.code.root)
def test_every_rule_describes_itself(rule: Rule) -> None:
    assert rule.name.root.strip() != ""
    # One line, because the rendered table gives it one row.
    assert rule.example.root.strip().splitlines() == [rule.example.root]


def test_the_core_preset_is_the_primitive_rules() -> None:
    assert core_selection() == Selection(
        frozenset({RuleCode("NOPRIM001"), RuleCode("NOPRIM002"), RuleCode("NOPRIM003")})
    )


@pytest.mark.parametrize(
    ("preset", "expected"),
    [(Preset.CORE, core_selection()), (Preset.ALL, _every_code())],
    ids=["core", "all"],
)
def test_a_preset_is_the_base_selection(preset: Preset, expected: Selection) -> None:
    assert selection(preset, None, _nothing(), _nothing()) == expected


def test_select_replaces_the_preset() -> None:
    chosen = selection(
        Preset.CORE, Selectors((Selector("NOPRIM007"),)), _nothing(), _nothing()
    )
    assert chosen == Selection(frozenset({RuleCode("NOPRIM007")}))


def test_a_selector_is_a_prefix() -> None:
    assert (
        selection(Preset.CORE, Selectors((Selector("NOPRIM"),)), _nothing(), _nothing())
        == _every_code()
    )


def test_ignore_subtracts_from_the_preset() -> None:
    chosen = selection(
        Preset.CORE, None, _nothing(), Selectors((Selector("NOPRIM002"),))
    )
    assert chosen == Selection(
        frozenset({RuleCode("NOPRIM001"), RuleCode("NOPRIM003")})
    )


def test_ignore_wins_over_select() -> None:
    chosen = selection(
        Preset.CORE,
        Selectors((Selector("NOPRIM"),)),
        _nothing(),
        Selectors((Selector("NOPRIM00"),)),
    )
    assert chosen == Selection(frozenset())


def test_extend_select_adds_to_the_preset() -> None:
    chosen = selection(
        Preset.CORE, None, Selectors((Selector("NOPRIM004"),)), _nothing()
    )
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
        _ = selection(Preset.CORE, select, extend, ignore)


def test_rule_for_finds_the_rule_that_owns_a_code() -> None:
    assert rule_for(RuleCode("NOPRIM001")).code == RuleCode("NOPRIM001")


def test_rule_for_rejects_a_code_no_rule_owns() -> None:
    with pytest.raises(UnknownRuleCodeError):
        _ = rule_for(RuleCode("NOPRIM999"))
