from iterpy import Arr
from pydantic import BaseModel, RootModel

from noprim_core.annotations import AnnotationText
from noprim_core.checker import Filename, Qualname, Surface, Violation


class BaselineKey(BaseModel, frozen=True):
    filename: Filename
    surface: Surface
    qualname: Qualname
    annotation: AnnotationText

    def __lt__(self, other: "BaselineKey") -> bool:
        return (
            self.filename.root,
            self.qualname.root,
            str(self.surface),
            self.annotation.root,
        ) < (
            other.filename.root,
            other.qualname.root,
            str(other.surface),
            other.annotation.root,
        )


class Baseline(RootModel[frozenset[BaselineKey]]):
    @classmethod
    def empty(cls) -> "Baseline":
        return cls(frozenset())


class KeyedViolation(BaseModel):
    key: BaselineKey
    violation: Violation


class KeyedViolations(RootModel[tuple[KeyedViolation, ...]]):
    pass


class PrunableFiles(RootModel[frozenset[Filename]]):
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
    found = frozenset(entries.map(lambda entry: entry.key))
    untouched = frozenset(
        Arr(baseline.root).filter(lambda key: key.filename not in prunable.root)
    )
    return BaselineOutcome(
        reported=tuple(
            entries.filter(lambda entry: entry.key not in baseline.root).map(
                lambda entry: entry.violation
            )
        ),
        suppressed=tuple(
            entries.filter(lambda entry: entry.key in baseline.root).map(
                lambda entry: entry.violation
            )
        ),
        stale=tuple(sorted(baseline.root - found - untouched)),
        regenerated=Baseline(found | untouched),
    )
