import json
from pathlib import Path
from typing import Any, cast

import pytest

from noprim_core.annotations import AnnotationText
from noprim_core.baseline import Baseline, BaselineKey, TouchedFiles
from noprim_core.rules.code import RuleCode
from noprim_core.site import (
    ColumnNumber,
    Filename,
    LineNumber,
    Qualname,
    Surface,
)
from noprim_core.violation import Violation
from noprim_io.baseline import (
    BaselineLayout,
    BaselinePath,
    LayoutMismatchError,
    MalformedBaselineError,
    UnmirrorableFilenameError,
    UnsupportedBaselineVersionError,
    Violations,
    baseline_exists,
    keyed_violations,
    prunable_files,
    read_baseline,
    write_baseline,
)
from noprim_io.check import CheckPaths, CheckReport, ErrorMessage, FileError
from noprim_io.paths import SourceFile


def _key(filename: Filename, qualname: Qualname) -> BaselineKey:
    return BaselineKey(
        filename=filename,
        code=RuleCode("NOPRIM001"),
        surface=Surface.PARAMETER,
        qualname=qualname,
        annotation=AnnotationText("str"),
    )


def _report(
    checked: tuple[SourceFile, ...], errors: tuple[FileError, ...] = ()
) -> CheckReport:
    return CheckReport(violations=(), errors=errors, checked=checked)


def _touched(*filenames: Filename) -> TouchedFiles:
    return TouchedFiles(frozenset(filenames))


def _baseline(*keys: BaselineKey) -> Baseline:
    return Baseline(frozenset(keys))


def _single(path: BaselinePath, baseline: Baseline) -> None:
    _ = write_baseline(path, baseline, BaselineLayout.SINGLE, _touched())


