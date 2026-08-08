from iterpy import Arr
from pydantic import BaseModel, RootModel

from noprim_core.annotations import AnnotationText
from noprim_core.rules.code import RuleCode
from noprim_core.site import Filename, Qualname, Surface
from noprim_core.suppression import SuppressedViolation, SuppressionReason
from noprim_core.violation import Violation


class BaselineKey(BaseModel, frozen=True):
    filename: Filename
    code: RuleCode
    surface: Surface
    qualname: Qualname
    annotation: AnnotationText

    def __lt__(self, other: "BaselineKey") -> bool:
        return (
            self.filename.root,
            self.qualname.root,
            str(self.surface),
            self.annotation.root,
            self.code.root,
        ) < (
            other.filename.root,
            other.qualname.root,
            str(other.surface),
            other.annotation.root,
            other.code.root,
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
    suppressed: tuple[SuppressedViolation, ...]
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
                lambda entry: SuppressedViolation(
                    violation=entry.violation, reason=SuppressionReason.BASELINE
                )
            )
        ),
        stale=tuple(sorted(baseline.root - found - untouched)),
        regenerated=Baseline(found | untouched),
    )
