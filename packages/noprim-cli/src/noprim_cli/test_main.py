from pathlib import Path

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
    assert "Checking" not in result.stdout


def test_exits_zero_when_only_violation_is_ignored(tmp_path: Path) -> None:
    target = tmp_path / "ignored.py"
    _ = target.write_text("def greet(name: str) -> None: ...  # noprim: ignore\n")

    result = runner.invoke(app, ["check", str(target)])

    assert result.exit_code == 0
    assert "greet.name" not in result.stdout
