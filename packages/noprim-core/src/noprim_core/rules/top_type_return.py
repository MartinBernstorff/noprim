from typing_extensions import override

from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.preset import Preset
from noprim_core.rules.rule import Rule, RuleExample, RuleName
from noprim_core.site import Site, Surface
from noprim_types.verdict import Verdict


class TopTypeReturn(Rule):
    code = RuleCode("NOPRIM005")
    name = RuleName("top-type-return")
    example = RuleExample("def payload() -> Any")
    in_preset = Preset.ALL

    @override
    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(site.surface == Surface.RETURN).and_(
            config.top_types.matches(site.names)
        )
