import json
from pathlib import Path

import pytest
from pydantic import RootModel

from noprim_cli.render import (
    Count,
    Duration,
    GroupAxes,
    GroupAxis,
    OutputFormat,
    Rendered,
    RenderOptions,
    RunOutcome,
    WrittenBaseline,
    pretty_duration,
    render,
)
from noprim_core.annotations import AnnotationText
from noprim_core.rules.code import RuleCode
from noprim_core.site import (
    ColumnNumber,
    Filename,
    LineNumber,
    Qualname,
    Surface,
)
from noprim_core.suppression import SuppressedViolation, SuppressionReason
from noprim_core.violation import Violation
from noprim_io.baseline import BaselinePath
from noprim_io.check import CheckReport, ErrorMessage, FileError
from noprim_io.paths import SourceFile
from noprim_types.verdict import Verdict


def _at(filename: Filename, line: LineNumber, column: ColumnNumber) -> Violation:
    return Violation(
        filename=filename,
        code=RuleCode("NOPRIM001"),
        line=line,
        column=column,
        surface=Surface.PARAMETER,
        qualname=Qualname("f.a"),
        annotation=AnnotationText("int"),
    )


def _error(filename: Filename, line: LineNumber) -> FileError:
    return FileError(
        filename=filename,
        line=line,
        column=ColumnNumber(1),
        message=ErrorMessage("syntax error: invalid syntax"),
    )


def _report(
    violations: tuple[Violation, ...],
    errors: tuple[FileError, ...],
    checked: Count,
    suppressed: tuple[SuppressedViolation, ...] = (),
) -> CheckReport:
    return CheckReport(
        violations=violations,
        errors=errors,
        checked=tuple(SourceFile(Path(f"f{n}.py")) for n in range(checked.root)),
        suppressed=suppressed,
    )


def _suppressed(
    reason: SuppressionReason, count: Count
) -> tuple[SuppressedViolation, ...]:
    return tuple(
        SuppressedViolation(
            violation=_at(Filename("a.py"), LineNumber(n + 1), ColumnNumber(1)),
            reason=reason,
        )
        for n in range(count.root)
    )


def _nothing() -> CheckReport:
    return _report((), (), Count(1))


def _one_violation() -> CheckReport:
    return _report(
        (_at(Filename("a.py"), LineNumber(1), ColumnNumber(1)),), (), Count(1)
    )


def _wrote(count: Count) -> WrittenBaseline:
    return WrittenBaseline(path=BaselinePath(Path(".noprim.json")), written=count)


def _rendered(outcome: RunOutcome, options: RenderOptions) -> Rendered:
    return render(outcome, Duration(0.5), options)


def _loud(outcome: RunOutcome) -> Rendered:
    return _rendered(outcome, RenderOptions())


class JsonDocument(RootModel[dict[str, object]]):
    pass


def _as_json(outcome: RunOutcome, options: RenderOptions) -> JsonDocument:
    rendered = _rendered(outcome, options)
    return JsonDocument(json.loads("\n".join(line.root for line in rendered.stdout)))


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "0ms"),
        (0.38, "380ms"),
        (0.9999, "1.00s"),
        (1.0, "1.00s"),
        (1.2351, "1.24s"),
        (62.5, "62.50s"),
    ],
)
def test_pretty_duration(seconds: float, expected: str) -> None:
    assert pretty_duration(Duration(seconds)).root == expected


@pytest.mark.parametrize(
    ("code", "surface", "expected"),
    [
        (
            "NOPRIM001",
            Surface.PARAMETER,
            'a.py:2:7: NOPRIM001 parameter "user_id" is annotated "str"',
        ),
        (
            "NOPRIM002",
            Surface.RETURN,
            'a.py:2:7: NOPRIM002 return type is annotated "str"',
        ),
        (
            "NOPRIM003",
            Surface.ATTRIBUTE,
            'a.py:2:7: NOPRIM003 attribute "user_id" is annotated "str"',
        ),
    ],
)
def test_names_the_rule_and_surface_it_found(
    code: str, surface: Surface, expected: str
) -> None:
    violation = Violation(
        filename=Filename("a.py"),
        code=RuleCode(code),
        line=LineNumber(2),
        column=ColumnNumber(7),
        surface=surface,
        qualname=Qualname("greet.user_id"),
        annotation=AnnotationText("str"),
    )

    rendered = _loud(RunOutcome(report=_report((violation,), (), Count(1))))

    assert [line.root for line in rendered.stdout] == [expected]


