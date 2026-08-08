from typing import override

from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.predicate_return import returns_a_bare_bool
from noprim_core.rules.rule import Rule
from noprim_core.site import Site, Surface
from noprim_types.verdict import Verdict


class PrimitiveReturn(Rule):
    code = RuleCode("NOPRIM002")
    on_by_default = Verdict(root=True)

    @override
    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return (
            Verdict(site.surface == Surface.RETURN)
            .and_(config.denied.matches(site.names))
            # A bare bool return belongs to the predicate rule, which opts in separately.
            .and_(returns_a_bare_bool(site).negated)
        )
