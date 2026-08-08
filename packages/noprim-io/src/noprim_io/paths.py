from pathlib import Path

from pydantic import ConfigDict, RootModel, field_validator


class DirectoryEntry(RootModel[Path]):
    pass


class SourceFile(RootModel[Path]):
    # Deduplicated with a set when the same file is reached by two paths.
    model_config = ConfigDict(frozen=True)


class NotADirectoryValueError(ValueError):
    def __init__(self, value: Path) -> None:
        super().__init__(f"not a directory: {value}")


class ExistingDirectory(RootModel[Path]):
    @field_validator("root")
    @classmethod
    def _must_be_a_directory(cls, value: Path) -> Path:
        if not value.is_dir():
            raise NotADirectoryValueError(value)
        return value


def repo_root(start: ExistingDirectory) -> ExistingDirectory:
    return next(
        (
            ExistingDirectory(ancestor)
            for ancestor in [start.root, *start.root.parents]
            if (ancestor / ".git").exists()
        ),
        start,
    )