def test_sorts_diagnostics_by_path_line_and_column() -> None:
    report = _report(
        (
            _at(Filename("b.py"), LineNumber(1), ColumnNumber(1)),
            _at(Filename("a.py"), LineNumber(2), ColumnNumber(1)),
            _at(Filename("a.py"), LineNumber(1), ColumnNumber(9)),
            _at(Filename("a.py"), LineNumber(1), ColumnNumber(3)),
        ),
        (),
        Count(2),
    )

    rendered = _loud(RunOutcome(report=report))

    assert [line.root.split(":")[:3] for line in rendered.stdout] == [
        ["a.py", "1", "3"],
        ["a.py", "1", "9"],
        ["a.py", "2", "1"],
        ["b.py", "1", "1"],
    ]


def test_interleaves_file_errors_with_violations() -> None:
    report = _report(
        (_at(Filename("c.py"), LineNumber(1), ColumnNumber(1)),),
        (_error(Filename("b.py"), LineNumber(1)),),
        Count(2),
    )

    rendered = _loud(RunOutcome(report=report))

    assert [line.root.split(":")[0] for line in rendered.stdout] == ["b.py", "c.py"]


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (RunOutcome(report=_nothing()), "no violations"),
        (RunOutcome(report=_one_violation()), "found 1 violation"),
        (
            RunOutcome(
                report=_report(
                    (
                        _at(Filename("a.py"), LineNumber(1), ColumnNumber(1)),
                        _at(Filename("a.py"), LineNumber(2), ColumnNumber(1)),
                    ),
                    (),
                    Count(1),
                )
            ),
            "found 2 violations",
        ),
        (
            RunOutcome(
                report=_report(
                    (),
                    (_error(Filename("a.py"), LineNumber(1)),),
                    Count(1),
                    _suppressed(SuppressionReason.BASELINE, Count(3)),
                )
            ),
            "no violations, 3 suppressed, 1 error",
        ),
        (
            RunOutcome(
                report=_report(
                    (), (), Count(1), _suppressed(SuppressionReason.COMMENT, Count(2))
                )
            ),
            "no violations, 2 suppressed",
        ),
        (
            RunOutcome(
                report=_report(
                    (), (), Count(1), _suppressed(SuppressionReason.PYTEST, Count(2))
                )
            ),
            "no violations",
        ),
    ],
)
def test_summarises_the_run_on_stderr(outcome: RunOutcome, expected: str) -> None:
    rendered = _loud(outcome)

    assert [line.root for line in rendered.stderr] == [
        f"Checked 1 file in 500ms - {expected}"
    ]


def test_counts_the_files_it_checked() -> None:
    rendered = _loud(RunOutcome(report=_report((), (), Count(3))))

    assert rendered.stderr[0].root.startswith("Checked 3 files in ")


def test_quiet_hides_the_notices_but_not_the_diagnostics() -> None:
    rendered = _rendered(
        RunOutcome(report=_one_violation(), stale=Count(1)),
        RenderOptions(quiet=Verdict(root=True)),
    )

    assert rendered.stderr == ()
    assert len(rendered.stdout) == 1


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "note: 1 baseline entry no longer matches"),
        (2, "note: 2 baseline entries no longer match"),
    ],
)
def test_notes_stale_baseline_entries_before_the_summary(
    count: int, expected: str
) -> None:
    rendered = _loud(RunOutcome(report=_nothing(), stale=Count(count)))

    assert rendered.stderr[0].root == (
        f"{expected}; rerun with --write-baseline to prune"
    )
    assert rendered.stderr[1].root.startswith("Checked ")


@pytest.mark.parametrize(
    ("written", "expected"), [(0, "0 violations"), (1, "1 violation")]
)
def test_a_written_baseline_reports_what_it_recorded(
    written: int, expected: str
) -> None:
    outcome = RunOutcome(report=_one_violation(), written=_wrote(Count(written)))

    rendered = _loud(outcome)

    assert rendered.stderr[0].root == (
        f"Checked 1 file in 500ms - wrote {expected} to .noprim.json"
    )


