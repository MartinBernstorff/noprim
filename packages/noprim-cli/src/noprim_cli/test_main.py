import logging
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from noprim_cli.main import app

runner = CliRunner()


def _plain(output: str) -> str:
    # Rich colours and wraps errors, splitting "--allow" across escapes and lines.
    stripped = re.sub(r"\x1b\[[0-9;]*m", "", output).replace("│", " ")
    return " ".join(stripped.split())


def test_exits_nonzero_on_violation(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def greet(name: str) -> None: ...\n")

    result = runner.invoke(app, ["check", str(target)])

    assert result.exit_code == 1
    assert "greet.name takes a primitive 'str'" in result.stdout


def test_reports_return_and_attribute_surfaces(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("class Thing:\n    n: int\ndef f() -> bool: ...\n")

    result = runner.invoke(app, ["check", str(target)])

    assert result.exit_code == 1
    assert "Thing.n holds a primitive 'int'" in result.stdout
    assert "f returns a primitive 'bool'" in result.stdout


def test_exits_zero_when_clean(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def greet(name: Name) -> None: ...\n")

    result = runner.invoke(app, ["check", str(target)])

    assert result.exit_code == 0


def test_allow_removes_type_from_deny_list(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(x: Any) -> str: ...\n")

    result = runner.invoke(app, ["check", "--allow", "Any", str(target)])

    assert "Any" not in result.stdout
    assert "f returns a primitive 'str'" in result.stdout


def test_deny_adds_type_to_deny_list(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(amount: Money) -> None: ...\n")

    result = runner.invoke(app, ["check", "--deny", "Money", str(target)])

    assert result.exit_code == 1
    assert "f.amount takes a primitive 'Money'" in result.stdout


def test_name_in_both_flags_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def f() -> None: ...\n")

    result = runner.invoke(
        app, ["check", "--allow", "int", "--deny", "int", str(target)]
    )

    assert result.exit_code == 2
    assert "passed to both --allow and --deny: int" in _plain(result.output)


def test_allow_of_unknown_name_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def f() -> None: ...\n")

    result = runner.invoke(app, ["check", "--allow", "itn", str(target)])

    assert result.exit_code == 2
    assert "--allow of a name that is not on the deny-list: itn" in _plain(
        result.output
    )


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
    assert "f.a" not in result.stdout
    assert "f.b" not in result.stdout
    assert "f.c takes a primitive 'Money'" in result.stdout
    assert "f.d takes a primitive 'Weight'" in result.stdout


def test_empty_name_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def f() -> None: ...\n")

    result = runner.invoke(app, ["check", "--deny", "", str(target)])

    assert result.exit_code == 2
    assert "got an empty one" in _plain(result.output)


def test_invalid_flags_fail_before_walking_paths(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _ = (tmp_path / "good.py").write_text("def f() -> None: ...\n")

    with caplog.at_level(logging.INFO, logger="noprim"):
        result = runner.invoke(app, ["check", "--allow", "itn", str(tmp_path)])

    assert result.exit_code == 2
    assert "Checked" not in caplog.text


def test_quiet_suppresses_progress_logging(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def greet(name: Name) -> None: ...\n")

    result = runner.invoke(app, ["check", "--quiet", str(target)])

    assert result.exit_code == 0
    assert "Checked" not in result.stdout


def test_exits_zero_when_only_violation_is_ignored(tmp_path: Path) -> None:
    target = tmp_path / "ignored.py"
    _ = target.write_text("def greet(name: str) -> None: ...  # noprim: ignore\n")

    result = runner.invoke(app, ["check", str(target)])

    assert result.exit_code == 0
    assert "greet.name" not in result.stdout


def test_defaults_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = (tmp_path / "bad.py").write_text("def greet(name: str) -> None: ...\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check"])

    assert result.exit_code == 1
    assert "takes a primitive" in result.stdout


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
    assert "binary.py" in result.stdout
