from iterpy import Arr

from noprim_core.rules.code import RuleCode, Selection, Selector, Selectors
from noprim_core.rules.predicate_return import PredicateReturn
from noprim_core.rules.primitive_attribute import PrimitiveAttribute
from noprim_core.rules.primitive_parameter import PrimitiveParameter
from noprim_core.rules.primitive_return import PrimitiveReturn
from noprim_core.rules.rule import Rule
from noprim_core.rules.top_type_attribute import TopTypeAttribute
from noprim_core.rules.top_type_parameter import TopTypeParameter
from noprim_core.rules.top_type_return import TopTypeReturn
from noprim_core.verdict import Verdict

RULES: tuple[Rule, ...] = (
    PrimitiveParameter(),
    PrimitiveReturn(),
    PrimitiveAttribute(),
    TopTypeParameter(),
    TopTypeReturn(),
    TopTypeAttribute(),
    PredicateReturn(),
)


class UnknownSelectorError(ValueError):
    def __init__(self, selectors: Selectors) -> None:
        spelled = ", ".join(selector.root for selector in selectors.root)
        super().__init__(f"no rule matches: {spelled}")


class UnknownRuleCodeError(ValueError):
    def __init__(self, code: RuleCode) -> None:
        super().__init__(f"no rule with code {code.root}")


def rule_for(code: RuleCode) -> Rule:
    found = Arr(RULES).filter(lambda rule: rule.code == code).to_list()
    if len(found) == 0:
        raise UnknownRuleCodeError(code)
    return found[0]


def default_selection() -> Selection:
    return Selection(
        frozenset(
            Arr(RULES)
            .filter(lambda rule: bool(rule.on_by_default))
            .map(lambda rule: rule.code)
        )
    )


def _matches_any(code: RuleCode, selectors: Selectors) -> Verdict:
    return Verdict(
        Arr(selectors.root).any(lambda selector: bool(selector.matches(code)))
    )


def _selected(selectors: Selectors) -> Selection:
    return Selection(
        frozenset(
            Arr(RULES)
            .filter(lambda rule: bool(_matches_any(rule.code, selectors)))
            .map(lambda rule: rule.code)
        )
    )


def _matches_nothing(selector: Selector) -> Verdict:
    return Verdict(len(_selected(Selectors((selector,))).root) == 0)


def _validated(selectors: Selectors) -> None:
    # A selector that names no rule is a typo, and silently doing nothing is the
    # failure this validation exists to prevent.
    unknown = Arr(selectors.root).filter(lambda s: bool(_matches_nothing(s))).to_list()
    if len(unknown) > 0:
        raise UnknownSelectorError(Selectors(tuple(unknown)))


def selection(
    select: Selectors | None, extend: Selectors, ignore: Selectors
) -> Selection:
    _validated(extend)
    _validated(ignore)
    if select is not None:
        _validated(select)
    chosen = default_selection() if select is None else _selected(select)
    return Selection((chosen.root | _selected(extend).root) - _selected(ignore).root)
