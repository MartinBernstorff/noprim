from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.predicate_return import returns_a_bare_bool
from noprim_core.rules.rule import RuleMessage, annotated
from noprim_core.site import Site, Surface
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation


class PrimitiveReturn:
    code = RuleCode("NOPRIM002")
    on_by_default = Verdict(root=True)

    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(
            site.surface == Surface.RETURN
            and bool(config.denied.matches(site.names))
            # A bare bool return belongs to the predicate rule, which opts in separately.
            and not bool(returns_a_bare_bool(site))
        )

    def message(self, violation: Violation) -> RuleMessage:
        return annotated(violation)