def test_round_trips_a_single_file_baseline(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    baseline = _baseline(
        _key(Filename("src/a.py"), Qualname("f.a")),
        _key(Filename("src/a.py"), Qualname("f.b")),
    )

    _single(path, baseline)

    assert read_baseline(path, BaselineLayout.SINGLE) == baseline


def test_round_trips_a_split_baseline(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / "baseline")
    baseline = _baseline(
        _key(Filename("src/a.py"), Qualname("f.a")),
        _key(Filename("src/b.py"), Qualname("f.a")),
    )

    _ = write_baseline(
        path,
        baseline,
        BaselineLayout.SPLIT,
        _touched(Filename("src/a.py"), Filename("src/b.py")),
    )

    assert read_baseline(path, BaselineLayout.SPLIT) == baseline


def test_groups_entries_by_filename_on_disk(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")

    _single(
        path,
        _baseline(
            _key(Filename("src/a.py"), Qualname("f.a")),
            _key(Filename("src/b.py"), Qualname("f.a")),
        ),
    )

    written = cast("dict[str, Any]", json.loads(path.root.read_text()))
    files = cast("dict[str, list[dict[str, str]]]", written["files"])
    assert written["version"] == 2
    assert sorted(files) == ["src/a.py", "src/b.py"]
    assert files["src/a.py"] == [
        {
            "code": "NOPRIM001",
            "surface": "parameter",
            "qualname": "f.a",
            "annotation": "str",
        }
    ]


def test_a_split_baseline_mirrors_the_source_tree(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / "baseline")

    _ = write_baseline(
        path,
        _baseline(_key(Filename("src/pkg/a.py"), Qualname("f.a"))),
        BaselineLayout.SPLIT,
        _touched(Filename("src/pkg/a.py")),
    )

    entry = path.root / "src" / "pkg" / "a.py.json"
    written = cast("dict[str, Any]", json.loads(entry.read_text()))
    assert written["version"] == 2
    assert list(cast("dict[str, Any]", written["files"])) == ["src/pkg/a.py"]


def test_a_split_write_leaves_files_it_did_not_touch_alone(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / "baseline")
    _ = write_baseline(
        path,
        _baseline(
            _key(Filename("a.py"), Qualname("f.a")),
            _key(Filename("b.py"), Qualname("f.a")),
        ),
        BaselineLayout.SPLIT,
        _touched(Filename("a.py"), Filename("b.py")),
    )
    before = (path.root / "b.py.json").read_bytes()

    _ = write_baseline(
        path,
        _baseline(
            _key(Filename("a.py"), Qualname("f.b")),
            _key(Filename("b.py"), Qualname("f.a")),
        ),
        BaselineLayout.SPLIT,
        _touched(Filename("a.py")),
    )

    assert (path.root / "b.py.json").read_bytes() == before
    assert read_baseline(path, BaselineLayout.SPLIT) == _baseline(
        _key(Filename("a.py"), Qualname("f.b")),
        _key(Filename("b.py"), Qualname("f.a")),
    )


def test_a_split_write_deletes_the_file_of_a_source_file_with_no_entries(
    tmp_path: Path,
) -> None:
    path = BaselinePath(tmp_path / "baseline")
    _ = write_baseline(
        path,
        _baseline(_key(Filename("src/pkg/a.py"), Qualname("f.a"))),
        BaselineLayout.SPLIT,
        _touched(Filename("src/pkg/a.py")),
    )

    write = write_baseline(
        path, Baseline.empty(), BaselineLayout.SPLIT, _touched(Filename("src/pkg/a.py"))
    )

    assert write.deleted.root == 1
    # An empty directory is dirty locally and absent for everyone who pulls.
    assert list(path.root.iterdir()) == []


def test_an_empty_split_directory_is_not_a_baseline_yet(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / "baseline")
    path.root.mkdir()

    assert baseline_exists(path, BaselineLayout.SPLIT).negated
    assert read_baseline(path, BaselineLayout.SPLIT) == Baseline.empty()


def test_a_shared_file_is_never_read_as_an_absent_split_baseline(
    tmp_path: Path,
) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _single(path, Baseline.empty())

    with pytest.raises(LayoutMismatchError):
        _ = baseline_exists(path, BaselineLayout.SPLIT)


def test_a_directory_is_never_read_as_an_absent_shared_baseline(
    tmp_path: Path,
) -> None:
    path = BaselinePath(tmp_path / "baseline")
    path.root.mkdir()

    with pytest.raises(LayoutMismatchError):
        _ = baseline_exists(path, BaselineLayout.SINGLE)


def test_a_source_file_outside_the_baseline_directory_cannot_be_split(
    tmp_path: Path,
) -> None:
    path = BaselinePath(tmp_path / "baseline")

    with pytest.raises(UnmirrorableFilenameError) as caught:
        _ = write_baseline(
            path,
            _baseline(_key(Filename("../a.py"), Qualname("f.a"))),
            BaselineLayout.SPLIT,
            _touched(Filename("../a.py")),
        )
    assert "--baseline-layout single" in str(caught.value)


def test_a_single_file_is_not_a_split_baseline(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _single(path, Baseline.empty())

    with pytest.raises(LayoutMismatchError) as caught:
        _ = read_baseline(path, BaselineLayout.SPLIT)
    assert "--baseline-layout single" in str(caught.value)


def test_a_split_directory_is_not_a_single_baseline(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / "baseline")
    path.root.mkdir()

    with pytest.raises(LayoutMismatchError) as caught:
        _ = write_baseline(path, Baseline.empty(), BaselineLayout.SINGLE, _touched())
    assert "--baseline-layout split" in str(caught.value)


def test_rejects_a_baseline_that_is_not_json(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _ = path.root.write_text("{oops")

    with pytest.raises(MalformedBaselineError):
        _ = read_baseline(path, BaselineLayout.SINGLE)


def test_rejects_a_split_entry_that_is_not_json(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / "baseline")
    path.root.mkdir()
    _ = (path.root / "a.py.json").write_text("{oops")

    with pytest.raises(MalformedBaselineError) as caught:
        _ = read_baseline(path, BaselineLayout.SPLIT)
    assert "a.py.json" in str(caught.value)


def test_rejects_a_baseline_written_by_a_later_noprim(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _ = path.root.write_text(json.dumps({"version": 3, "files": {}}))

    with pytest.raises(UnsupportedBaselineVersionError) as caught:
        _ = read_baseline(path, BaselineLayout.SINGLE)
    assert "upgrade noprim" in str(caught.value)


def test_an_older_baseline_asks_to_be_regenerated(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _ = path.root.write_text(json.dumps({"version": 1, "files": {}}))

    with pytest.raises(UnsupportedBaselineVersionError) as caught:
        _ = read_baseline(path, BaselineLayout.SINGLE)
    assert "--write-baseline" in str(caught.value)


def test_keys_violations_relative_to_the_repo_above_the_baseline(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "nested").mkdir()
    path = BaselinePath(tmp_path / "nested" / ".noprim.json")
    violation = Violation(
        filename=Filename(str(tmp_path / "src" / "a.py")),
        code=RuleCode("NOPRIM001"),
        line=LineNumber(1),
        column=ColumnNumber(1),
        surface=Surface.PARAMETER,
        qualname=Qualname("f.a"),
        annotation=AnnotationText("str"),
    )

    keyed = keyed_violations(Violations((violation,)), path)

    assert [entry.key.filename.root for entry in keyed.root] == ["src/a.py"]


def test_keys_relative_to_the_baseline_directory_without_a_repo(
    tmp_path: Path,
) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    (tmp_path / "src").mkdir()
    analysed = tmp_path / "src" / "a.py"
    _ = analysed.write_text("")

    prunable = prunable_files(
        _report((SourceFile(analysed),)),
        CheckPaths((tmp_path,)),
        Baseline.empty(),
        path,
    )

    assert prunable.root == frozenset({Filename("src/a.py")})


def test_a_file_that_would_not_parse_is_not_prunable(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    broken = tmp_path / "broken.py"
    _ = broken.write_text("")
    error = FileError(
        filename=Filename(str(broken)),
        line=LineNumber(1),
        column=ColumnNumber(1),
        message=ErrorMessage("syntax error: nope"),
    )

    prunable = prunable_files(
        _report((SourceFile(broken),), (error,)),
        CheckPaths((tmp_path,)),
        Baseline.empty(),
        path,
    )

    assert prunable.root == frozenset()


def test_an_entry_whose_file_is_gone_is_prunable(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")

    prunable = prunable_files(
        _report(()),
        CheckPaths((tmp_path,)),
        Baseline(frozenset({_key(Filename("deleted.py"), Qualname("f.a"))})),
        path,
    )

    assert prunable.root == frozenset({Filename("deleted.py")})


def test_an_entry_outside_the_run_is_not_prunable(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    (tmp_path / "inside").mkdir()

    prunable = prunable_files(
        _report(()),
        CheckPaths((tmp_path / "inside",)),
        Baseline(frozenset({_key(Filename("outside/deleted.py"), Qualname("f.a"))})),
        path,
    )

    assert prunable.root == frozenset()
