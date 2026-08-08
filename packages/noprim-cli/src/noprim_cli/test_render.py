from pathlib import Path

import pytest

from noprim_cli.render import (
    Count,
    Duration,
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
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation
from noprim_io.baseline import BaselinePath
from noprim_io.check import CheckReport, ErrorMessage, FileError
from noprim_io.paths import SourceFile


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
) -> CheckReport:
    return CheckReport(
        violations=violations,
        errors=errors,
        checked=tuple(SourceFile(Path(f"f{n}.py")) for n in range(checked.root)),
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
                    (), (_error(Filename("a.py"), LineNumber(1)),), Count(1)
                ),
                suppressed=Count(3),
            ),
            "no violations, 3 suppressed by baseline, 1 error",
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
