import json
from pathlib import Path

from iterpy import Arr
from pydantic import BaseModel, RootModel, ValidationError

from noprim_core import Surface, Violation
from noprim_core.baseline import (
    Baseline,
    BaselineKey,
    KeyedViolation,
    KeyedViolations,
    WalkedFiles,
)
from noprim_io.check import repo_root


class BaselinePath(RootModel[Path]):
    pass


class Violations(RootModel[tuple[Violation, ...]]):
    pass


class Filenames(RootModel[tuple[str, ...]]):
    pass


class BaselineVersion(RootModel[int]):
    @classmethod
    def current(cls) -> "BaselineVersion":
        return cls(1)


class MalformedBaselineError(Exception):
    def __init__(self, path: BaselinePath) -> None:
        super().__init__(f"{path.root}: not a valid noprim baseline")


class UnsupportedBaselineVersionError(Exception):
    def __init__(self, path: BaselinePath, version: BaselineVersion) -> None:
        super().__init__(
            f"{path.root}: unsupported baseline version {version.root}; upgrade noprim"
        )


class _Entry(BaseModel):
    surface: Surface
    qualname: str
    annotation: str


class _Document(BaseModel):
    version: int
    files: dict[str, list[_Entry]]


def _anchor(path: BaselinePath) -> Path:
    directory = path.root.resolve().parent
    root = repo_root(directory)
    return root if (root / ".git").exists() else directory


def _relative(filename: str, anchor: Path) -> str:
    return Path(filename).resolve().relative_to(anchor, walk_up=True).as_posix()


def keyed_violations(violations: Violations, path: BaselinePath) -> KeyedViolations:
    anchor = _anchor(path)
    return KeyedViolations(
        tuple(
            Arr(violations.root).map(
                lambda violation: KeyedViolation(
                    key=BaselineKey(
                        filename=_relative(violation.filename, anchor),
                        surface=violation.surface,
                        qualname=violation.qualname,
                        annotation=violation.annotation,
                    ),
                    violation=violation,
                )
            )
        )
    )


def walked_files(filenames: Filenames, path: BaselinePath) -> WalkedFiles:
    anchor = _anchor(path)
    return WalkedFiles(
        frozenset(Arr(filenames.root).map(lambda name: _relative(name, anchor)))
    )


def read_baseline(path: BaselinePath) -> Baseline:
    try:
        document = _Document.model_validate_json(path.root.read_bytes())
    except (ValidationError, ValueError) as error:
        raise MalformedBaselineError(path) from error
    version = BaselineVersion(document.version)
    if version != BaselineVersion.current():
        raise UnsupportedBaselineVersionError(path, version)
    return Baseline(
        frozenset(
            BaselineKey(
                filename=filename,
                surface=entry.surface,
                qualname=entry.qualname,
                annotation=entry.annotation,
            )
            for filename, entries in document.files.items()
            for entry in entries
        )
    )


def _entry_order(key: BaselineKey) -> tuple[str, str]:
    return (key.qualname, key.annotation)


def write_baseline(path: BaselinePath, baseline: Baseline) -> None:
    grouped = (
        Arr(sorted(baseline.root, key=_entry_order))
        .groupby(lambda key: key.filename)
        .to_list()
    )
    document = _Document(
        version=BaselineVersion.current().root,
        files={
            filename: [
                _Entry(
                    surface=key.surface,
                    qualname=key.qualname,
                    annotation=key.annotation,
                )
                for key in keys
            ]
            for filename, keys in sorted(grouped)
        },
    )
    _ = path.root.write_text(
        json.dumps(document.model_dump(mode="json"), indent=2, sort_keys=False) + "\n"
    )
