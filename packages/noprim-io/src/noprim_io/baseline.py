import json
from pathlib import Path

from iterpy import Arr
from pydantic import BaseModel, RootModel, ValidationError

from noprim_core.baseline import (
    Baseline,
    BaselineKey,
    KeyedViolation,
    KeyedViolations,
    PrunableFiles,
)
from noprim_core.checker import (
    AnnotationText,
    Filename,
    Qualname,
    Surface,
    Verdict,
    Violation,
)
from noprim_io.check import CheckPaths, CheckReport
from noprim_io.paths import ExistingDirectory, SourceFile, repo_root


class BaselinePath(RootModel[Path]):
    pass


class Violations(RootModel[tuple[Violation, ...]]):
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
    qualname: Qualname
    annotation: AnnotationText


class _Document(BaseModel):
    version: BaselineVersion
    files: dict[Filename, list[_Entry]]


class _Anchor(RootModel[ExistingDirectory]):
    @classmethod
    def of(cls, path: BaselinePath) -> "_Anchor":
        directory = ExistingDirectory(path.root.resolve().parent)
        root = repo_root(directory)
        return cls(directory if root is None else root)

    def relative(self, file: SourceFile) -> Filename:
        resolved = file.root.resolve()
        return Filename(resolved.relative_to(self.root.root, walk_up=True).as_posix())

    def absolute(self, filename: Filename) -> SourceFile:
        return SourceFile((self.root.root / filename.root).resolve())


def keyed_violations(violations: Violations, path: BaselinePath) -> KeyedViolations:
    anchor = _Anchor.of(path)
    return KeyedViolations(
        tuple(
            Arr(violations.root).map(
                lambda violation: KeyedViolation(
                    key=BaselineKey(
                        filename=anchor.relative(
                            SourceFile(Path(violation.filename.root))
                        ),
                        surface=violation.surface,
                        qualname=violation.qualname,
                        annotation=violation.annotation,
                    ),
                    violation=violation,
                )
            )
        )
    )


def _within(file: SourceFile, targets: CheckPaths) -> Verdict:
    return Verdict(
        Arr(targets.root)
        .map(lambda target: target.resolve())
        .any(lambda target: file.root == target or target in file.root.parents)
    )


def prunable_files(
    report: CheckReport, targets: CheckPaths, baseline: Baseline, path: BaselinePath
) -> PrunableFiles:
    anchor = _Anchor.of(path)
    # A file noprim could not parse yields no evidence that its entries are stale.
    unreadable = frozenset(
        Arr(report.errors).map(
            lambda error: anchor.relative(SourceFile(Path(error.filename.root)))
        )
    )
    analysed = frozenset(Arr(report.checked).map(anchor.relative)) - unreadable
    vanished = frozenset(
        Arr(baseline.root)
        .map(lambda key: anchor.absolute(key.filename))
        .filter(lambda file: _within(file, targets).root and not file.root.exists())
        .map(anchor.relative)
    )
    return PrunableFiles(analysed | vanished)


def read_baseline(path: BaselinePath) -> Baseline:
    try:
        document = _Document.model_validate_json(path.root.read_bytes())
    except (ValidationError, ValueError) as error:
        raise MalformedBaselineError(path) from error
    if document.version != BaselineVersion.current():
        raise UnsupportedBaselineVersionError(path, document.version)
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


def write_baseline(path: BaselinePath, baseline: Baseline) -> None:
    grouped = (
        Arr(sorted(baseline.root)).groupby(lambda key: key.filename.root).to_list()
    )
    # Dumped by hand: a RootModel used as a dict key serialises as its repr.
    document = {
        "version": BaselineVersion.current().root,
        "files": {
            filename: [
                _Entry(
                    surface=key.surface,
                    qualname=key.qualname,
                    annotation=key.annotation,
                ).model_dump(mode="json")
                for key in keys
            ]
            for filename, keys in sorted(grouped)
        },
    }
    _ = path.root.write_text(json.dumps(document, indent=2) + "\n")
