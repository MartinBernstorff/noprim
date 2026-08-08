from enum import StrEnum

from iterpy import Arr
from pydantic import BaseModel, Field, RootModel
from typing_extensions import override

from noprim_core.annotations import AnnotationText
from noprim_core.baseline import BaselineOutcome
from noprim_core.rules.code import RuleCode
from noprim_core.rules.registry import rule_for
from noprim_core.site import ColumnNumber, Filename, LineNumber, Qualname, Surface
from noprim_core.violation import Violation
from noprim_io.baseline import BaselinePath
from noprim_io.check import CheckReport, ErrorMessage
from noprim_types.verdict import Verdict


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


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


class GroupAxis(StrEnum):
    RULE = "rule"
    TYPE = "type"
    NAME = "name"
    PATH = "path"


class GroupAxes(RootModel[tuple[GroupAxis, ...]]):
    @classmethod
    def default(cls) -> "GroupAxes":
        return cls((GroupAxis.RULE,))


class RenderOptions(BaseModel):
    quiet: Verdict = Verdict(root=False)
    output_format: OutputFormat = OutputFormat.TEXT
    statistics: Verdict = Verdict(root=False)
    group_by: GroupAxes = Field(default_factory=GroupAxes.default)


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
        len(Arr(report.suppressed).filter(lambda s: s.reason.requested()).to_list())
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


def _error_diagnostics(report: CheckReport) -> Arr[Diagnostic]:
    return Arr(
        [
            Diagnostic(
                filename=e.filename,
                line=e.line,
                column=e.column,
                text=DisplayText(e.message.root),
            )
            for e in report.errors
        ]
    )


def _diagnostics(report: CheckReport) -> Arr[DisplayText]:
    located = [
        *(
            Diagnostic(
                filename=v.filename, line=v.line, column=v.column, text=_message(v)
            )
            for v in report.violations
        ),
        *_error_diagnostics(report),
    ]
    return Arr(sorted(located)).map(Diagnostic.rendered)


class JsonViolation(BaseModel):
    path: Filename
    line: LineNumber
    column: ColumnNumber
    code: RuleCode
    surface: Surface
    name: Qualname
    qualname: Qualname
    annotation: AnnotationText


class JsonError(BaseModel):
    path: Filename
    line: LineNumber
    column: ColumnNumber
    message: ErrorMessage


class JsonReport(BaseModel):
    violations: tuple[JsonViolation, ...]
    errors: tuple[JsonError, ...]


def _json_errors(report: CheckReport) -> tuple[JsonError, ...]:
    return tuple(
        JsonError(path=e.filename, line=e.line, column=e.column, message=e.message)
        for e in report.errors
    )


def _json_report(report: CheckReport) -> JsonReport:
    return JsonReport(
        violations=tuple(
            JsonViolation(
                path=v.filename,
                line=v.line,
                column=v.column,
                code=v.code,
                surface=v.surface,
                name=v.qualname.leaf(),
                qualname=v.qualname,
                annotation=v.annotation,
            )
            for v in report.violations
        ),
        errors=_json_errors(report),
    )


class Group(BaseModel):
    values: tuple[DisplayText, ...]
    count: Count

    # Ties break on the axis values, so diffing two runs shows what changed rather
    # than what the walk happened to reach first.
    def __lt__(self, other: "Group") -> bool:
        return (-self.count.root, tuple(v.root for v in self.values)) < (
            -other.count.root,
            tuple(v.root for v in other.values),
        )


class JsonGroup(BaseModel):
    count: Count
    rule: DisplayText | None = None
    type: DisplayText | None = None
    name: DisplayText | None = None
    path: DisplayText | None = None


class JsonStatistics(BaseModel):
    statistics: tuple[JsonGroup, ...]
    # A file that would not parse contributed no violations to any count, so the
    # counts are only trustworthy alongside it.
    errors: tuple[JsonError, ...]


def _axis_value(violation: Violation, axis: GroupAxis) -> DisplayText:
    match axis:
        case GroupAxis.RULE:
            return DisplayText(violation.code.root)
        case GroupAxis.TYPE:
            return DisplayText(violation.annotation.root)
        case GroupAxis.NAME:
            return DisplayText(violation.qualname.leaf().root)
        case GroupAxis.PATH:
            return DisplayText(violation.filename.root)


def _axis_values(violation: Violation, axes: GroupAxes) -> tuple[DisplayText, ...]:
    return tuple(_axis_value(violation, axis) for axis in axes.root)


class GroupKey(RootModel[str]):
    @classmethod
    def of(cls, violation: Violation, axes: GroupAxes) -> "GroupKey":
        # A separator no annotation, path or identifier can contain, so two axes
        # cannot collide into one key.
        return cls("\x00".join(v.root for v in _axis_values(violation, axes)))


def _groups(report: CheckReport, axes: GroupAxes) -> Arr[Group]:
    grouped = (
        Arr(report.violations)
        .groupby(lambda v: GroupKey.of(v, axes).root)
        .map(
            lambda pair: Group(
                values=_axis_values(pair[1][0], axes), count=Count(len(pair[1]))
            )
        )
    )
    return Arr(sorted(grouped))


def _statistics_lines(groups: Arr[Group]) -> Arr[DisplayText]:
    width = max((len(str(group.count.root)) for group in groups), default=0)
    return groups.map(
        lambda group: DisplayText(
            "  ".join([f"{group.count.root:>{width}}", *(v.root for v in group.values)])
        )
    )


def _json_group(group: Group, axes: GroupAxes) -> JsonGroup:
    return JsonGroup(
        count=group.count,
        **dict(zip((axis.value for axis in axes.root), group.values, strict=True)),
    )


def _document(payload: BaseModel) -> Arr[DisplayText]:
    return Arr([DisplayText(payload.model_dump_json(indent=2, exclude_none=True))])


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
    if options.quiet:
        return Arr([])
    stale = [_stale_note(outcome.stale)] if outcome.stale.root > 0 else []
    return Arr([*stale, _summary_line(outcome.report, elapsed, _summary(outcome))])


def _reportable(outcome: RunOutcome) -> CheckReport:
    # Writing a baseline records the violations rather than reporting them, so only
    # the errors remain worth printing.
    if outcome.written is None:
        return outcome.report
    return outcome.report.model_copy(update={"violations": ()})


def _statistics(report: CheckReport, options: RenderOptions) -> Arr[DisplayText]:
    groups = _groups(report, options.group_by)
    if options.output_format == OutputFormat.JSON:
        return _document(
            JsonStatistics(
                statistics=tuple(
                    groups.map(lambda group: _json_group(group, options.group_by))
                ),
                errors=_json_errors(report),
            )
        )
    # A count cannot express a file that would not parse, so those keep their line.
    return (
        _error_diagnostics(report)
        .map(Diagnostic.rendered)
        .chain(_statistics_lines(groups))
    )


def _body(report: CheckReport, options: RenderOptions) -> Arr[DisplayText]:
    if options.statistics:
        return _statistics(report, options)
    if options.output_format == OutputFormat.JSON:
        return _document(_json_report(report))
    return _diagnostics(report)


def render(outcome: RunOutcome, elapsed: Duration, options: RenderOptions) -> Rendered:
    report = _reportable(outcome)
    found = len(report.violations) + len(report.errors)
    return Rendered(
        stdout=tuple(_body(report, options)),
        stderr=tuple(_notices(outcome, elapsed, options)),
        exit_code=ExitCode(1 if found > 0 else 0),
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
