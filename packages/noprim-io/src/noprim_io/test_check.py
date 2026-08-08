from pathlib import Path

import pytest

from noprim_core.settings import PathPatterns, Settings
from noprim_core.site import Qualname
from noprim_core.suppression import SuppressionReason
from noprim_core.violation import Violation
from noprim_io.check import (
    CheckPaths,
    DiscoveryConfig,
    IgnorePatterns,
    check_paths,
)
from noprim_io.paths import ExistingDirectory
from noprim_io.settings import LoadedSettings


def _excluding(root: ExistingDirectory, patterns: IgnorePatterns) -> DiscoveryConfig:
    return DiscoveryConfig(
        settings=LoadedSettings(
            settings=Settings(exclude=PathPatterns(patterns.root)), anchor=root
        )
    )


def _leaf(violation: Violation) -> Qualname:
    return violation.qualname.leaf()


def test_checks_an_explicitly_named_file(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    _ = target.write_text("def greet(name: str) -> None: ...\n")

    report = check_paths(CheckPaths((target,)), DiscoveryConfig())

    assert [_leaf(v).root for v in report.violations] == ["name"]


def test_walks_a_directory_recursively(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    _ = (tmp_path / "pkg" / "deep.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "top.py").write_text("def g(b: str) -> None: ...\n")
    _ = (tmp_path / "notes.txt").write_text("def h(c: str) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), DiscoveryConfig())

    assert sorted(_leaf(v).root for v in report.violations) == ["a", "b"]


def test_skips_gitignored_files_when_walking(tmp_path: Path) -> None:
    _ = (tmp_path / ".gitignore").write_text(".venv/\ngenerated.py\n")
    (tmp_path / ".venv").mkdir()
    _ = (tmp_path / ".venv" / "vendored.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "generated.py").write_text("def g(b: int) -> None: ...\n")
    _ = (tmp_path / "kept.py").write_text("def h(c: int) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), DiscoveryConfig())

    assert [_leaf(v).root for v in report.violations] == ["c"]


def test_lints_a_gitignored_file_when_named_explicitly(tmp_path: Path) -> None:
    _ = (tmp_path / ".gitignore").write_text("generated.py\n")
    target = tmp_path / "generated.py"
    _ = target.write_text("def g(b: int) -> None: ...\n")

    report = check_paths(CheckPaths((target,)), DiscoveryConfig())

    assert [_leaf(v).root for v in report.violations] == ["b"]


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

    report = check_paths(
        CheckPaths((tmp_path,)), _excluding(ExistingDirectory(tmp_path), glob)
    )

    assert sorted(_leaf(v).root for v in report.violations) == sorted(expected)


def test_accepts_repeated_exclude_globs(tmp_path: Path) -> None:
    _ = (tmp_path / "a.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "b.py").write_text("def g(b: int) -> None: ...\n")
    _ = (tmp_path / "c.py").write_text("def h(c: int) -> None: ...\n")

    report = check_paths(
        CheckPaths((tmp_path,)),
        _excluding(ExistingDirectory(tmp_path), IgnorePatterns(("a.py", "b.py"))),
    )

    assert [_leaf(v).root for v in report.violations] == ["c"]


def test_skips_stub_files(tmp_path: Path) -> None:
    stub = tmp_path / "shim.pyi"
    _ = stub.write_text("def f(a: int) -> None: ...\n")

    walked = check_paths(CheckPaths((tmp_path,)), DiscoveryConfig())
    named = check_paths(CheckPaths((stub,)), DiscoveryConfig())

    assert list(walked.violations) == []
    assert list(named.violations) == []


def test_does_not_follow_symlinked_directories(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    _ = (outside / "linked.py").write_text("def f(a: int) -> None: ...\n")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    report = check_paths(CheckPaths((root,)), DiscoveryConfig())

    assert list(report.violations) == []


def test_reads_an_explicitly_named_symlinked_file(tmp_path: Path) -> None:
    real = tmp_path / "real.py"
    _ = real.write_text("def f(a: int) -> None: ...\n")
    link = tmp_path / "link.py"
    link.symlink_to(real)

    report = check_paths(CheckPaths((link,)), DiscoveryConfig())

    assert [_leaf(v).root for v in report.violations] == ["a"]


def test_undecodable_file_is_reported_as_an_error_without_stopping_the_run(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / "binary.py").write_bytes(b"\xfe\xff\x00def f(a: int): ...")
    _ = (tmp_path / "readable.py").write_text("def g(b: int) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), DiscoveryConfig())

    assert [_leaf(v).root for v in report.violations] == ["b"]
    assert [Path(e.filename.root).name for e in report.errors] == ["binary.py"]
    assert [(e.line.root, e.column.root) for e in report.errors] == [(1, 1)]
    assert report.errors[0].message.root.startswith("decode error: ")


def _make_repo(directory: ExistingDirectory) -> None:
    (directory.root / ".git").mkdir()
    (directory.root / "src").mkdir()


def test_respects_a_gitignore_above_the_walked_directory(tmp_path: Path) -> None:
    _make_repo(ExistingDirectory(tmp_path))
    _ = (tmp_path / ".gitignore").write_text("generated.py\n")
    _ = (tmp_path / "src" / "generated.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "src" / "kept.py").write_text("def g(b: int) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path / "src",)), DiscoveryConfig())

    assert [_leaf(v).root for v in report.violations] == ["b"]


def test_exclude_globs_are_relative_to_the_repo_root(tmp_path: Path) -> None:
    _make_repo(ExistingDirectory(tmp_path))
    _ = (tmp_path / "src" / "old.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "src" / "kept.py").write_text("def g(b: int) -> None: ...\n")

    report = check_paths(
        CheckPaths((tmp_path / "src",)),
        _excluding(ExistingDirectory(tmp_path), IgnorePatterns(("/src/old.py",))),
    )

    assert [_leaf(v).root for v in report.violations] == ["b"]


def test_unparseable_file_is_reported_as_an_error_without_stopping_the_run(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / "broken.py").write_text("x = 1\ndef f(a: int -> None:\n")
    _ = (tmp_path / "readable.py").write_text("def g(b: int) -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), DiscoveryConfig())

    assert [_leaf(v).root for v in report.violations] == ["b"]
    assert [e.filename.root for e in report.errors] == [str(tmp_path / "broken.py")]
    assert report.errors[0].line.root == 2
    assert report.errors[0].message.root.startswith("syntax error: ")


def test_an_ignored_file_is_still_checked_and_its_violations_counted(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / "opted_out.py").write_text(
        "# noprim: ignore-file\ndef f(a: int) -> str: ...\n"
    )

    report = check_paths(CheckPaths((tmp_path,)), DiscoveryConfig())

    assert report.violations == ()
    assert [str(file.root) for file in report.checked] == [
        str(tmp_path / "opted_out.py")
    ]
    assert [s.reason for s in report.suppressed] == [
        SuppressionReason.FILE_COMMENT,
        SuppressionReason.FILE_COMMENT,
    ]


def test_an_ignored_file_can_name_the_codes_it_opts_out_of(tmp_path: Path) -> None:
    _ = (tmp_path / "opted_out.py").write_text(
        "# noprim: ignore-file[NOPRIM002]\ndef f(a: int) -> str: ...\n"
    )

    report = check_paths(CheckPaths((tmp_path,)), DiscoveryConfig())

    assert [v.code.root for v in report.violations] == ["NOPRIM001"]
    assert [s.violation.code.root for s in report.suppressed] == ["NOPRIM002"]


def test_reports_the_files_it_walked(tmp_path: Path) -> None:
    _ = (tmp_path / "a.py").write_text("def f(a: int) -> None: ...\n")
    _ = (tmp_path / "b.py").write_text("def g() -> None: ...\n")

    report = check_paths(CheckPaths((tmp_path,)), DiscoveryConfig())

    assert sorted(str(file.root) for file in report.checked) == [
        str(tmp_path / "a.py"),
        str(tmp_path / "b.py"),
    ]
