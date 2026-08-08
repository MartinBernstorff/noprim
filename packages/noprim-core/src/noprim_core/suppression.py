import functools
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
    FILE_COMMENT = "file-comment"
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


class IgnoredCodes(RootModel[frozenset[RuleCode] | None]):
    # None is a comment that wrote no brackets at all, which speaks for every rule.
    # Brackets narrow the suppression, so empty brackets narrow it to nothing.
    def covers(self, code: RuleCode) -> Verdict:
        return Verdict(self.root is None or code in self.root)

    def merged(self, other: "IgnoredCodes") -> "IgnoredCodes":
        if self.root is None or other.root is None:
            return IgnoredCodes(root=None)
        return IgnoredCodes(self.root | other.root)


class Scope(StrEnum):
    LINE = "ignore"
    FILE = "ignore-file"


class Comment(RootModel[str]):
    def ignored_codes(self, scope: Scope) -> IgnoredCodes | None:
        # Anchored to end-of-line so a suppression cannot hide behind trailing prose.
        # Searched, not matched, so it can stack after another tool's suppression.
        grammar = re.compile(
            rf"#\s*noprim:\s*{scope.value}\s*(?:\[(?P<codes>[^]]*)])?\s*$"
        )
        found = grammar.search(self.root)
        if found is None:
            return None
        spelled = found.group("codes")
        if spelled is None:
            return IgnoredCodes(root=None)
        return IgnoredCodes(
            frozenset(
                Arr(spelled.split(","))
                .map(str.strip)
                .filter(lambda code: code != "")
                .map(RuleCode)
            )
        )


def _tokens(source: SourceCode) -> Arr[tokenize.TokenInfo]:
    return Arr(tokenize.generate_tokens(io.StringIO(source.root).readline))


def _comments(source: SourceCode) -> Arr[tokenize.TokenInfo]:
    return _tokens(source).filter(lambda token: token.type == tokenize.COMMENT)


def _is_code(token: tokenize.TokenInfo) -> Verdict:
    return Verdict(
        token.type
        not in {
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.ENDMARKER,
        }
    )


def _first_code_line(source: SourceCode) -> LineNumber | None:
    found = _tokens(source).filter(_is_code).take(1).to_list()
    if found == []:
        return None
    return LineNumber(found[0].start[0])


def _leading_comments(source: SourceCode) -> Arr[Comment]:
    # Only the leading block speaks for the module: past the first statement a comment
    # sits beside code, and belongs to that line.
    boundary = _first_code_line(source)
    return (
        _comments(source)
        .filter(lambda token: boundary is None or token.start[0] < boundary.root)
        .map(lambda token: Comment(token.string))
    )


class IgnoredLines(RootModel[dict[LineNumber, IgnoredCodes]]):
    @classmethod
    def parse(cls, source: SourceCode) -> "IgnoredLines":
        pairs = (
            _comments(source)
            .map(
                lambda token: (
                    LineNumber(token.start[0]),
                    Comment(token.string).ignored_codes(Scope.LINE),
                )
            )
            .to_list()
        )
        return cls({line: codes for line, codes in pairs if codes is not None})

    def covers(self, violation: Violation) -> Verdict:
        codes = self.root.get(violation.line)
        return Verdict(root=False) if codes is None else codes.covers(violation.code)


class IgnoredFile(RootModel[IgnoredCodes | None]):
    @classmethod
    def parse(cls, source: SourceCode) -> "IgnoredFile":
        named = [
            codes
            for codes in _leading_comments(source).map(
                lambda comment: comment.ignored_codes(Scope.FILE)
            )
            if codes is not None
        ]
        if named == []:
            return cls(root=None)
        return cls(functools.reduce(IgnoredCodes.merged, named))

    def covers(self, violation: Violation) -> Verdict:
        if self.root is None:
            return Verdict(root=False)
        return self.root.covers(violation.code)


class PytestOwned(RootModel[frozenset[Qualname]]):
    def covers(self, violation: Violation) -> Verdict:
        return Verdict(violation.qualname in self.root)


class Suppressions(BaseModel):
    file: IgnoredFile = IgnoredFile(root=None)
    lines: IgnoredLines = IgnoredLines({})
    names: IgnoredNames = IgnoredNames(frozenset())
    pytest_owned: PytestOwned = PytestOwned(frozenset())

    def _named_as_ignored(self, violation: Violation) -> Verdict:
        # A return type carries the function's name, not a symbol name of its own.
        return Verdict(violation.surface != Surface.RETURN).and_(
            self.names.contains(violation.qualname.leaf())
        )

    def reason_for(self, violation: Violation) -> SuppressionReason | None:
        if self.file.covers(violation):
            return SuppressionReason.FILE_COMMENT
        if self.lines.covers(violation):
            return SuppressionReason.COMMENT
        if self._named_as_ignored(violation):
            return SuppressionReason.IGNORED_NAME
        if self.pytest_owned.covers(violation):
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
