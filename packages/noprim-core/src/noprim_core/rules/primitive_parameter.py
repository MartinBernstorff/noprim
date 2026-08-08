from typing import override

from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import Rule
from noprim_core.site import Site, Surface
from noprim_core.verdict import Verdict


class PrimitiveParameter(Rule):
    code = RuleCode("NOPRIM001")
    on_by_default = Verdict(root=True)

    @override
    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(site.surface == Surface.PARAMETER).and_(
            config.denied.matches(site.names)
        )
