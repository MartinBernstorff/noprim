from pathlib import Path

import pathspec
from iterpy import Arr
from pydantic import BaseModel, RootModel

from noprim_core import Filename, PrimitiveNames, SourceCode, Violation, check_source


class CheckPaths(RootModel[tuple[Path, ...]]):
    pass


class IgnorePatterns(RootModel[tuple[str, ...]]):
    pass


class CheckConfig(BaseModel):
    excludes: IgnorePatterns = IgnorePatterns(())


class FileError(BaseModel):
    filename: str
    message: str


class CheckReport(BaseModel):
    violations: tuple[Violation, ...]
    errors: tuple[FileError, ...]
    files_checked: int


class _AnchoredSpec(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    anchor: Path
    spec: pathspec.PathSpec[pathspec.Pattern]

    def matches(self, path: Path) -> bool:
        relative = path.relative_to(self.anchor).as_posix()
        suffix = "/" if path.is_dir() else ""
        return self.spec.match_file(f"{relative}{suffix}")


def _spec_anchored_at(anchor: Path, patterns: IgnorePatterns) -> Arr[_AnchoredSpec]:
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


def _gitignore_at(directory: Path) -> Arr[_AnchoredSpec]:
    gitignore = directory / ".gitignore"
    if not gitignore.is_file():
        return Arr([])
    return _spec_anchored_at(
        directory, IgnorePatterns(tuple(gitignore.read_text().splitlines()))
    )


def _repo_root(start: Path) -> Path:
    return next(
        (
            ancestor
            for ancestor in [start, *start.parents]
            if (ancestor / ".git").exists()
        ),
        start,
    )


def _ancestors_below(root: Path, start: Path) -> Arr[Path]:
    lineage = [start, *start.parents]
    if root not in lineage:
        return Arr([])
    return Arr(list(reversed(lineage[: lineage.index(root) + 1]))[:-1])


def _is_python_source(path: Path) -> bool:
    return path.suffix == ".py"


def _files_under(directory: Path, inherited: Arr[_AnchoredSpec]) -> Arr[Path]:
    specs = inherited.chain(_gitignore_at(directory))
    entries = (
        Arr(sorted(directory.iterdir()))
        .filter(lambda entry: not _matches_any(entry, specs))
        .to_list()
    )
    nested = (
        Arr(entries)
        .filter(lambda entry: entry.is_dir() and not entry.is_symlink())
        .map(lambda child: _files_under(child, specs))
        .flatten()
    )
    return (
        Arr(entries)
        .filter(lambda entry: _is_python_source(entry) and entry.is_file())
        .chain(nested)
    )


def _matches_any(path: Path, specs: Arr[_AnchoredSpec]) -> bool:
    return specs.map(lambda spec: spec.matches(path)).any(lambda hit: hit)


def _walk(directory: Path, excludes: IgnorePatterns) -> Arr[Path]:
    root = _repo_root(directory)
    inherited = (
        _ancestors_below(root, directory)
        .map(_gitignore_at)
        .flatten()
        .chain(_spec_anchored_at(root, excludes))
    )
    return _files_under(directory, inherited)


def _files_to_check(paths: CheckPaths, excludes: IgnorePatterns) -> Arr[Path]:
    return (
        Arr(paths.root)
        .map(lambda path: _walk(path, excludes) if path.is_dir() else Arr([path]))
        .flatten()
        .filter(_is_python_source)
        .unique()
    )


def _check_one(path: Path) -> CheckReport:
    try:
        source = SourceCode(path.read_text())
        violations = check_source(source, Filename(str(path)), PrimitiveNames.default())
    except (UnicodeDecodeError, SyntaxError) as error:
        return CheckReport(
            violations=(),
            errors=(FileError(filename=str(path), message=str(error)),),
            files_checked=1,
        )
    return CheckReport(violations=tuple(violations), errors=(), files_checked=1)


def check_paths(paths: CheckPaths, config: CheckConfig) -> CheckReport:
    reports = _files_to_check(paths, config.excludes).map(_check_one).to_list()
    return CheckReport(
        violations=tuple(Arr(reports).map(lambda r: r.violations).flatten()),
        errors=tuple(Arr(reports).map(lambda r: r.errors).flatten()),
        files_checked=len(reports),
    )
