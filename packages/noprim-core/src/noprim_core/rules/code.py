from pydantic import ConfigDict, RootModel

from noprim_types.verdict import Verdict


class RuleCode(RootModel[str]):
    # Hashed as part of a baseline key.
    model_config = ConfigDict(frozen=True)


class Selector(RootModel[str]):
    # A prefix, as in ruff: "NOPRIM" names every rule, "NOPRIM001" one of them.
    def matches(self, code: RuleCode) -> Verdict:
        return Verdict(code.root.startswith(self.root))


class Selectors(RootModel[tuple[Selector, ...]]):
    pass


class Selection(RootModel[frozenset[RuleCode]]):
    def contains(self, code: RuleCode) -> Verdict:
        return Verdict(code in self.root)