def test_a_written_baseline_records_violations_instead_of_printing_them() -> None:
    outcome = RunOutcome(
        report=_report(
            (_at(Filename("a.py"), LineNumber(1), ColumnNumber(1)),),
            (_error(Filename("b.py"), LineNumber(1)),),
            Count(2),
        ),
        written=_wrote(Count(1)),
    )

    rendered = _loud(outcome)

    assert [line.root.split(":")[0] for line in rendered.stdout] == ["b.py"]
    assert rendered.exit_code.root == 1


def _violation(
    filename: Filename, code: RuleCode, qualname: Qualname, annotation: AnnotationText
) -> Violation:
    return Violation(
        filename=filename,
        code=code,
        line=LineNumber(1),
        column=ColumnNumber(1),
        surface=Surface.PARAMETER,
        qualname=qualname,
        annotation=annotation,
    )


def _mixed() -> CheckReport:
    return _report(
        (
            _violation(
                Filename("a.py"),
                RuleCode("NOPRIM001"),
                Qualname("f.name"),
                AnnotationText("str"),
            ),
            _violation(
                Filename("a.py"),
                RuleCode("NOPRIM001"),
                Qualname("g.name"),
                AnnotationText("str"),
            ),
            _violation(
                Filename("b.py"),
                RuleCode("NOPRIM001"),
                Qualname("h.size"),
                AnnotationText("int"),
            ),
            _violation(
                Filename("b.py"),
                RuleCode("NOPRIM002"),
                Qualname("h"),
                AnnotationText("int"),
            ),
        ),
        (),
        Count(2),
    )


def _statistics(axes: GroupAxes) -> RenderOptions:
    return RenderOptions(statistics=Verdict(root=True), group_by=axes)


def test_statistics_counts_by_rule_descending() -> None:
    rendered = _rendered(
        RunOutcome(report=_mixed()), _statistics(GroupAxes((GroupAxis.RULE,)))
    )

    assert [line.root for line in rendered.stdout] == [
        "3  NOPRIM001",
        "1  NOPRIM002",
    ]


def test_statistics_splits_on_every_requested_axis() -> None:
    rendered = _rendered(
        RunOutcome(report=_mixed()),
        _statistics(GroupAxes((GroupAxis.RULE, GroupAxis.TYPE))),
    )

    assert [line.root for line in rendered.stdout] == [
        "2  NOPRIM001  str",
        "1  NOPRIM001  int",
        "1  NOPRIM002  int",
    ]


@pytest.mark.parametrize(
    ("axis", "expected"),
    [
        (GroupAxis.PATH, ["2  a.py", "2  b.py"]),
        (GroupAxis.NAME, ["2  name", "1  h", "1  size"]),
        (GroupAxis.TYPE, ["2  int", "2  str"]),
    ],
)
def test_statistics_groups_on_each_axis(axis: GroupAxis, expected: list[str]) -> None:
    rendered = _rendered(RunOutcome(report=_mixed()), _statistics(GroupAxes((axis,))))

    assert [line.root for line in rendered.stdout] == expected


def test_statistics_aligns_counts_to_the_widest() -> None:
    report = _report(
        (
            *(
                _violation(
                    Filename("a.py"),
                    RuleCode("NOPRIM001"),
                    Qualname(f"f{n}.a"),
                    AnnotationText("str"),
                )
                for n in range(10)
            ),
            _violation(
                Filename("a.py"),
                RuleCode("NOPRIM002"),
                Qualname("g"),
                AnnotationText("int"),
            ),
        ),
        (),
        Count(1),
    )

    rendered = _rendered(
        RunOutcome(report=report), _statistics(GroupAxes((GroupAxis.RULE,)))
    )

    assert [line.root for line in rendered.stdout] == [
        "10  NOPRIM001",
        " 1  NOPRIM002",
    ]


