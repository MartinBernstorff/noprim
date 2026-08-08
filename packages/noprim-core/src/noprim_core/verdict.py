from iterpy import Arr
from pydantic import RootModel


class Verdict(RootModel[bool]):
    # Without it `bool(verdict)` is silently the always-true identity of an object,
    # and no typechecker catches that; `if verdict:` pyrefly does catch.
    def __bool__(self) -> bool:
        return self.root

    @property
    def holds(self) -> bool:
        return self.root

    @property
    def negated(self) -> "Verdict":
        return Verdict(not self.root)

    def and_(self, other: "Verdict") -> "Verdict":
        return Verdict(self.root and other.root)

    def or_(self, other: "Verdict") -> "Verdict":
        return Verdict(self.root or other.root)

    @staticmethod
    def any(verdicts: Arr["Verdict"]) -> "Verdict":
        return Verdict(verdicts.any(lambda verdict: verdict.holds))
