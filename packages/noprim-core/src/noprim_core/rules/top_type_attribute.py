from typing import override

from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import Rule
from noprim_core.site import Site, Surface
from noprim_types.verdict import Verdict


class TopTypeAttribute(Rule):
    code = RuleCode("NOPRIM006")
    in_core = Verdict(root=False)

    @override
    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(site.surface == Surface.ATTRIBUTE).and_(
            config.top_types.matches(site.names)
        )
