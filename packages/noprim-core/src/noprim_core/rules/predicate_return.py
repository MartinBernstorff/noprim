from typing_extensions import override

from noprim_core.annotations import SymbolName, text_is_exactly
from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import Rule, RuleExample, RuleName
from noprim_core.site import Site, Surface
from noprim_types.verdict import Verdict


def returns_a_bare_bool(site: Site) -> Verdict:
    return Verdict(site.surface == Surface.RETURN).and_(
        text_is_exactly(site.annotation, SymbolName("bool"))
    )


class PredicateReturn(Rule):
    code = RuleCode("NOPRIM007")
    name = RuleName("predicate-return")
    example = RuleExample("def is_ready() -> bool")
    in_core = Verdict(root=False)

    @override
    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return returns_a_bare_bool(site).and_(config.denied.matches(site.names))
