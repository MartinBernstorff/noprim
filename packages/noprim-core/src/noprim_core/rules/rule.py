from typing import Protocol

from pydantic import RootModel

from noprim_core.config import CheckConfig
from noprim_core.rules.code import RuleCode
from noprim_core.site import Site, Surface
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation


class RuleMessage(RootModel[str]):
    pass


class Rule(Protocol):
    # Properties, not declarations: an unset declared attribute typechecks clean.
    @property
    def code(self) -> RuleCode: ...

    @property
    def on_by_default(self) -> Verdict: ...

    def applies(self, site: Site, config: CheckConfig) -> Verdict: ...

    def message(self, violation: Violation) -> RuleMessage:
        name = violation.qualname.leaf().root
        annotation = violation.annotation.root
        match violation.surface:
            case Surface.PARAMETER:
                return RuleMessage(f'parameter "{name}" is annotated "{annotation}"')
            case Surface.RETURN:
                return RuleMessage(f'return type is annotated "{annotation}"')
            case Surface.ATTRIBUTE:
                return RuleMessage(f'attribute "{name}" is annotated "{annotation}"')
