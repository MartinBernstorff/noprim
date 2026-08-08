import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from noprim_cli.main import DisplayText, Duration, app, pretty_duration

runner = CliRunner()


def _plain(output: DisplayText) -> DisplayText:
    # Rich colours and wraps errors, splitting "--allow" across escapes and lines.
    stripped = re.sub(r"\x1b\[[0-9;]*m", "", output.root).replace("│", " ")
    return DisplayText(" ".join(stripped.split()))


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


def test_summary_counts_unreadable_files_apart_from_violations(tmp_path: Path) -> None:
    _ = (tmp_path / "broken.py").write_text("def f(a: int -> None:\n")
    _ = (tmp_path / "bad.py").write_text("def g(b: int) -> None: ...\n")

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.stderr.rstrip().endswith(" - found 1 violation, 1 error")


def test_allow_removes_type_from_deny_list(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(x: Any) -> str: ...\n")

    result = runner.invoke(app, ["check", "--allow", "Any", str(target)])

    assert result.stdout.splitlines() == [
        f'{target}:1:18: return type is annotated "str"'
    ]


def test_deny_adds_type_to_deny_list(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(amount: Money) -> None: ...\n")

    result = runner.invoke(app, ["check", "--deny", "Money", str(target)])

    assert result.exit_code == 1
    assert 'parameter "amount" is annotated "Money"' in result.stdout


def test_flags_are_repeatable(tmp_path: Path) -> None:
    target = tmp_path / "mixed.py"
    _ = target.write_text("def f(a: int, b: str, c: Money, d: Weight) -> None: ...\n")

    result = runner.invoke(
        app,
        [
            "check",
            "--allow",
            "int",
            "--allow",
            "str",
            "--deny",
            "Money",
            "--deny",
            "Weight",
            str(target),
        ],
    )

    assert result.exit_code == 1
    assert 'parameter "a"' not in result.stdout
    assert 'parameter "b"' not in result.stdout
    assert 'parameter "c" is annotated "Money"' in result.stdout
    assert 'parameter "d" is annotated "Weight"' in result.stdout


def test_name_in_both_flags_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def f() -> None: ...\n")

    result = runner.invoke(
        app, ["check", "--allow", "int", "--deny", "int", str(target)]
    )

    assert result.exit_code == 2
    assert (
        "passed to both --allow and --deny: int"
        in _plain(DisplayText(result.output)).root
    )


def test_allow_of_unknown_name_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def f() -> None: ...\n")

    result = runner.invoke(app, ["check", "--allow", "itn", str(target)])

    assert result.exit_code == 2
    assert (
        "--allow of a name that is not on the deny-list: itn"
        in _plain(DisplayText(result.output)).root
    )


def test_empty_name_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def f() -> None: ...\n")

    result = runner.invoke(app, ["check", "--deny", "", str(target)])

    assert result.exit_code == 2
    assert "got an empty one" in _plain(DisplayText(result.output)).root


def test_invalid_flags_fail_before_walking_paths(tmp_path: Path) -> None:
    _ = (tmp_path / "good.py").write_text("def f() -> None: ...\n")

    result = runner.invoke(app, ["check", "--allow", "itn", str(tmp_path)])

    assert result.exit_code == 2
    assert "Checked" not in result.stderr


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


def test_a_directory_vanishing_mid_walk_exits_two(tmp_path: Path) -> None:
    doomed = tmp_path / "doomed"
    doomed.mkdir()
    real_is_dir = Path.is_dir

    # Stands in for Path.is_dir, so it is bound to that signature.
    def vanish(self: Path) -> bool:  # noprim: ignore
        verdict = real_is_dir(self)
        if self == doomed and doomed.exists():
            doomed.rmdir()
        return verdict

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "is_dir", vanish)
        result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 2
    assert "doomed" in _plain(DisplayText(result.output)).root
