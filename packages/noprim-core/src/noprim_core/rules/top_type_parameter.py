from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode, RuleName
from noprim_core.rules.rule import RuleMessage, annotated
from noprim_core.site import Site, Surface
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation


class TopTypeParameter:
    code = RuleCode("NOPRIM004")
    name = RuleName("top-type-parameter")
    default = Verdict(root=False)

    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(
            site.surface == Surface.PARAMETER
            and bool(config.top_types.matches(site.names))
        )

    def message(self, violation: Violation) -> RuleMessage:
        return annotated(violation)
