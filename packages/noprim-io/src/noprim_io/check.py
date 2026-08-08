from pathlib import Path

import pathspec
from iterpy import Arr
from pydantic import BaseModel, Field, RootModel

from noprim_core import (
    CheckConfig,
    ColumnNumber,
    Filename,
    LineNumber,
    SourceCode,
    Verdict,
    Violation,
    check_source,
)
from noprim_io.paths import (
    DirectoryEntry,
    ExistingDirectory,
    SourceFile,
    repo_root,
)
from noprim_io.settings import LoadedSettings


class CheckPaths(RootModel[tuple[Path, ...]]):
    pass


class ErrorMessage(RootModel[str]):
    pass


class FileCount(RootModel[int]):
    pass


class IgnorePatterns(RootModel[tuple[str, ...]]):
    pass


class DiscoveryConfig(BaseModel):
    settings: LoadedSettings = Field(default_factory=LoadedSettings.empty)

    def for_file(self, file: SourceFile) -> CheckConfig:
        return self.settings.settings.resolve(self.settings.relative(file))


class FileError(BaseModel):
    filename: Filename
    line: LineNumber
    column: ColumnNumber
    message: ErrorMessage


class CheckReport(BaseModel):
    violations: tuple[Violation, ...]
    errors: tuple[FileError, ...]
    files_checked: FileCount


class _AnchoredSpec(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    anchor: ExistingDirectory
    spec: pathspec.PathSpec[pathspec.Pattern]

    def matches(self, entry: DirectoryEntry) -> Verdict:
        # A target outside the anchor has no path relative to it, so nothing anchored
        # there can describe it.
        if not entry.root.is_relative_to(self.anchor.root):
            return Verdict(root=False)
        relative = entry.root.relative_to(self.anchor.root).as_posix()
        suffix = "/" if entry.root.is_dir() else ""
        return Verdict(self.spec.match_file(f"{relative}{suffix}"))


def _spec_anchored_at(
    anchor: ExistingDirectory, patterns: IgnorePatterns
) -> Arr[_AnchoredSpec]:
    if len(patterns.root) == 0:
        return Arr([])
    return Arr(
        [
            _AnchoredSpec(
                anchor=anchor,
                spec=pathspec.PathSpec.from_lines("gitignore", patterns.root),
            )
        ]
    )


def _gitignore_at(directory: ExistingDirectory) -> Arr[_AnchoredSpec]:
    gitignore = directory.root / ".gitignore"
    if not gitignore.is_file():
        return Arr([])
    return _spec_anchored_at(
        directory, IgnorePatterns(tuple(gitignore.read_text().splitlines()))
    )


def _ancestors_below(
    root: ExistingDirectory, start: ExistingDirectory
) -> Arr[ExistingDirectory]:
    lineage = [start.root, *start.root.parents]
    if root.root not in lineage:
        return Arr([])
    below = list(reversed(lineage[: lineage.index(root.root) + 1]))[:-1]
    return Arr(below).map(ExistingDirectory)


def _is_python_source(entry: DirectoryEntry) -> Verdict:
    return Verdict(entry.root.suffix == ".py")


def _files_under(
    directory: ExistingDirectory, inherited: Arr[_AnchoredSpec]
) -> Arr[SourceFile]:
    specs = inherited.chain(_gitignore_at(directory))
    entries = (
        Arr(sorted(directory.root.iterdir()))
        .map(DirectoryEntry)
        # pyrefly: ignore[implicit-bool]
        .filter(lambda entry: not _matches_any(entry, specs))
        .to_list()
    )
    nested = (
        Arr(entries)
        .filter(lambda entry: entry.root.is_dir() and not entry.root.is_symlink())
        .map(lambda child: _files_under(ExistingDirectory(child.root), specs))
        .flatten()
    )
    return (
        Arr(entries)
        # pyrefly: ignore[implicit-bool, bad-argument-type]
        .filter(lambda entry: _is_python_source(entry) and entry.root.is_file())
        .map(lambda entry: SourceFile(entry.root))
        .chain(nested)
    )


def _matches_any(entry: DirectoryEntry, specs: Arr[_AnchoredSpec]) -> Verdict:
    return Verdict(
        specs.map(lambda spec: spec.matches(entry)).any(lambda hit: hit.root)
    )


def _walk(directory: ExistingDirectory, config: DiscoveryConfig) -> Arr[SourceFile]:
    root = repo_root(directory)
    anchor = config.settings.anchor
    inherited = (
        _ancestors_below(root, directory)
        .map(_gitignore_at)
        .flatten()
        .chain(
            _spec_anchored_at(
                root if anchor is None else anchor,
                IgnorePatterns(config.settings.excludes().root),
            )
        )
    )
    return _files_under(directory, inherited)


def _files_to_check(paths: CheckPaths, config: DiscoveryConfig) -> Arr[SourceFile]:
    return (
        Arr(paths.root)
        .map(
            lambda path: (
                _walk(ExistingDirectory(path), config)
                if path.is_dir()
                else Arr([SourceFile(path)])
            )
        )
        .flatten()
        # pyrefly: ignore[bad-argument-type]
        .filter(lambda file: _is_python_source(DirectoryEntry(file.root)))
        .unique()
    )


def _file_error(file: SourceFile, error: UnicodeDecodeError | SyntaxError) -> FileError:
    if isinstance(error, SyntaxError):
        return FileError(
            filename=Filename(str(file.root)),
            line=LineNumber(error.lineno if error.lineno is not None else 1),
            column=ColumnNumber(error.offset if error.offset is not None else 1),
            message=ErrorMessage(f"syntax error: {error.msg}"),
        )
    return FileError(
        filename=Filename(str(file.root)),
        line=LineNumber(1),
        column=ColumnNumber(1),
        message=ErrorMessage(f"decode error: {error.reason}"),
    )


def _check_one(file: SourceFile, config: CheckConfig) -> CheckReport:
    try:
        source = SourceCode(file.root.read_text())
        violations = check_source(source, Filename(str(file.root)), config)
    except (UnicodeDecodeError, SyntaxError) as error:
        return CheckReport(
            violations=(),
            errors=(_file_error(file, error),),
            files_checked=FileCount(1),
        )
    return CheckReport(
        violations=tuple(violations), errors=(), files_checked=FileCount(1)
    )


def check_paths(paths: CheckPaths, config: DiscoveryConfig) -> CheckReport:
    reports = (
        _files_to_check(paths, config)
        .map(lambda file: _check_one(file, config.for_file(file)))
        .to_list()
    )
    return CheckReport(
        violations=tuple(Arr(reports).map(lambda r: r.violations).flatten()),
        errors=tuple(Arr(reports).map(lambda r: r.errors).flatten()),
        files_checked=FileCount(len(reports)),
    )
