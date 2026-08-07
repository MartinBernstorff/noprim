from pathlib import Path

import pytest
from typer.testing import CliRunner

from noprim_cli.main import app

runner = CliRunner()


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
