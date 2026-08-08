from iterpy import Arr
from pydantic import RootModel


class Verdict(RootModel[bool]):
    def __bool__(self) -> bool:
        return self.root

    def and_(self, other: "Verdict") -> "Verdict":
        return Verdict(self.root and other.root)

    def or_(self, other: "Verdict") -> "Verdict":
        return Verdict(self.root or other.root)

    @property
    def negated(self) -> "Verdict":
        return Verdict(not self.root)

    @classmethod
    def any(cls, verdicts: Arr["Verdict"]) -> "Verdict":
        return cls(verdicts.any(lambda verdict: verdict.root))
