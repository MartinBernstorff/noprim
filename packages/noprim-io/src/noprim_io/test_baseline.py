import json
from pathlib import Path
from typing import Any, cast

import pytest

from noprim_core import Surface, Violation
from noprim_core.baseline import Baseline, BaselineKey
from noprim_io.baseline import (
    BaselinePath,
    Filenames,
    MalformedBaselineError,
    UnsupportedBaselineVersionError,
    Violations,
    keyed_violations,
    read_baseline,
    walked_files,
    write_baseline,
)


def _key(filename: str = "src/a.py", qualname: str = "f.a") -> BaselineKey:
    return BaselineKey(
        filename=filename,
        surface=Surface.PARAMETER,
        qualname=qualname,
        annotation="str",
    )


def test_round_trips_a_baseline(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    baseline = Baseline(frozenset({_key(), _key(qualname="f.b")}))

    write_baseline(path, baseline)

    assert read_baseline(path) == baseline


def test_groups_entries_by_filename_on_disk(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")

    write_baseline(path, Baseline(frozenset({_key(), _key(filename="src/b.py")})))

    written = cast("dict[str, Any]", json.loads(path.root.read_text()))
    files = cast("dict[str, list[dict[str, str]]]", written["files"])
    assert written["version"] == 1
    assert sorted(files) == ["src/a.py", "src/b.py"]
    assert files["src/a.py"] == [
        {"surface": "parameter", "qualname": "f.a", "annotation": "str"}
    ]


def test_rejects_a_baseline_that_is_not_json(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _ = path.root.write_text("{oops")

    with pytest.raises(MalformedBaselineError):
        _ = read_baseline(path)


def test_rejects_a_baseline_written_by_a_later_noprim(tmp_path: Path) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")
    _ = path.root.write_text(json.dumps({"version": 2, "files": {}}))

    with pytest.raises(UnsupportedBaselineVersionError):
        _ = read_baseline(path)


def test_keys_violations_relative_to_the_repo_above_the_baseline(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "nested").mkdir()
    path = BaselinePath(tmp_path / "nested" / ".noprim.json")
    violation = Violation(
        filename=str(tmp_path / "src" / "a.py"),
        line=1,
        column=1,
        surface=Surface.PARAMETER,
        qualname="f.a",
        annotation="str",
    )

    keyed = keyed_violations(Violations((violation,)), path)

    assert [entry.key.filename for entry in keyed.root] == ["src/a.py"]


def test_keys_relative_to_the_baseline_directory_without_a_repo(
    tmp_path: Path,
) -> None:
    path = BaselinePath(tmp_path / ".noprim.json")

    walked = walked_files(Filenames((str(tmp_path / "src" / "a.py"),)), path)

    assert walked.root == frozenset({"src/a.py"})
