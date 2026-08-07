from pathlib import Path

from typer.testing import CliRunner

from noprim_cli.main import app

runner = CliRunner()


def test_exits_nonzero_on_violation(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def greet(name: str) -> None: ...\n")

    result = runner.invoke(app, ["check", str(target)])

    assert result.exit_code == 1
    assert "takes a primitive" in result.stdout


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
