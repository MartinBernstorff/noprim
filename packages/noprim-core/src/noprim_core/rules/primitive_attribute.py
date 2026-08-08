from typing import override

from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import Rule, RuleExample, RuleName
from noprim_core.site import Site, Surface
from noprim_types.verdict import Verdict


class PrimitiveAttribute(Rule):
    code = RuleCode("NOPRIM003")
    name = RuleName("primitive-attribute")
    example = RuleExample("class Order: id: str")
    in_core = Verdict(root=True)

    @override
    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(site.surface == Surface.ATTRIBUTE).and_(
            config.denied.matches(site.names)
        )
