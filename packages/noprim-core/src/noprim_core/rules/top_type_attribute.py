from typing_extensions import override

from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import Rule, RuleExample, RuleName
from noprim_core.site import Site, Surface
from noprim_types.verdict import Verdict


class TopTypeAttribute(Rule):
    code = RuleCode("NOPRIM006")
    name = RuleName("top-type-attribute")
    example = RuleExample("class Order: meta: Any")
    in_core = Verdict(root=False)

    @override
    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(site.surface == Surface.ATTRIBUTE).and_(
            config.top_types.matches(site.names)
        )
