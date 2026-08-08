import io
import re
import tokenize
from enum import StrEnum

from iterpy import Arr
from pydantic import BaseModel, RootModel

from noprim_core.config import IgnoredNames
from noprim_core.rules.code import RuleCode
from noprim_core.site import LineNumber, Qualname, Surface
from noprim_core.source import SourceCode
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation


class SuppressionReason(StrEnum):
    COMMENT = "comment"
    IGNORED_NAME = "ignored-name"
    PYTEST = "pytest"
    BASELINE = "baseline"

    def requested(self) -> Verdict:
        # pytest owning a signature is structural, like a dunder method being exempt.
        # Counting those alongside the ones the author wrote would swamp them.
        return Verdict(self != SuppressionReason.PYTEST)


class SuppressedViolation(BaseModel):
    violation: Violation
    reason: SuppressionReason


class SuppressionOutcome(BaseModel):
    reported: tuple[Violation, ...]
    suppressed: tuple[SuppressedViolation, ...]


class IgnoredCodes(RootModel[frozenset[RuleCode]]):
    def covers(self, code: RuleCode) -> Verdict:
        # A comment that names no code speaks for every rule.
        return Verdict(len(self.root) == 0 or code in self.root)


class Comment(RootModel[str]):
    def ignored_codes(self) -> IgnoredCodes | None:
        # Anchored to end-of-line so a suppression cannot hide behind trailing prose.
        # Searched, not matched, so it can stack after another tool's suppression.
        grammar = re.compile(r"#\s*noprim:\s*ignore\s*(?:\[(?P<codes>[^]]*)])?\s*$")
        found = grammar.search(self.root)
        if found is None:
            return None
        spelled = found.group("codes")
        return IgnoredCodes(
            frozenset()
            if spelled is None
            else frozenset(
                Arr(spelled.split(","))
                .map(str.strip)
                .filter(lambda code: code != "")
                .map(RuleCode)
            )
        )


class IgnoredLines(RootModel[dict[LineNumber, IgnoredCodes]]):
    @classmethod
    def parse(cls, source: SourceCode) -> "IgnoredLines":
        tokens = tokenize.generate_tokens(io.StringIO(source.root).readline)
        pairs = (
            Arr(tokens)
            .filter(lambda token: token.type == tokenize.COMMENT)
            .map(
                lambda token: (
                    LineNumber(token.start[0]),
                    Comment(token.string).ignored_codes(),
                )
            )
            .to_list()
        )
        return cls({line: codes for line, codes in pairs if codes is not None})

    def covers(self, violation: Violation) -> Verdict:
        codes = self.root.get(violation.line)
        return Verdict(root=False) if codes is None else codes.covers(violation.code)


class PytestOwned(RootModel[frozenset[Qualname]]):
    def covers(self, violation: Violation) -> Verdict:
        return Verdict(violation.qualname in self.root)


class Suppressions(BaseModel):
    lines: IgnoredLines = IgnoredLines({})
    names: IgnoredNames = IgnoredNames(frozenset())
    pytest_owned: PytestOwned = PytestOwned(frozenset())

    def _named_as_ignored(self, violation: Violation) -> Verdict:
        # A return type carries the function's name, not a symbol name of its own.
        return Verdict(
            violation.surface != Surface.RETURN
            and self.names.contains(violation.qualname.leaf()).root
        )

    def reason_for(self, violation: Violation) -> SuppressionReason | None:
        if self.lines.covers(violation).root:
            return SuppressionReason.COMMENT
        if self._named_as_ignored(violation).root:
            return SuppressionReason.IGNORED_NAME
        if self.pytest_owned.covers(violation).root:
            return SuppressionReason.PYTEST
        return None

    def apply(self, violations: Arr[Violation]) -> SuppressionOutcome:
        judged = violations.map(
            lambda violation: (violation, self.reason_for(violation))
        ).to_list()
        return SuppressionOutcome(
            reported=tuple(violation for violation, reason in judged if reason is None),
            suppressed=tuple(
                SuppressedViolation(violation=violation, reason=reason)
                for violation, reason in judged
                if reason is not None
            ),
        )
