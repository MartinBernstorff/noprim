from collections.abc import Callable

import pytest
from pydantic import ValidationError

from noprim_core.config import DeniedTypes
from noprim_core.rules.code import RuleCode, Selector, Selectors
from noprim_core.rules.registry import UnknownSelectorError, default_selection
from noprim_core.settings import (
    AllowedAndDeniedError,
    AllowedNames,
    DeniedNames,
    EmptyNameError,
    NotOnDenyListError,
    PathOverride,
    PathPatterns,
    PerPathError,
    RelativePath,
    Settings,
)
from noprim_core.verdict import Verdict

_ANY = RelativePath("a.py")


def _raised(error: ValidationError, expected: type[ValueError]) -> Verdict:
    details = error.errors()[0]
    context = details.get("ctx")
    # A pydantic error with no cause attached means the helper is broken, not that
    # the wrong exception was raised.
    assert context is not None, details
    cause: object = context["error"]
    if isinstance(cause, PerPathError):
        cause = cause.__cause__
    return Verdict(isinstance(cause, expected))


def test_defaults_resolve_to_the_default_deny_list() -> None:
    assert Settings().resolve(_ANY).denied == DeniedTypes.default()


def test_defaults_resolve_to_the_default_selection() -> None:
    assert Settings().resolve(_ANY).selection == default_selection()


def test_select_narrows_the_rules_that_run() -> None:
    settings = Settings(select=Selectors((Selector("NOPRIM007"),)))
    assert settings.resolve(_ANY).selection.contains(RuleCode("NOPRIM007"))
    assert not settings.resolve(_ANY).selection.contains(RuleCode("NOPRIM001"))


def test_ignore_subtracts_from_the_rules_that_run() -> None:
    settings = Settings(ignore=Selectors((Selector("NOPRIM002"),)))
    assert not settings.resolve(_ANY).selection.contains(RuleCode("NOPRIM002"))
    assert settings.resolve(_ANY).selection.contains(RuleCode("NOPRIM001"))


def test_a_selector_that_names_no_rule_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        _ = Settings(select=Selectors((Selector("NOPRIM999"),)))
    assert _raised(caught.value, UnknownSelectorError)


def test_deny_adds_to_the_deny_list() -> None:
    denied = Settings(deny=DeniedNames(("Enum",))).resolve(_ANY).denied
    assert "Enum" in denied.root


def test_allow_removes_from_the_deny_list() -> None:
    denied = Settings(allow=AllowedNames(("str",))).resolve(_ANY).denied
    assert "str" not in denied.root


def _lenient_on(patterns: PathPatterns) -> PathOverride:
    return PathOverride(paths=patterns, allow=AllowedNames(("str",)))


def test_an_override_applies_only_to_paths_it_matches() -> None:
    settings = Settings(per_path=(_lenient_on(PathPatterns(("test_infra/**",))),))
    assert "str" not in settings.resolve(RelativePath("test_infra/a.py")).denied.root
    assert "str" in settings.resolve(RelativePath("domain/a.py")).denied.root


def test_one_override_can_list_several_patterns() -> None:
    settings = Settings(
        per_path=(_lenient_on(PathPatterns(("test_infra/**", "django_app/**"))),)
    )
    assert "str" not in settings.resolve(RelativePath("django_app/a.py")).denied.root


def test_a_bare_pattern_matches_at_any_depth() -> None:
    settings = Settings(per_path=(_lenient_on(PathPatterns(("test_*.py",))),))
    assert "str" not in settings.resolve(RelativePath("a/b/test_c.py")).denied.root


def test_a_leading_bang_re_includes_a_pattern() -> None:
    settings = Settings(per_path=(_lenient_on(PathPatterns(("**/*.py", "!src/**"))),))
    assert "str" not in settings.resolve(RelativePath("legacy/a.py")).denied.root
    assert "str" in settings.resolve(RelativePath("src/a.py")).denied.root


def test_every_matching_override_contributes() -> None:
    settings = Settings(
        per_path=(
            PathOverride(
                paths=PathPatterns(("domain/**",)), deny=DeniedNames(("Enum",))
            ),
            PathOverride(paths=PathPatterns(("**/*.py",)), deny=DeniedNames(("Flag",))),
        )
    )
    denied = settings.resolve(RelativePath("domain/a.py")).denied.root
    assert {"Enum", "Flag"} <= denied


def test_an_override_can_relax_a_top_level_deny() -> None:
    settings = Settings(
        deny=DeniedNames(("Enum",)),
        per_path=(
            PathOverride(
                paths=PathPatterns(("legacy/**",)), allow=AllowedNames(("Enum",))
            ),
        ),
    )
    assert "Enum" not in settings.resolve(RelativePath("legacy/a.py")).denied.root
    assert "Enum" in settings.resolve(RelativePath("domain/a.py")).denied.root