def test_statistics_keeps_reporting_what_would_not_parse() -> None:
    report = _report((), (_error(Filename("b.py"), LineNumber(3)),), Count(1))

    rendered = _rendered(
        RunOutcome(report=report), _statistics(GroupAxes((GroupAxis.RULE,)))
    )

    assert [line.root for line in rendered.stdout] == [
        "b.py:3:1: syntax error: invalid syntax"
    ]


def test_statistics_as_json_keeps_what_would_not_parse() -> None:
    report = _report((), (_error(Filename("b.py"), LineNumber(3)),), Count(1))

    document = _as_json(
        RunOutcome(report=report),
        RenderOptions(
            statistics=Verdict(root=True),
            group_by=GroupAxes((GroupAxis.RULE,)),
            output_format=OutputFormat.JSON,
        ),
    )

    assert document.root["errors"] == [
        {
            "path": "b.py",
            "line": 3,
            "column": 1,
            "message": "syntax error: invalid syntax",
        }
    ]


def test_statistics_of_a_clean_run_prints_nothing() -> None:
    rendered = _rendered(
        RunOutcome(report=_nothing()), _statistics(GroupAxes((GroupAxis.RULE,)))
    )

    assert rendered.stdout == ()


def test_statistics_as_json_names_each_axis() -> None:
    document = _as_json(
        RunOutcome(report=_mixed()),
        RenderOptions(
            statistics=Verdict(root=True),
            group_by=GroupAxes((GroupAxis.RULE, GroupAxis.PATH)),
            output_format=OutputFormat.JSON,
        ),
    )

    assert document.root == {
        "statistics": [
            {"count": 2, "rule": "NOPRIM001", "path": "a.py"},
            {"count": 1, "rule": "NOPRIM001", "path": "b.py"},
            {"count": 1, "rule": "NOPRIM002", "path": "b.py"},
        ],
        "errors": [],
    }


def test_statistics_leaves_the_exit_code_alone() -> None:
    assert (
        _rendered(
            RunOutcome(report=_one_violation()),
            _statistics(GroupAxes((GroupAxis.RULE,))),
        ).exit_code.root
        == 1
    )


def _json_options() -> RenderOptions:
    return RenderOptions(output_format=OutputFormat.JSON)


def test_json_describes_every_violation() -> None:
    violation = Violation(
        filename=Filename("a.py"),
        code=RuleCode("NOPRIM001"),
        line=LineNumber(2),
        column=ColumnNumber(7),
        surface=Surface.PARAMETER,
        qualname=Qualname("greet.user_id"),
        annotation=AnnotationText("str"),
    )

    document = _as_json(
        RunOutcome(report=_report((violation,), (), Count(1))), _json_options()
    )

    assert document.root["violations"] == [
        {
            "path": "a.py",
            "line": 2,
            "column": 7,
            "code": "NOPRIM001",
            "surface": "parameter",
            "name": "user_id",
            "qualname": "greet.user_id",
            "annotation": "str",
        }
    ]


def test_json_is_parseable_with_nothing_to_report() -> None:
    document = _as_json(RunOutcome(report=_nothing()), _json_options())

    assert document.root == {"violations": [], "errors": []}


def test_json_keeps_file_errors_out_of_the_violations() -> None:
    report = _report((), (_error(Filename("b.py"), LineNumber(3)),), Count(1))

    document = _as_json(RunOutcome(report=report), _json_options())

    assert document.root["errors"] == [
        {
            "path": "b.py",
            "line": 3,
            "column": 1,
            "message": "syntax error: invalid syntax",
        }
    ]


def test_json_still_summarises_on_stderr() -> None:
    rendered = _rendered(RunOutcome(report=_one_violation()), _json_options())

    assert rendered.stderr[0].root.endswith("found 1 violation")


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (RunOutcome(report=_nothing()), 0),
        (RunOutcome(report=_one_violation()), 1),
        (
            RunOutcome(
                report=_report((), (_error(Filename("a.py"), LineNumber(1)),), Count(1))
            ),
            1,
        ),
        (RunOutcome(report=_one_violation(), written=_wrote(Count(1))), 0),
    ],
)
def test_exit_code_follows_the_diagnostics(outcome: RunOutcome, expected: int) -> None:
    assert _loud(outcome).exit_code.root == expected
