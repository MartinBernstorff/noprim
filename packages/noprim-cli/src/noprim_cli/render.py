from typing import override

from iterpy import Arr
from pydantic import BaseModel, RootModel

from noprim_core.baseline import BaselineOutcome
from noprim_core.rules.registry import rule_for
from noprim_core.site import ColumnNumber, Filename, LineNumber
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation
from noprim_io.baseline import BaselinePath
from noprim_io.check import CheckReport


class Duration(RootModel[float]):
    pass


class Count(RootModel[int]):
    pass


class Noun(RootModel[str]):
    pass


class ExitCode(RootModel[int]):
    pass


class DisplayText(RootModel[str]):
    # Interpolated into other messages, so it has to render as its text and not as
    # the model's repr.
    @override
    def __str__(self) -> str:
        return self.root

    @override
    def __repr__(self) -> str:
        return self.root


class WrittenBaseline(BaseModel):
    path: BaselinePath
    written: Count


class RunOutcome(BaseModel):
    report: CheckReport
    stale: Count = Count(0)
    written: WrittenBaseline | None = None


class RenderOptions(BaseModel):
    quiet: Verdict = Verdict(root=False)


class Rendered(BaseModel):
    stdout: tuple[DisplayText, ...]
    stderr: tuple[DisplayText, ...]
    exit_code: ExitCode


def pretty_duration(duration: Duration) -> DisplayText:
    milliseconds = round(duration.root * 1000)
    seconds, remainder = divmod(milliseconds, 1000)
    if seconds == 0:
        return DisplayText(f"{remainder}ms")
    return DisplayText(f"{milliseconds / 1000:.2f}s")


def _plural(count: Count, noun: Noun) -> DisplayText:
    plural = "" if count.root == 1 else "s"
    return DisplayText(f"{count.root} {noun.root}{plural}")


def _message(violation: Violation) -> DisplayText:
    rule = rule_for(violation.code)
    return DisplayText(f"{violation.code.root} {rule.message(violation).root}")


def _found(report: CheckReport) -> DisplayText:
    suppressed = Count(
        len(
            Arr(report.suppressed)
            .filter(lambda s: bool(s.reason.requested()))
            .to_list()
        )
    )
    clauses = [
        f"found {_plural(Count(len(report.violations)), Noun('violation'))}"
        if len(report.violations) > 0
        else "no violations",
        *([f"{suppressed.root} suppressed"] if suppressed.root > 0 else []),
        *(
            [str(_plural(Count(len(report.errors)), Noun("error")))]
            if len(report.errors) > 0
            else []
        ),
    ]
    return DisplayText(", ".join(clauses))


class Diagnostic(BaseModel):
    filename: Filename
    line: LineNumber
    column: ColumnNumber
    text: DisplayText

    def __lt__(self, other: "Diagnostic") -> bool:
        return (self.filename.root, self.line.root, self.column.root) < (
            other.filename.root,
            other.line.root,
            other.column.root,
        )

    def rendered(self) -> DisplayText:
        return DisplayText(
            f"{self.filename.root}:{self.line.root}:{self.column.root}: {self.text}"
        )


def _diagnostics(report: CheckReport) -> Arr[DisplayText]:
    located: list[Diagnostic] = [
        *(
            Diagnostic(
                filename=v.filename, line=v.line, column=v.column, text=_message(v)
            )
            for v in report.violations
        ),
        *(
            Diagnostic(
                filename=e.filename,
                line=e.line,
                column=e.column,
                text=DisplayText(e.message.root),
            )
            for e in report.errors
        ),
    ]
    return Arr(sorted(located)).map(Diagnostic.rendered)


def _stale_note(count: Count) -> DisplayText:
    subject = (
        f"{count.root} baseline entry no longer matches"
        if count.root == 1
        else f"{count.root} baseline entries no longer match"
    )
    return DisplayText(f"note: {subject}; rerun with --write-baseline to prune")


def _summary_line(
    report: CheckReport, elapsed: Duration, summary: DisplayText
) -> DisplayText:
    return DisplayText(
        f"Checked {_plural(Count(len(report.checked)), Noun('file'))} "
        f"in {pretty_duration(elapsed)} - {summary}"
    )


def _summary(outcome: RunOutcome) -> DisplayText:
    if outcome.written is None:
        return _found(outcome.report)
    written = _plural(outcome.written.written, Noun("violation"))
    return DisplayText(f"wrote {written} to {outcome.written.path.root}")


def _notices(
    outcome: RunOutcome, elapsed: Duration, options: RenderOptions
) -> Arr[DisplayText]:
    if options.quiet.root:
        return Arr([])
    stale = [_stale_note(outcome.stale)] if outcome.stale.root > 0 else []
    return Arr([*stale, _summary_line(outcome.report, elapsed, _summary(outcome))])


def _reportable(outcome: RunOutcome) -> CheckReport:
    # Writing a baseline records the violations rather than reporting them, so only
    # the errors remain worth printing.
    if outcome.written is None:
        return outcome.report
    return outcome.report.model_copy(update={"violations": ()})


def render(outcome: RunOutcome, elapsed: Duration, options: RenderOptions) -> Rendered:
    diagnostics = _diagnostics(_reportable(outcome)).to_list()
    return Rendered(
        stdout=tuple(diagnostics),
        stderr=tuple(_notices(outcome, elapsed, options)),
        exit_code=ExitCode(1 if len(diagnostics) > 0 else 0),
    )


def baseline_written(
    report: CheckReport, outcome: BaselineOutcome, path: BaselinePath
) -> RunOutcome:
    return RunOutcome(
        report=report,
        written=WrittenBaseline(
            path=path, written=Count(len(outcome.regenerated.root))
        ),
    )


def baseline_applied(report: CheckReport, outcome: BaselineOutcome) -> RunOutcome:
    return RunOutcome(
        report=report.model_copy(
            update={
                "violations": outcome.reported,
                "suppressed": report.suppressed + outcome.suppressed,
            }
        ),
        stale=Count(len(outcome.stale)),
    )
