from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import RuleMessage, annotated
from noprim_core.site import Site, Surface
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation


class PrimitiveParameter:
    code = RuleCode("NOPRIM001")
    on_by_default = Verdict(root=True)

    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(site.surface == Surface.PARAMETER).and_(
            config.denied.matches(site.names)
        )

    def message(self, violation: Violation) -> RuleMessage:
        return annotated(violation)
