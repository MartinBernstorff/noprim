from pathlib import Path

from pydantic import RootModel, field_validator


class NotADirectoryValueError(ValueError):
    def __init__(self, value: Path) -> None:
        super().__init__(f"exists and is not a directory: {value}")


class EnsuredDir(RootModel[Path]):
    # Validation touches the disk: holding an EnsuredDir is the guarantee that the
    # directory is there, which nothing but creating it can provide.
    @field_validator("root")
    @classmethod
    def _must_be_a_directory(cls, value: Path) -> Path:
        # follow_symlinks=False: a dangling symlink does not "exist", and mkdir would
        # then raise FileExistsError past pydantic instead of a ValidationError.
        if value.exists(follow_symlinks=False) and not value.is_dir():
            raise NotADirectoryValueError(value)
        value.mkdir(parents=True, exist_ok=True)
        return value
