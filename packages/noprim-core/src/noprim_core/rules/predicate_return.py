from noprim_core.annotations import SymbolName, text_is_exactly
from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import RuleMessage, annotated
from noprim_core.site import Site, Surface
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation


def returns_a_bare_bool(site: Site) -> Verdict:
    return Verdict(site.surface == Surface.RETURN).and_(
        text_is_exactly(site.annotation, SymbolName("bool"))
    )


class PredicateReturn:
    code = RuleCode("NOPRIM007")
    on_by_default = Verdict(root=False)

    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return returns_a_bare_bool(site).and_(config.denied.matches(site.names))

    def message(self, violation: Violation) -> RuleMessage:
        return annotated(violation)
