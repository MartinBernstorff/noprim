from typing_extensions import override

from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import Rule
from noprim_core.site import Site, Surface
from noprim_types.verdict import Verdict


class TopTypeReturn(Rule):
    code = RuleCode("NOPRIM005")
    on_by_default = Verdict(root=False)

    @override
    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(site.surface == Surface.RETURN).and_(
            config.top_types.matches(site.names)
        )
