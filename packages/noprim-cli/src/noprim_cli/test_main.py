from pathlib import Path

import pytest
from typer.testing import CliRunner

from noprim_cli.main import Duration, app, pretty_duration

runner = CliRunner()


def test_reports_each_surface_ruff_style(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text(
        "def greet(user_id: str) -> bool: ...\nclass Thing:\n    email: str\n"
    )

    result = runner.invoke(app, ["check", str(target)])

    assert result.stdout.splitlines() == [
        f'{target}:1:20: parameter "user_id" is annotated "str"',
        f'{target}:1:28: return type is annotated "bool"',
        f'{target}:3:12: attribute "email" is annotated "str"',
    ]


def test_sorts_diagnostics_by_path_line_and_column(tmp_path: Path) -> None:
    _ = (tmp_path / "b.py").write_text("def g(b: int) -> None: ...\n")
    _ = (tmp_path / "a.py").write_text("def f(a: int, aa: int) -> None: ...\n")

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.stdout.splitlines() == [
        f'{tmp_path / "a.py"}:1:10: parameter "a" is annotated "int"',
        f'{tmp_path / "a.py"}:1:19: parameter "aa" is annotated "int"',
        f'{tmp_path / "b.py"}:1:10: parameter "b" is annotated "int"',
    ]


def test_interleaves_file_errors_with_violations(tmp_path: Path) -> None:
    _ = (tmp_path / "a.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "b.py").write_text("def g(b: int -> None:\n")

    result = runner.invoke(app, ["check", str(tmp_path)])

    lines = result.stdout.splitlines()
    assert lines[0].startswith(f"{tmp_path / 'a.py'}:1:10: parameter")
    assert lines[1].startswith(f"{tmp_path / 'b.py'}:1:")
    assert "syntax error: " in lines[1]


def test_summarises_a_run_with_violations_on_stderr(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def f(a: int, b: int) -> None: ...\n")

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.stderr.startswith("Checked 1 file in ")
    assert result.stderr.rstrip().endswith(" - found 2 violations")


def test_summarises_a_clean_run_on_stderr(tmp_path: Path) -> None:
    _ = (tmp_path / "good.py").write_text("def f(a: Name) -> None: ...\n")

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.stderr.startswith("Checked 1 file in ")
    assert result.stderr.rstrip().endswith(" - no violations")


def test_quiet_hides_the_summary_but_not_the_violations(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(a: int) -> None: ...\n")

    result = runner.invoke(app, ["check", "--quiet", str(target)])

    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f'{target}:1:10: parameter "a" is annotated "int"'
    ]


def test_exits_zero_when_clean(tmp_path: Path) -> None:
    _ = (tmp_path / "good.py").write_text("def greet(name: Name) -> None: ...\n")

    assert runner.invoke(app, ["check", str(tmp_path)]).exit_code == 0


def test_exits_one_when_violations_are_found(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def greet(name: str) -> None: ...\n")

    assert runner.invoke(app, ["check", str(tmp_path)]).exit_code == 1


def test_exits_two_when_a_path_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"

    result = runner.invoke(app, ["check", str(missing)])

    assert result.exit_code == 2
    assert str(missing) in result.stderr
    assert result.stdout == ""


def test_exits_zero_when_only_violation_is_ignored(tmp_path: Path) -> None:
    target = tmp_path / "ignored.py"
    _ = target.write_text("def greet(name: str) -> None: ...  # noprim: ignore\n")

    result = runner.invoke(app, ["check", str(target)])

    assert result.exit_code == 0
    assert result.stdout == ""


def test_defaults_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = (tmp_path / "bad.py").write_text("def greet(name: str) -> None: ...\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check"])

    assert result.exit_code == 1
    assert 'parameter "name" is annotated "str"' in result.stdout


def test_repeated_exclude_globs_drop_files(tmp_path: Path) -> None:
    _ = (tmp_path / "a.py").write_text("def f(a: str) -> None: ...\n")
    _ = (tmp_path / "b.py").write_text("def g(b: str) -> None: ...\n")

    result = runner.invoke(
        app, ["check", str(tmp_path), "--exclude", "a.py", "--exclude", "b.py"]
    )

    assert result.exit_code == 0


def test_undecodable_file_exits_nonzero_with_an_error(tmp_path: Path) -> None:
    _ = (tmp_path / "binary.py").write_bytes(b"\xfe\xff\x00")

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 1
    assert "decode error: " in result.stdout


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
    assert pretty_duration(Duration(seconds)) == expected
