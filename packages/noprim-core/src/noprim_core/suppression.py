import functools
import io
import re
import tokenize
from enum import StrEnum

from iterpy import Arr
from pydantic import BaseModel, RootModel

from noprim_core.config import NamePatterns
from noprim_core.rules.code import RuleCode
from noprim_core.site import LineNumber, Qualname, Surface
from noprim_core.source import SourceCode
from noprim_core.violation import Violation
from noprim_types.verdict import Verdict


class SuppressionReason(StrEnum):
    COMMENT = "comment"
    FILE_COMMENT = "file-comment"
    IGNORED_NAME = "ignored-name"
    INNER_CLASS = "inner-class"
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
            rf"#\s*noprim:\s*{re.escape(scope.value)}\s*(?:\[(?P<codes>[^]]*)])?\s*$"
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


def tokens_in(source: SourceCode) -> Arr[tokenize.TokenInfo]:
    # Both parsers read the same stream, so the caller tokenizes once and hands it over.
    return Arr(tokenize.generate_tokens(io.StringIO(source.root).readline))


def _line(token: tokenize.TokenInfo) -> LineNumber:
    return LineNumber(token.start[0])


def _comments(tokens: Arr[tokenize.TokenInfo]) -> Arr[tokenize.TokenInfo]:
    return tokens.filter(lambda token: token.type == tokenize.COMMENT)


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


def _first_code_line(tokens: Arr[tokenize.TokenInfo]) -> LineNumber | None:
    found = tokens.filter(_is_code).take(1).to_list()
    if found == []:
        return None
    return _line(found[0])


def _leading_comments(tokens: Arr[tokenize.TokenInfo]) -> Arr[Comment]:
    # Only the leading block speaks for the module: past the first statement a comment
    # sits beside code, and belongs to that line.
    boundary = _first_code_line(tokens)
    return (
        _comments(tokens)
        .filter(lambda token: boundary is None or _line(token).root < boundary.root)
        .map(lambda token: Comment(token.string))
    )


class IgnoredLines(RootModel[dict[LineNumber, IgnoredCodes]]):
    @classmethod
    def parse(cls, tokens: Arr[tokenize.TokenInfo]) -> "IgnoredLines":
        pairs = (
            _comments(tokens)
            .map(
                lambda token: (
                    _line(token),
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
    def parse(cls, tokens: Arr[tokenize.TokenInfo]) -> "IgnoredFile":
        named = [
            codes
            for codes in _leading_comments(tokens).map(
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


# The walk is the only place that can see who chose an annotation, so it hands over
# the qualnames rather than the tree these readings would each have to walk again.
class OwnedQualnames(RootModel[frozenset[Qualname]]):
    def covers(self, violation: Violation) -> Verdict:
        return Verdict(violation.qualname in self.root)


class Suppressions(BaseModel):
    file: IgnoredFile = IgnoredFile(root=None)
    lines: IgnoredLines = IgnoredLines({})
    parameter_names: NamePatterns = NamePatterns(())
    attribute_names: NamePatterns = NamePatterns(())
    inner_class_owned: OwnedQualnames = OwnedQualnames(frozenset())
    pytest_owned: OwnedQualnames = OwnedQualnames(frozenset())

    def _patterns_for(self, surface: Surface) -> NamePatterns:
        match surface:
            case Surface.PARAMETER:
                return self.parameter_names
            case Surface.ATTRIBUTE:
                return self.attribute_names
            # A return type carries the function's name, not a symbol name of its own.
            case Surface.RETURN:
                return NamePatterns(())

    def _named_as_ignored(self, violation: Violation) -> Verdict:
        return self._patterns_for(violation.surface).matches(violation.qualname.leaf())

    def reason_for(self, violation: Violation) -> SuppressionReason | None:
        if self.file.covers(violation):
            return SuppressionReason.FILE_COMMENT
        if self.lines.covers(violation):
            return SuppressionReason.COMMENT
        if self._named_as_ignored(violation):
            return SuppressionReason.IGNORED_NAME
        if self.inner_class_owned.covers(violation):
            return SuppressionReason.INNER_CLASS
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