def test_an_override_can_ignore_a_rule_for_the_paths_it_matches() -> None:
    settings = Settings(
        per_path=(
            PathOverride(
                paths=PathPatterns(("test_*.py",)),
                ignore=Selectors((Selector("NOPRIM002"),)),
            ),
        )
    )
    ignored = settings.resolve(RelativePath("test_a.py")).selection
    assert not ignored.contains(RuleCode("NOPRIM002")).root
    assert (
        settings.resolve(RelativePath("a.py"))
        .selection.contains(RuleCode("NOPRIM002"))
        .root
    )


def test_every_matching_override_contributes_its_ignores() -> None:
    settings = Settings(
        per_path=(
            PathOverride(
                paths=PathPatterns(("domain/**",)),
                ignore=Selectors((Selector("NOPRIM002"),)),
            ),
            PathOverride(
                paths=PathPatterns(("**/*.py",)),
                ignore=Selectors((Selector("NOPRIM003"),)),
            ),
        )
    )
    running = settings.resolve(RelativePath("domain/a.py")).selection.root
    assert {RuleCode("NOPRIM002"), RuleCode("NOPRIM003")}.isdisjoint(running)


def test_an_override_may_ignore_a_rule_the_top_level_did_not_select() -> None:
    settings = Settings(
        select=Selectors((Selector("NOPRIM001"),)),
        per_path=(
            PathOverride(
                paths=PathPatterns(("legacy/**",)),
                ignore=Selectors((Selector("NOPRIM002"),)),
            ),
        ),
    )
    assert (
        settings.resolve(RelativePath("legacy/a.py"))
        .selection.contains(RuleCode("NOPRIM001"))
        .root
    )


def test_an_override_ignoring_a_selector_that_names_no_rule_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        _ = Settings(
            per_path=(
                PathOverride(
                    paths=PathPatterns(("legacy/**",)),
                    ignore=Selectors((Selector("NOPRIM999"),)),
                ),
            )
        )
    assert _raised(caught.value, UnknownSelectorError).root


def test_an_override_allowing_a_name_nothing_denies_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        _ = Settings(
            per_path=(
                PathOverride(
                    paths=PathPatterns(("legacy/**",)), allow=AllowedNames(("Enum",))
                ),
            )
        )
    assert _raised(caught.value, NotOnDenyListError)


def test_a_per_path_complaint_names_the_patterns_it_came_from() -> None:
    with pytest.raises(ValidationError) as caught:
        _ = Settings(
            per_path=(
                PathOverride(
                    paths=PathPatterns(("legacy/**", "vendor/**")),
                    allow=AllowedNames(("Enum",)),
                ),
            )
        )
    assert "legacy/**, vendor/**" in str(caught.value)


def test_an_override_may_allow_a_name_the_top_level_denied() -> None:
    _ = Settings(
        deny=DeniedNames(("Enum",)),
        per_path=(
            PathOverride(
                paths=PathPatterns(("legacy/**",)), allow=AllowedNames(("Enum",))
            ),
        ),
    )


def test_an_override_that_both_allows_and_denies_a_name_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        _ = Settings(
            per_path=(
                PathOverride(
                    paths=PathPatterns(("legacy/**",)),
                    allow=AllowedNames(("str",)),
                    deny=DeniedNames(("str",)),
                ),
            )
        )
    assert _raised(caught.value, AllowedAndDeniedError)


def test_multi_word_keys_are_spelled_with_a_dash() -> None:
    settings = Settings.model_validate(
        {"per-path": [{"paths": ["legacy/**"], "allow": ["str"]}]}
    )
    assert "str" not in settings.resolve(RelativePath("legacy/a.py")).denied.root


def test_exclude_is_carried_through() -> None:
    assert Settings.model_validate({"exclude": ["build/**"]}).exclude == PathPatterns(
        ("build/**",)
    )


@pytest.mark.parametrize(
    "document",
    [{"denied": ["str"]}, {"per-path": [{"path": ["a/**"]}]}],
    ids=["misnamed-key", "misnamed-nested-key"],
)
def test_an_unrecognised_key_is_rejected(document: object) -> None:
    with pytest.raises(ValidationError):
        _ = Settings.model_validate(document)


def test_a_name_both_allowed_and_denied_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        _ = Settings(allow=AllowedNames(("str",)), deny=DeniedNames(("str",)))
    assert _raised(caught.value, AllowedAndDeniedError)


@pytest.mark.parametrize(
    "settings",
    [
        lambda: Settings(allow=AllowedNames(("",))),
        lambda: Settings(deny=DeniedNames(("",))),
    ],
    ids=["allow", "deny"],
)
def test_an_empty_name_is_rejected(settings: Callable[[], Settings]) -> None:
    with pytest.raises(ValidationError) as caught:
        _ = settings()
    assert _raised(caught.value, EmptyNameError)


def test_allowing_a_name_that_is_not_denied_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        _ = Settings(allow=AllowedNames(("Enum",)))
    assert _raised(caught.value, NotOnDenyListError)
