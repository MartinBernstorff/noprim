from iterpy import Arr
from pydantic import BaseModel, RootModel

from noprim_core.checker import Surface, Violation


class BaselineKey(BaseModel, frozen=True):
    filename: str
    surface: Surface
    qualname: str
    annotation: str


class Baseline(RootModel[frozenset[BaselineKey]]):
    @classmethod
    def empty(cls) -> "Baseline":
        return cls(frozenset())


class KeyedViolation(BaseModel):
    key: BaselineKey
    violation: Violation


class KeyedViolations(RootModel[tuple[KeyedViolation, ...]]):
    pass


class PrunableFiles(RootModel[frozenset[str]]):
    pass


class BaselineOutcome(BaseModel):
    reported: tuple[Violation, ...]
    suppressed: tuple[Violation, ...]
    stale: tuple[BaselineKey, ...]
    regenerated: Baseline


def apply_baseline(
    keyed: KeyedViolations, baseline: Baseline, prunable: PrunableFiles
) -> BaselineOutcome:
    entries = Arr(keyed.root)
    found = frozenset(entries.map(lambda e: e.key))
    untouched = frozenset(
        Arr(baseline.root).filter(lambda key: key.filename not in prunable.root)
    )
    return BaselineOutcome(
        reported=tuple(
            entries.filter(lambda e: e.key not in baseline.root).map(
                lambda e: e.violation
            )
        ),
        suppressed=tuple(
            entries.filter(lambda e: e.key in baseline.root).map(lambda e: e.violation)
        ),
        stale=tuple(sorted(baseline.root - found - untouched, key=_ordering)),
        regenerated=Baseline(found | untouched),
    )


def _ordering(key: BaselineKey) -> tuple[str, str, str, str]:
    return (key.filename, key.qualname, str(key.surface), key.annotation)
