from pathlib import Path

import pytest

from noprim_io.check import CheckConfig, CheckPaths, IgnorePatterns, check_paths


def test_checks_an_explicitly_named_file(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def greet(name: str) -> None: ...\n")

    report = check_paths(CheckPaths((target,)), CheckConfig())

    assert [v.parameter for v in report.violations] == ["name"]


def test_walks_a_directory_recursively(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    _ = (tmp_path / "pkg" / "deep.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "top.py").write_text("def g(b: str) -> None: ...\n")
    _ = (tmp_path / "notes.txt").write_text("def h(c: str) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), CheckConfig())

    assert sorted(v.parameter for v in report.violations) == ["a", "b"]


def test_skips_gitignored_files_when_walking(tmp_path: Path) -> None:
    _ = (tmp_path / ".gitignore").write_text(".venv/\ngenerated.py\n")
    (tmp_path / ".venv").mkdir()
    _ = (tmp_path / ".venv" / "vendored.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "generated.py").write_text("def g(b: int) -> None: ...\n")
    _ = (tmp_path / "kept.py").write_text("def h(c: int) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), CheckConfig())

    assert [v.parameter for v in report.violations] == ["c"]


def test_lints_a_gitignored_file_when_named_explicitly(tmp_path: Path) -> None:
    _ = (tmp_path / ".gitignore").write_text("generated.py\n")
    target = tmp_path / "generated.py"
    _ = target.write_text("def g(b: int) -> None: ...\n")

    report = check_paths(CheckPaths((target,)), CheckConfig())

    assert [v.parameter for v in report.violations] == ["b"]


@pytest.mark.parametrize(
    ("glob", "expected"),
    [
        (IgnorePatterns(("migrations/*",)), ["kept"]),
        (IgnorePatterns(("**/old.py",)), ["kept"]),
        (IgnorePatterns(("*.py",)), []),
        (IgnorePatterns(("/kept.py",)), ["migrated"]),
    ],
    ids=["directory", "any-depth", "bare-name-is-any-depth", "leading-slash-anchors"],
)
def test_exclude_globs_match_root_relative_paths(
    tmp_path: Path, glob: IgnorePatterns, expected: list[str]
) -> None:
    (tmp_path / "migrations").mkdir()
    _ = (tmp_path / "migrations" / "old.py").write_text(
        "def f(migrated: int) -> None: ...\n"
    )
    _ = (tmp_path / "kept.py").write_text("def g(kept: int) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), CheckConfig(excludes=glob))

    assert sorted(v.parameter for v in report.violations) == sorted(expected)


def test_accepts_repeated_exclude_globs(tmp_path: Path) -> None:
    _ = (tmp_path / "a.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "b.py").write_text("def g(b: int) -> None: ...\n")
    _ = (tmp_path / "c.py").write_text("def h(c: int) -> None: ...\n")

    report = check_paths(
        CheckPaths((tmp_path,)), CheckConfig(excludes=IgnorePatterns(("a.py", "b.py")))
    )

    assert [v.parameter for v in report.violations] == ["c"]


def test_skips_stub_files(tmp_path: Path) -> None:
    stub = tmp_path / "shim.pyi"
    _ = stub.write_text("def f(a: int) -> None: ...\n")

    walked = check_paths(CheckPaths((tmp_path,)), CheckConfig())
    named = check_paths(CheckPaths((stub,)), CheckConfig())

    assert list(walked.violations) == []
    assert list(named.violations) == []


def test_does_not_follow_symlinked_directories(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    _ = (outside / "linked.py").write_text("def f(a: int) -> None: ...\n")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    report = check_paths(CheckPaths((root,)), CheckConfig())

    assert list(report.violations) == []


def test_reads_an_explicitly_named_symlinked_file(tmp_path: Path) -> None:
    real = tmp_path / "real.py"
    _ = real.write_text("def f(a: int) -> None: ...\n")
    link = tmp_path / "link.py"
    link.symlink_to(real)

    report = check_paths(CheckPaths((link,)), CheckConfig())

    assert [v.parameter for v in report.violations] == ["a"]


def test_undecodable_file_is_reported_as_an_error_without_stopping_the_run(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / "binary.py").write_bytes(b"\xfe\xff\x00def f(a: int): ...")
    _ = (tmp_path / "readable.py").write_text("def g(b: int) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), CheckConfig())

    assert [v.parameter for v in report.violations] == ["b"]
    assert [Path(e.filename).name for e in report.errors] == ["binary.py"]


def _repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    return tmp_path


def test_respects_a_gitignore_above_the_walked_directory(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _ = (root / ".gitignore").write_text("generated.py\n")
    _ = (root / "src" / "generated.py").write_text("def f(a: int) -> None: ...\n")
    _ = (root / "src" / "kept.py").write_text("def g(b: int) -> None: ...\n")

    report = check_paths(CheckPaths((root / "src",)), CheckConfig())

    assert [v.parameter for v in report.violations] == ["b"]


def test_exclude_globs_are_relative_to_the_repo_root(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _ = (root / "src" / "old.py").write_text("def f(a: int) -> None: ...\n")
    _ = (root / "src" / "kept.py").write_text("def g(b: int) -> None: ...\n")

    report = check_paths(
        CheckPaths((root / "src",)),
        CheckConfig(excludes=IgnorePatterns(("/src/old.py",))),
    )

    assert [v.parameter for v in report.violations] == ["b"]


def test_unparseable_file_is_reported_as_an_error_without_stopping_the_run(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / "broken.py").write_text("def f(a: int -> None:\n")
    _ = (tmp_path / "readable.py").write_text("def g(b: int) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), CheckConfig())

    assert [v.parameter for v in report.violations] == ["b"]
    assert [e.filename for e in report.errors] == [str(tmp_path / "broken.py")]
