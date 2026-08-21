import json
from enum import StrEnum
from os.path import relpath
from pathlib import Path, PurePosixPath

from iterpy import Arr
from pydantic import BaseModel, RootModel, ValidationError

from noprim_core.annotations import AnnotationText
from noprim_core.baseline import (
    Baseline,
    BaselineKey,
    KeyedViolation,
    KeyedViolations,
    PrunableFiles,
    TouchedFiles,
)
from noprim_core.rules.code import RuleCode
from noprim_core.site import Filename, Qualname, Surface
from noprim_core.violation import Violation
from noprim_io.check import CheckPaths, CheckReport
from noprim_io.paths import ExistingDirectory, SourceFile, repo_root
from noprim_types.verdict import Verdict


class BaselinePath(RootModel[Path]):
    pass


class BaselineLayout(StrEnum):
    SPLIT = "split"
    SINGLE = "single"


class Violations(RootModel[tuple[Violation, ...]]):
    pass


class WrittenFiles(RootModel[int]):
    pass


class DeletedFiles(RootModel[int]):
    pass


class BaselineWrite(BaseModel):
    path: BaselinePath
    layout: BaselineLayout
    written: WrittenFiles
    deleted: DeletedFiles


class BaselineVersion(RootModel[int]):
    @classmethod
    def current(cls) -> "BaselineVersion":
        # 2: entries name the rule that fired, so two rules on one annotation are
        # two entries rather than one.
        return cls(2)


class BaselineError(Exception):
    pass


class MalformedBaselineError(BaselineError):
    def __init__(self, path: BaselinePath) -> None:
        super().__init__(f"{path.root}: not a valid noprim baseline")


class UnsupportedBaselineVersionError(BaselineError):
    def __init__(self, path: BaselinePath, version: BaselineVersion) -> None:
        self.outdated = Verdict(version.root < BaselineVersion.current().root)
        remedy = (
            "rerun with --write-baseline to regenerate it"
            if self.outdated
            else "upgrade noprim"
        )
        super().__init__(
            f"{path.root}: unsupported baseline version {version.root}; {remedy}"
        )


class LayoutMismatchError(BaselineError):
    def __init__(self, path: BaselinePath, layout: BaselineLayout) -> None:
        split = Verdict(layout == BaselineLayout.SPLIT)
        found = "a file" if split else "a directory"
        wanted = "a directory" if split else "a file"
        other = BaselineLayout.SINGLE if split else BaselineLayout.SPLIT
        super().__init__(
            f"{path.root}: is {found}, but --baseline-layout {layout.value} writes"
            f" {wanted}; pass --baseline-layout {other.value}"
        )


class UnmirrorableFilenameError(BaselineError):
    def __init__(self, filename: Filename) -> None:
        super().__init__(
            f"{filename.root}: lies outside the baseline directory, so it has no"
            " file of its own; pass --baseline-layout single"
        )


class _Entry(BaseModel):
    code: RuleCode
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
        # relpath, not relative_to(walk_up=True): the latter is 3.12+, and a file
        # outside the anchor must key as `../…` rather than raise.
        return Filename(Path(relpath(resolved, self.root.root)).as_posix())

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
                        code=violation.code,
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
        .filter(lambda file: _within(file, targets))
        .filter(lambda file: not file.root.exists())
        .map(anchor.relative)
    )
    return PrunableFiles(analysed | vanished)


def _documents(path: BaselinePath) -> Arr[BaselinePath]:
    return Arr(sorted(path.root.rglob("*.json"))).map(BaselinePath)


def _guarded(path: BaselinePath, layout: BaselineLayout) -> BaselinePath:
    mismatched = (
        path.root.is_file() if layout == BaselineLayout.SPLIT else path.root.is_dir()
    )
    if mismatched:
        raise LayoutMismatchError(path, layout)
    return path


# Guarded, so a path of the wrong kind can never be read as merely absent: that
# would suppress nothing and report everything instead of naming the other layout.
def baseline_exists(path: BaselinePath, layout: BaselineLayout) -> Verdict:
    guarded = _guarded(path, layout)
    if layout == BaselineLayout.SINGLE:
        return Verdict(guarded.root.is_file())
    # An empty directory records nothing, so it is not a baseline yet — otherwise
    # a hand-made one would suppress everything by never being written.
    return Verdict(len(_documents(guarded).to_list()) > 0)


