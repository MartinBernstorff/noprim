import tomllib
from pathlib import Path

from iterpy import Arr
from pydantic import BaseModel, RootModel
from pydantic_settings import (
    BaseSettings,
    PyprojectTomlConfigSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from noprim_core.config import CheckConfig
from noprim_core.settings import PathPatterns, RelativePath, Settings
from noprim_core.verdict import Verdict
from noprim_io.paths import ExistingDirectory, SourceFile, ancestry, repo_root


class ConfigFile(RootModel[Path]):
    pass


class LoadedSettings(BaseModel):
    settings: Settings
    # None when no config file was found, so patterns have no directory to hang off.
    anchor: ExistingDirectory | None = None

    @classmethod
    def empty(cls) -> "LoadedSettings":
        return cls(settings=Settings())

    def excludes(self) -> PathPatterns:
        return self.settings.exclude

    def for_file(self, file: SourceFile) -> CheckConfig:
        return self.settings.resolve(self._relative(file))

    def _relative(self, file: SourceFile) -> RelativePath:
        if self.anchor is None:
            return RelativePath("")
        try:
            return RelativePath(
                file.root.resolve().relative_to(self.anchor.root.resolve()).as_posix()
            )
        except ValueError:
            return RelativePath("")


class _Standalone(BaseSettings):
    model_config = SettingsConfigDict()


class _Pyproject(BaseSettings):
    model_config = SettingsConfigDict(pyproject_toml_table_header=("tool", "noprim"))


def _is_standalone(file: ConfigFile) -> Verdict:
    return Verdict(file.root.name == "noprim.toml")


def _declares_a_table(file: ConfigFile) -> Verdict:
    # A missing [tool.noprim] and an empty one both read back as {}, and only the
    # first should let the search continue upwards.
    document: dict[str, object] = tomllib.loads(file.root.read_text())
    tools = document.get("tool")
    return Verdict(isinstance(tools, dict) and "noprim" in tools)


def _is_config(file: ConfigFile) -> Verdict:
    if not file.root.is_file():
        return Verdict(root=False)
    if _is_standalone(file):
        return Verdict(root=True)
    return _declares_a_table(file)


def _config_in(directory: ExistingDirectory) -> ConfigFile | None:
    # Lazily, so a malformed pyproject.toml beside a winning noprim.toml is never read.
    return next(
        (
            file
            for file in (
                ConfigFile(directory.root / "noprim.toml"),
                ConfigFile(directory.root / "pyproject.toml"),
            )
            if _is_config(file)
        ),
        None,
    )


def _searched(start: ExistingDirectory) -> Arr[ExistingDirectory]:
    root = repo_root(start)
    if root is None:
        return Arr([start])
    lineage = ancestry(start).to_list()
    return Arr(lineage[: lineage.index(root) + 1])


class ConfigDocument(RootModel[dict[str, object]]):
    pass


def _document(file: ConfigFile) -> ConfigDocument:
    if _is_standalone(file):
        return ConfigDocument(
            TomlConfigSettingsSource(_Standalone, toml_file=file.root)()
        )
    return ConfigDocument(
        PyprojectTomlConfigSettingsSource(_Pyproject, toml_file=file.root)()
    )


def load_settings(start: ExistingDirectory) -> LoadedSettings:
    found = next(
        (
            (directory, file)
            for directory in _searched(start)
            if (file := _config_in(directory)) is not None
        ),
        None,
    )
    if found is None:
        return LoadedSettings(settings=Settings())
    directory, file = found
    return LoadedSettings(
        settings=Settings.model_validate(_document(file).root), anchor=directory
    )
