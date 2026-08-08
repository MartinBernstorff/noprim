from collections.abc import Iterable

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
    def any(cls, verdicts: Iterable["Verdict"]) -> "Verdict":
        return cls(any(verdict.root for verdict in verdicts))