def _keys(path: BaselinePath) -> frozenset[BaselineKey]:
    try:
        document = _Document.model_validate_json(path.root.read_bytes())
    except (ValidationError, ValueError) as error:
        raise MalformedBaselineError(path) from error
    if document.version != BaselineVersion.current():
        raise UnsupportedBaselineVersionError(path, document.version)
    return frozenset(
        BaselineKey(
            filename=filename,
            code=entry.code,
            surface=entry.surface,
            qualname=entry.qualname,
            annotation=entry.annotation,
        )
        for filename, entries in document.files.items()
        for entry in entries
    )


def read_baseline(path: BaselinePath, layout: BaselineLayout) -> Baseline:
    guarded = _guarded(path, layout)
    if layout == BaselineLayout.SINGLE:
        return Baseline(_keys(guarded))
    return Baseline(frozenset().union(*_documents(guarded).map(_keys).to_list()))


class _Serialised(RootModel[str]):
    @classmethod
    def of(cls, baseline: Baseline) -> "_Serialised":
        grouped = (
            Arr(sorted(baseline.root)).groupby(lambda key: key.filename.root).to_list()
        )
        # Dumped by hand: a RootModel used as a dict key serialises as its repr.
        document = {
            "version": BaselineVersion.current().root,
            "files": {
                filename: [
                    _Entry(
                        code=key.code,
                        surface=key.surface,
                        qualname=key.qualname,
                        annotation=key.annotation,
                    ).model_dump(mode="json")
                    for key in keys
                ]
                for filename, keys in sorted(grouped)
            },
        }
        return cls(json.dumps(document, indent=2) + "\n")


class _ByFile(RootModel[dict[Filename, Baseline]]):
    @classmethod
    def of(cls, baseline: Baseline) -> "_ByFile":
        return cls(
            {
                Filename(filename): Baseline(frozenset(keys))
                for filename, keys in Arr(baseline.root)
                .groupby(lambda key: key.filename.root)
                .to_list()
            }
        )

    def entries(self, filename: Filename) -> Baseline:
        return self.root.get(filename, Baseline.empty())


def _mirrorable(filename: Filename) -> Verdict:
    relative = PurePosixPath(filename.root)
    return Verdict(not relative.is_absolute() and ".." not in relative.parts)


def _target(path: BaselinePath, filename: Filename) -> BaselinePath:
    return BaselinePath(path.root / f"{filename.root}.json")


def _prune(directory: BaselinePath, root: BaselinePath) -> None:
    # Git does not track an empty directory, so one left behind is dirty locally
    # and absent for everyone who pulls.
    current = directory.root
    while (
        current != root.root
        and root.root in current.parents
        and len(list(current.iterdir())) == 0
    ):
        current.rmdir()
        current = current.parent


def _write_one(path: BaselinePath, filename: Filename, entries: Baseline) -> None:
    target = _target(path, filename)
    target.root.parent.mkdir(parents=True, exist_ok=True)
    _ = target.root.write_text(_Serialised.of(entries).root)


def _delete_one(path: BaselinePath, filename: Filename) -> Verdict:
    target = _target(path, filename)
    if not target.root.is_file():
        return Verdict(root=False)
    target.root.unlink()
    _prune(BaselinePath(target.root.parent), path)
    return Verdict(root=True)


def _write_split(
    path: BaselinePath, baseline: Baseline, touched: TouchedFiles
) -> BaselineWrite:
    names = Arr(sorted(Arr(touched.root).map(lambda name: name.root).to_list())).map(
        Filename
    )
    escaping = names.filter(lambda filename: _mirrorable(filename).negated).to_list()
    if len(escaping) > 0:
        raise UnmirrorableFilenameError(escaping[0])
    by_file = _ByFile.of(baseline)
    recorded = names.filter(lambda filename: filename in by_file.root).to_list()
    emptied = names.filter(lambda filename: filename not in by_file.root).to_list()
    for filename in recorded:
        _write_one(path, filename, by_file.entries(filename))
    deleted = [filename for filename in emptied if _delete_one(path, filename)]
    return BaselineWrite(
        path=path,
        layout=BaselineLayout.SPLIT,
        written=WrittenFiles(len(recorded)),
        deleted=DeletedFiles(len(deleted)),
    )


def write_baseline(
    path: BaselinePath,
    baseline: Baseline,
    layout: BaselineLayout,
    touched: TouchedFiles,
) -> BaselineWrite:
    guarded = _guarded(path, layout)
    if layout == BaselineLayout.SPLIT:
        return _write_split(guarded, baseline, touched)
    _ = guarded.root.write_text(_Serialised.of(baseline).root)
    return BaselineWrite(
        path=guarded,
        layout=layout,
        written=WrittenFiles(1),
        deleted=DeletedFiles(0),
    )
