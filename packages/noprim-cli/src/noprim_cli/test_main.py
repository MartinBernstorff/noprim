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
    assert "int" in result.output
    assert "both --allow and --deny" in result.output


def test_allow_of_unknown_name_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def f() -> None: ...\n")

    result = runner.invoke(app, ["check", "--allow", "itn", str(target)])

    assert result.exit_code == 2
    assert "not on the deny-list" in result.output
    assert "itn" in result.output


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


def test_quiet_suppresses_progress_logging(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def greet(name: Name) -> None: ...\n")

    result = runner.invoke(app, ["check", "--quiet", str(target)])

    assert result.exit_code == 0
    assert "Checking" not in result.stdout
