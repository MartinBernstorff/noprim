from typing import override

from noprim_core.annotations import SymbolName, names_in_text
from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.rules.rule import Rule, RuleMessage
from noprim_core.site import Owner, Site, Surface
from noprim_core.violation import Violation
from noprim_types.verdict import Verdict


# A bare bool flag has no other spelling, so it is the one case with nothing to
# recommend — and the one the typer exemption covers.
def _has_an_alternative(violation: Violation) -> Verdict:
    return Verdict(violation.owner == Owner.TYPER).and_(
        names_in_text(violation.annotation).are_only(SymbolName("bool")).negated
    )


class PrimitiveParameter(Rule):
    code = RuleCode("NOPRIM001")
    on_by_default = Verdict(root=True)

    @override
    def applies(self, site: Site, config: CheckConfig) -> Verdict:
        return Verdict(site.surface == Surface.PARAMETER).and_(
            config.denied.matches(site.names)
        )

    @override
    def message(self, violation: Violation) -> RuleMessage:
        generic = super().message(violation)
        if _has_an_alternative(violation):
            return RuleMessage(
                f"{generic.root}; Typer renders an enum.Enum natively, "
                "and typer.Option(parser=...) takes any type"
            )
        return generic
