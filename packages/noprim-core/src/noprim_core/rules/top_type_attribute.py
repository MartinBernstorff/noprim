from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import RuleMessage, annotated
from noprim_core.site import Site, Surface
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation


class TopTypeAttribute:
    code = RuleCode("NOPRIM006")
    on_by_default = Verdict(root=False)

    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(
            site.surface == Surface.ATTRIBUTE
            and bool(config.top_types.matches(site.names))
        )

    def message(self, violation: Violation) -> RuleMessage:
        return annotated(violation)
