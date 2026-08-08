import json
from pathlib import Path
from typing import Any, cast

import pytest

from noprim_core.annotations import AnnotationText
from noprim_core.baseline import Baseline, BaselineKey
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
    BaselinePath,
    MalformedBaselineError,
    UnsupportedBaselineVersionError,
    Violations,
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


def test_round_trips_a_baseline(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    baseline = Baseline(
        frozenset(
            {
                _key(Filename("src/a.py"), Qualname("f.a")),
                _key(Filename("src/a.py"), Qualname("f.b")),
            }
        )
    )

    write_baseline(path, baseline)

    assert read_baseline(path) == baseline


def test_groups_entries_by_filename_on_disk(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")

    write_baseline(
        path,
        Baseline(
            frozenset(
                {
                    _key(Filename("src/a.py"), Qualname("f.a")),
                    _key(Filename("src/b.py"), Qualname("f.a")),
                }
            )
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


def test_rejects_a_baseline_that_is_not_json(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _ = path.root.write_text("{oops")

    with pytest.raises(MalformedBaselineError):
        _ = read_baseline(path)


def test_rejects_a_baseline_written_by_a_later_noprim(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _ = path.root.write_text(json.dumps({"version": 3, "files": {}}))

    with pytest.raises(UnsupportedBaselineVersionError) as caught:
        _ = read_baseline(path)
    assert "upgrade noprim" in str(caught.value)


def test_an_older_baseline_asks_to_be_regenerated(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _ = path.root.write_text(json.dumps({"version": 1, "files": {}}))

    with pytest.raises(UnsupportedBaselineVersionError) as caught:
        _ = read_baseline(path)
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
