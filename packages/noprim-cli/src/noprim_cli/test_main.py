import inspect
import json
import re
from pathlib import Path

import pytest
from pydantic import RootModel
from typer.testing import CliRunner

from noprim_cli.main import app, check
from noprim_cli.render import DisplayText
from noprim_core.baseline import Baseline
from noprim_core.settings import Settings
from noprim_io.baseline import BaselinePath, read_baseline
from noprim_io.paths import ExistingDirectory

runner = CliRunner()


def _plain(output: DisplayText) -> DisplayText:
    # Rich colours and wraps errors, splitting "--allow" across escapes and lines.
    stripped = re.sub(r"\x1b\[[0-9;]*m", "", output.root).replace("│", " ")
    return DisplayText(" ".join(stripped.split()))


def test_reports_each_surface_ruff_style(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text(
        "def greet(user_id: str) -> int: ...\nclass Thing:\n    email: str\n"
    )

    result = runner.invoke(app, ["check", str(target)])

    assert result.stdout.splitlines() == [
        f'{target}:1:20: NOPRIM001 parameter "user_id" is annotated "str"',
        f'{target}:1:28: NOPRIM002 return type is annotated "int"',
        f'{target}:3:12: NOPRIM003 attribute "email" is annotated "str"',
    ]


def test_quiet_hides_the_summary_but_not_the_violations(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(a: int) -> None: ...\n")

    result = runner.invoke(app, ["check", "--quiet", str(target)])

    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f'{target}:1:10: NOPRIM001 parameter "a" is annotated "int"'
    ]


def test_the_summary_counts_suppressions_a_baseline_had_no_part_in(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / "bad.py").write_text(
        "def f(a: int) -> None: ...  # noprim: ignore\n"
    )

    result = runner.invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "no violations, 1 suppressed" in result.stderr


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


def test_a_rule_flag_replaces_its_key_without_dropping_per_path_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = (tmp_path / "noprim.toml").write_text(
        'ignore = ["NOPRIM001"]\n\n'
        '[[per-path]]\npaths = ["legacy/**"]\nignore = ["NOPRIM002"]\n'
    )
    (tmp_path / "legacy").mkdir()
    _ = (tmp_path / "legacy" / "a.py").write_text("def f() -> str: ...\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "--ignore", "NOPRIM007"])

    assert result.exit_code == 0


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


def test_allow_removes_type_from_deny_list(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(x: int) -> str: ...\n")

    result = runner.invoke(app, ["check", "--allow", "int", str(target)])

    assert result.stdout.splitlines() == [
        f'{target}:1:18: NOPRIM002 return type is annotated "str"'
    ]


@pytest.mark.parametrize("annotation", ["Any", "object"])
@pytest.mark.parametrize(
    ("flags", "expected"), [([], 0), (["--select", "NOPRIM004"], 1)]
)
def test_top_types_are_reported_only_when_opted_into(
    tmp_path: Path, annotation: str, flags: list[str], expected: int
) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text(f"def f(x: {annotation}) -> None: ...\n")

    result = runner.invoke(app, ["check", *flags, str(target)])

    assert result.exit_code == expected
    assert (f'parameter "x" is annotated "{annotation}"' in result.stdout) == (
        expected == 1
    )


@pytest.mark.parametrize("flags", [[], ["--select", "NOPRIM004"]])
def test_allow_of_a_top_type_exits_two(tmp_path: Path, flags: list[str]) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(x: Any) -> None: ...\n")

    result = runner.invoke(app, ["check", *flags, "--allow", "Any", str(target)])

    assert result.exit_code == 2
    assert (
        "allow of a type governed by the top-type rules: Any"
        in _plain(DisplayText(result.output)).root
    )


def test_deny_of_a_top_type_reports_it_without_the_flag(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(x: Any, y: object) -> None: ...\n")

    result = runner.invoke(app, ["check", "--deny", "Any", str(target)])

    assert result.exit_code == 1
    assert 'parameter "x" is annotated "Any"' in result.stdout
    assert 'parameter "y"' not in result.stdout


def test_predicates_are_skipped_until_asked_for(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def is_ready(x: Name) -> bool: ...\n")

    skipped = runner.invoke(app, ["check", str(target)])
    checked = runner.invoke(app, ["check", "--select", "NOPRIM007", str(target)])

    assert skipped.stdout.splitlines() == []
    assert checked.stdout.splitlines() == [
        f'{target}:1:26: NOPRIM007 return type is annotated "bool"'
    ]


def test_ignore_drops_a_rule_from_the_run(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(x: int) -> str: ...\n")

    result = runner.invoke(app, ["check", "--ignore", "NOPRIM002", str(target)])

    assert result.stdout.splitlines() == [
        f'{target}:1:10: NOPRIM001 parameter "x" is annotated "int"'
    ]


def test_a_selector_prefix_turns_on_every_rule(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def is_ready(x: Any) -> bool: ...\n")

    result = runner.invoke(app, ["check", "--select", "NOPRIM", str(target)])

    assert result.stdout.splitlines() == [
        f'{target}:1:17: NOPRIM004 parameter "x" is annotated "Any"',
        f'{target}:1:25: NOPRIM007 return type is annotated "bool"',
    ]


def test_the_all_preset_turns_on_every_rule(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def is_ready(x: Any) -> bool: ...\n")

    result = runner.invoke(app, ["check", "--preset", "all", str(target)])

    assert result.stdout.splitlines() == [
        f'{target}:1:17: NOPRIM004 parameter "x" is annotated "Any"',
        f'{target}:1:25: NOPRIM007 return type is annotated "bool"',
    ]


def test_ignore_subtracts_from_the_all_preset(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def is_ready(x: Any) -> bool: ...\n")

    result = runner.invoke(
        app, ["check", "--preset", "all", "--ignore", "NOPRIM007", str(target)]
    )

    assert result.stdout.splitlines() == [
        f'{target}:1:17: NOPRIM004 parameter "x" is annotated "Any"'
    ]


def test_extend_select_adds_a_rule_to_the_defaults(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(x: Any, y: int) -> None: ...\n")

    result = runner.invoke(app, ["check", "--extend-select", "NOPRIM004", str(target)])

    assert result.stdout.splitlines() == [
        f'{target}:1:10: NOPRIM004 parameter "x" is annotated "Any"',
        f'{target}:1:18: NOPRIM001 parameter "y" is annotated "int"',
    ]


@pytest.mark.parametrize("flag", ["--select", "--extend-select", "--ignore"])
def test_a_selector_matching_no_rule_exits_two(tmp_path: Path, flag: str) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def f() -> None: ...\n")

    result = runner.invoke(app, ["check", flag, "NOPRIM999", str(target)])

    assert result.exit_code == 2
    assert "no rule matches: NOPRIM999" in _plain(DisplayText(result.output)).root


def test_ignore_names_skips_symbols_by_name(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(size: int, **kwargs: str) -> None: ...\n")

    result = runner.invoke(app, ["check", "--ignore-names", "kwargs", str(target)])

    assert result.stdout.splitlines() == [
        f'{target}:1:13: NOPRIM001 parameter "size" is annotated "int"'
    ]


@pytest.mark.parametrize(
    ("flag", "remaining"),
    [
        (
            "--ignore-param-names",
            '2:12: NOPRIM003 attribute "value" is annotated "int"',
        ),
        (
            "--ignore-attribute-names",
            '4:14: NOPRIM001 parameter "value" is annotated "str"',
        ),
    ],
)
def test_a_name_flag_skips_only_its_own_surface(
    tmp_path: Path, flag: str, remaining: str
) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text(
        "class Thing:\n    value: int\n\ndef f(value: str) -> None: ...\n"
    )

    result = runner.invoke(app, ["check", flag, "value", str(target)])

    assert result.stdout.splitlines() == [f"{target}:{remaining}"]


def test_ignore_inner_classes_skips_a_nested_body_but_not_a_top_level_one(
    tmp_path: Path,
) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text(
        "class Meta:\n    fields: list[str] = []\n\n"
        "class Filter:\n    class Meta:\n        fields: list[str] = []\n"
    )

    result = runner.invoke(
        app, ["check", "--ignore-inner-classes", "Meta", str(target)]
    )

    assert result.stdout.splitlines() == [
        f'{target}:2:13: NOPRIM003 attribute "fields" is annotated "list[str]"'
    ]
    assert "found 1 violation, 1 suppressed" in result.stderr


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
    assert "both allowed and denied: int" in _plain(DisplayText(result.output)).root


def test_allow_of_unknown_name_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    _ = target.write_text("def f() -> None: ...\n")

    result = runner.invoke(app, ["check", "--allow", "itn", str(target)])

    assert result.exit_code == 2
    assert (
        "allow of a name that is not on the deny-list: itn"
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


def test_writes_a_baseline_when_the_file_is_absent(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"

    result = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    assert result.exit_code == 0
    assert result.stdout == ""
    assert "wrote 1 violation to" in result.stderr
    assert baseline.is_file()


def test_reports_only_violations_the_baseline_does_not_cover(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _ = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    _ = target.write_text("def f(a: int) -> None: ...\ndef g(b: str) -> None: ...\n")
    result = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    assert result.exit_code == 1
    assert result.stdout.splitlines() == [
        f'{target}:2:10: NOPRIM001 parameter "b" is annotated "str"'
    ]
    assert "found 1 violation, 1 suppressed" in result.stderr


def test_keeps_suppressing_after_the_violation_moves(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _ = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    _ = target.write_text("# a new line\n\ndef f(a: int) -> None: ...\n")
    result = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    assert result.exit_code == 0
    assert result.stdout == ""


def test_a_check_run_never_rewrites_the_baseline(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _ = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])
    before = baseline.read_text()

    _ = target.write_text("def f() -> None: ...\n")
    result = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    assert baseline.read_text() == before
    assert "1 baseline entry no longer matches" in result.stderr
    assert "--write-baseline" in result.stderr


def test_write_baseline_prunes_entries_that_no_longer_match(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _ = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    _ = target.write_text("def f() -> None: ...\n")
    result = runner.invoke(
        app,
        ["check", "--baseline", str(baseline), "--write-baseline", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "wrote 0 violations to" in result.stderr
    assert read_baseline(BaselinePath(baseline)) == Baseline.empty()


def test_write_baseline_keeps_entries_for_files_it_did_not_walk(
    tmp_path: Path,
) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _ = (tmp_path / "a" / "one.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "b" / "two.py").write_text("def g(b: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _ = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    _ = runner.invoke(
        app,
        ["check", "--baseline", str(baseline), "--write-baseline", str(tmp_path / "a")],
    )

    recorded = read_baseline(BaselinePath(baseline))
    assert sorted(key.filename.root for key in recorded.root) == [
        "a/one.py",
        "b/two.py",
    ]


def test_keeps_entries_for_a_file_that_stopped_parsing(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _ = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    _ = target.write_text("def f(a: int -> None:\n")
    result = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])
    _ = runner.invoke(
        app,
        ["check", "--baseline", str(baseline), "--write-baseline", str(tmp_path)],
    )

    assert "no longer match" not in result.stderr
    recorded = read_baseline(BaselinePath(baseline))
    assert {key.filename.root for key in recorded.root} == {"bad.py"}


def test_write_baseline_drops_entries_for_deleted_files(tmp_path: Path) -> None:
    _ = (tmp_path / "gone.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "kept.py").write_text("def g(b: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _ = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    (tmp_path / "gone.py").unlink()
    _ = runner.invoke(
        app,
        ["check", "--baseline", str(baseline), "--write-baseline", str(tmp_path)],
    )

    recorded = read_baseline(BaselinePath(baseline))
    assert {key.filename.root for key in recorded.root} == {"kept.py"}


def test_write_baseline_without_a_path_is_rejected(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def f(a: int) -> None: ...\n")

    result = runner.invoke(app, ["check", "--write-baseline", str(tmp_path)])

    assert result.exit_code == 2
    assert (
        "--write-baseline needs --baseline" in _plain(DisplayText(result.output)).root
    )


def _outdated_baseline(path: BaselinePath) -> None:
    _ = path.root.write_text(json.dumps({"version": 1, "files": {}}))


def test_a_baseline_from_an_older_noprim_stops_the_run(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _outdated_baseline(BaselinePath(baseline))

    result = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    assert result.exit_code == 2
    assert "--write-baseline" in result.stderr


def test_write_baseline_replaces_one_from_an_older_noprim(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _outdated_baseline(BaselinePath(baseline))

    result = runner.invoke(
        app,
        ["check", "--baseline", str(baseline), "--write-baseline", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert len(read_baseline(BaselinePath(baseline)).root) == 1


def test_a_malformed_baseline_stops_the_run(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / ".noprim.json"
    _ = baseline.write_text("{oops")

    result = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    assert result.exit_code == 2
    assert "not a valid noprim baseline" in result.stderr


def test_an_unwritable_baseline_path_exits_two(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def f(a: int) -> None: ...\n")
    baseline = tmp_path / "absent" / ".noprim.json"

    result = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    assert result.exit_code == 2
    assert "error: " in result.stderr


def test_syntax_errors_are_not_suppressed_by_a_baseline(tmp_path: Path) -> None:
    _ = (tmp_path / "broken.py").write_text("def f(a: int -> None:\n")
    baseline = tmp_path / ".noprim.json"

    result = runner.invoke(app, ["check", "--baseline", str(baseline), str(tmp_path)])

    assert result.exit_code == 1
    assert "syntax error: " in result.stdout


class ConfigText(RootModel[str]):
    pass


def _project(root: ExistingDirectory, config: ConfigText) -> None:
    (root.root / ".git").mkdir()
    _ = (root.root / "noprim.toml").write_text(config.root)
    _ = (root.root / "a.py").write_text("def f(x: str) -> None: ...\n")


def test_a_config_file_in_the_project_is_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(ExistingDirectory(tmp_path), ConfigText('allow = ["str"]\n'))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "a.py"])

    assert result.exit_code == 0


def test_a_flag_replaces_the_same_key_from_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(ExistingDirectory(tmp_path), ConfigText('allow = ["str"]\n'))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "--allow", "int", "a.py"])

    assert result.exit_code == 1
    assert 'parameter "x" is annotated "str"' in result.stdout


def test_the_preset_flag_replaces_the_one_from_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(ExistingDirectory(tmp_path), ConfigText('preset = "all"\n'))
    _ = (tmp_path / "a.py").write_text("def is_ready(x: Name) -> bool: ...\n")
    monkeypatch.chdir(tmp_path)

    under_config = runner.invoke(app, ["check", "a.py"])
    overridden = runner.invoke(app, ["check", "--preset", "default", "a.py"])

    assert "NOPRIM007" in under_config.stdout
    assert overridden.stdout.splitlines() == []


def test_a_per_path_override_from_the_config_is_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(
        ExistingDirectory(tmp_path),
        ConfigText('[[per-path]]\npaths = ["a.py"]\nallow = ["str"]\n'),
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "a.py"])

    assert result.exit_code == 0


def test_a_per_path_glob_of_ignored_parameter_names_is_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(
        ExistingDirectory(tmp_path),
        ConfigText(
            '[[per-path]]\npaths = ["django_app/**"]\nignore-param-names = ["*_contains"]\n'
        ),
    )
    (tmp_path / "django_app").mkdir()
    _ = (tmp_path / "django_app" / "filters.py").write_text(
        "class F:\n    name_contains: str\n\ndef f(name_contains: str) -> None: ...\n"
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "django_app"])

    assert result.stdout.splitlines() == [
        (
            'django_app/filters.py:2:20: NOPRIM003 attribute "name_contains"'
            ' is annotated "str"'
        )
    ]
    assert "found 1 violation, 1 suppressed" in result.stderr


def test_an_unreadable_config_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(ExistingDirectory(tmp_path), ConfigText("deny = [\n"))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "a.py"])

    assert result.exit_code == 2
    assert "Checked" not in result.stderr


def test_an_unknown_config_key_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(ExistingDirectory(tmp_path), ConfigText('denied = ["str"]\n'))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "a.py"])

    assert result.exit_code == 2
    assert "denied" in _plain(DisplayText(result.output)).root


def test_output_format_json_reaches_the_renderer(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def greet(user_id: str) -> None: ...\n")

    result = runner.invoke(
        app, ["check", "--output-format", "json", "--quiet", str(tmp_path)]
    )

    assert json.loads(result.stdout)["violations"][0]["name"] == "user_id"


def test_json_output_parses_when_there_is_nothing_to_report(tmp_path: Path) -> None:
    _ = (tmp_path / "good.py").write_text("def f(a: Name) -> None: ...\n")

    result = runner.invoke(
        app, ["check", "--output-format", "json", "--quiet", str(tmp_path)]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"violations": [], "errors": []}


def test_statistics_counts_instead_of_listing(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text(
        "def f(a: int, b: int) -> str: ...\ndef g(c: str) -> None: ...\n"
    )

    result = runner.invoke(app, ["check", "--statistics", "--quiet", str(tmp_path)])

    assert len(result.stdout.splitlines()) == 2
    assert str(tmp_path) not in result.stdout


def test_group_by_takes_a_comma_separated_list(tmp_path: Path) -> None:
    _ = (tmp_path / "bad.py").write_text("def f(a: int, b: str) -> None: ...\n")

    result = runner.invoke(
        app,
        ["check", "--statistics", "--group-by", "rule,type", "--quiet", str(tmp_path)],
    )

    assert result.stdout.splitlines() == ["1  NOPRIM001  int", "1  NOPRIM001  str"]


def test_an_unknown_group_by_axis_exits_two(tmp_path: Path) -> None:
    _ = (tmp_path / "good.py").write_text("def f() -> None: ...\n")

    result = runner.invoke(
        app, ["check", "--statistics", "--group-by", "module", str(tmp_path)]
    )

    assert result.exit_code == 2
    assert (
        "--group-by got an unknown axis: module; expected one of rule, type, name, path"
        in _plain(DisplayText(result.output)).root
    )


@pytest.mark.parametrize("axes", ["", ",", " "])
def test_a_group_by_naming_no_axis_exits_two(tmp_path: Path, axes: str) -> None:
    _ = (tmp_path / "good.py").write_text("def f() -> None: ...\n")

    result = runner.invoke(
        app, ["check", "--statistics", "--group-by", axes, str(tmp_path)]
    )

    assert result.exit_code == 2
    assert (
        "--group-by needs at least one axis" in _plain(DisplayText(result.output)).root
    )


def test_a_repeated_group_by_axis_exits_two(tmp_path: Path) -> None:
    _ = (tmp_path / "good.py").write_text("def f() -> None: ...\n")

    result = runner.invoke(
        app, ["check", "--statistics", "--group-by", "rule,rule", str(tmp_path)]
    )

    assert result.exit_code == 2
    assert (
        "--group-by got the same axis twice: rule"
        in _plain(DisplayText(result.output)).root
    )


def test_statistics_still_reports_a_file_it_could_not_parse(tmp_path: Path) -> None:
    _ = (tmp_path / "broken.py").write_text("def f(a: int -> None:\n")

    result = runner.invoke(app, ["check", "--statistics", "--quiet", str(tmp_path)])

    assert result.exit_code == 1
    assert "syntax error: " in result.stdout


def test_group_by_without_statistics_is_rejected(tmp_path: Path) -> None:
    _ = (tmp_path / "good.py").write_text("def f() -> None: ...\n")

    result = runner.invoke(app, ["check", "--group-by", "rule", str(tmp_path)])

    assert result.exit_code == 2
    assert "--group-by needs --statistics" in _plain(DisplayText(result.output)).root


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--statistics"],
        ["--output-format", "json"],
        ["--statistics", "--output-format", "json"],
    ],
)
def test_reporting_flags_leave_the_exit_code_alone(
    tmp_path: Path, flags: list[str]
) -> None:
    _ = (tmp_path / "bad.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "clean").mkdir()
    _ = (tmp_path / "clean" / "good.py").write_text("def g() -> None: ...\n")

    dirty = runner.invoke(app, ["check", *flags, str(tmp_path / "bad.py")])
    clean = runner.invoke(app, ["check", *flags, str(tmp_path / "clean")])

    assert dirty.exit_code == 1
    assert clean.exit_code == 0


def test_every_flag_that_is_not_run_mode_names_a_config_key() -> None:
    # The name is the wiring: a flag matching no key is silently dropped rather
    # than rejected. Run-mode flags steer one invocation and are meant to miss.
    run_mode = {
        "paths",
        "quiet",
        "baseline",
        "refresh",
        "statistics",
        "group_by",
        "output_format",
    }
    flags = set(inspect.signature(check).parameters) - run_mode
    assert flags <= set(Settings.model_fields)


def test_a_rule_key_can_come_from_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    _ = (tmp_path / "noprim.toml").write_text('select = ["NOPRIM004"]\n')
    _ = (tmp_path / "a.py").write_text("def f(x: Any) -> None: ...\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "a.py"])

    assert result.stdout.splitlines() == [
        'a.py:1:10: NOPRIM004 parameter "x" is annotated "Any"'
    ]


def test_a_config_key_survives_when_a_different_flag_is_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    _ = (tmp_path / "noprim.toml").write_text('select = ["NOPRIM007"]\n')
    _ = (tmp_path / "a.py").write_text("def is_ready(x: Name) -> bool: ...\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "--ignore-names", "unused", "a.py"])

    assert result.stdout.splitlines() == [
        'a.py:1:26: NOPRIM007 return type is annotated "bool"'
    ]
