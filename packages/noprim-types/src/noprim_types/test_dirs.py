from pathlib import Path

import pytest
from pydantic import ValidationError

from noprim_types.dirs import EnsuredDir


def test_creates_a_missing_directory(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "nested"

    assert EnsuredDir(target).root.is_dir()


def test_accepts_an_existing_directory(tmp_path: Path) -> None:
    assert EnsuredDir(tmp_path).root == tmp_path


def test_rejects_a_path_held_by_a_file(tmp_path: Path) -> None:
    occupied = tmp_path / "occupied"
    occupied.touch()

    with pytest.raises(ValidationError, match="is not a directory"):
        _ = EnsuredDir(occupied)
