import pytest

from noprim_types.replacements import Replacements, ReplacementTable, TypeName

_TABLE = ReplacementTable.default()


@pytest.mark.parametrize("denied", sorted(name.root for name in _TABLE.covered))
def test_every_entry_recommends_something(denied: str) -> None:
    assert _TABLE.suggestions_for(TypeName(denied)).root != ()


def test_an_uncovered_name_recommends_nothing() -> None:
    assert _TABLE.suggestions_for(TypeName("Widget")) == Replacements(())


def test_bool_recommends_the_verdict_this_package_ships() -> None:
    assert TypeName("Verdict") in _TABLE.suggestions_for(TypeName("bool")).root
