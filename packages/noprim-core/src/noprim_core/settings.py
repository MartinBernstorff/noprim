from typing import Self

import pathspec
from iterpy import Arr
from pydantic import BaseModel, ConfigDict, RootModel, model_validator

from noprim_core.config import (
    CheckConfig,
    DeniedTypes,
    NamePatterns,
    TopTypes,
)
from noprim_core.rules.code import Selection, Selectors
from noprim_core.rules.preset import Preset
from noprim_core.rules.registry import selection, validate_selectors
from noprim_core.verdict import Verdict


class AllowedNames(RootModel[tuple[str, ...]]):
    pass


class DeniedNames(RootModel[tuple[str, ...]]):
    pass


class PathPatterns(RootModel[tuple[str, ...]]):
    pass


class RelativePath(RootModel[str]):
    pass


class AllowedAndDeniedError(ValueError):
    def __init__(self, names: AllowedNames) -> None:
        super().__init__(f"both allowed and denied: {', '.join(names.root)}")


class EmptyNameError(ValueError):
    def __init__(self) -> None:
        super().__init__("allow and deny need a type name; got an empty one")


class NotOnDenyListError(ValueError):
    def __init__(self, names: AllowedNames) -> None:
        super().__init__(
            f"allow of a name that is not on the deny-list: {', '.join(names.root)}"
        )


class AllowedTopTypeError(ValueError):
    def __init__(self, names: AllowedNames) -> None:
        super().__init__(
            f"allow of a type governed by the top-type rules: {', '.join(names.root)}. "
            "Deselect them instead; those rules are all or nothing."
        )


def _validated(allow: AllowedNames, deny: DeniedNames, denied: DeniedTypes) -> None:
    # "" is the sentinel for unresolvable annotations, so denying it matches everything.
    if "" in set(allow.root) | set(deny.root):
        raise EmptyNameError
    conflicting = sorted(set(allow.root) & set(deny.root))
    if len(conflicting) > 0:
        raise AllowedAndDeniedError(AllowedNames(tuple(conflicting)))
    top = sorted(set(allow.root) & TopTypes.default().root)
    if len(top) > 0:
        raise AllowedTopTypeError(AllowedNames(tuple(top)))
    unknown = sorted(set(allow.root) - denied.root)
    if len(unknown) > 0:
        raise NotOnDenyListError(AllowedNames(tuple(unknown)))


def _adjusted(
    denied: DeniedTypes, allow: AllowedNames, deny: DeniedNames
) -> DeniedTypes:
    return DeniedTypes((denied.root - set(allow.root)) | set(deny.root))


class PerPathError(ValueError):
    def __init__(self, paths: PathPatterns, cause: ValueError) -> None:
        super().__init__(f"{cause} (per-path entry for {', '.join(paths.root)})")


class FieldName(RootModel[str]):
    pass


def _to_kebab(name: FieldName) -> FieldName:
    return FieldName(name.root.replace("_", "-"))


# pydantic fixes this signature, so the primitive cannot be wrapped.
def _alias(name: str) -> str:  # noprim: ignore
    return _to_kebab(FieldName(name)).root


_SCHEMA = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=_alias)


# ignore-names predates the split and stays the way to speak about both surfaces.
class IgnoredNames(BaseModel):
    model_config = _SCHEMA

    ignore_names: NamePatterns = NamePatterns(())
    ignore_param_names: NamePatterns = NamePatterns(())
    ignore_attribute_names: NamePatterns = NamePatterns(())

    def parameter_names(self) -> NamePatterns:
        return self.ignore_names.joined(self.ignore_param_names)

    def attribute_names(self) -> NamePatterns:
        return self.ignore_names.joined(self.ignore_attribute_names)


class PathOverride(IgnoredNames):
    paths: PathPatterns
    allow: AllowedNames = AllowedNames(())
    deny: DeniedNames = DeniedNames(())
    ignore: Selectors = Selectors(())

    def matches(self, path: RelativePath) -> Verdict:
        # Empty means the file lies outside the tree the patterns are anchored to.
        if path.root == "":
            return Verdict(root=False)
        spec = pathspec.PathSpec.from_lines("gitignore", self.paths.root)
        return Verdict(spec.match_file(path.root))


class PathOverrides(RootModel[tuple[PathOverride, ...]]):
    def matching(self, path: RelativePath) -> "PathOverrides":
        return PathOverrides(
            tuple(Arr(self.root).filter(lambda override: override.matches(path)))
        )

    def allowed(self) -> AllowedNames:
        return AllowedNames(
            tuple(Arr(self.root).map(lambda override: override.allow.root).flatten())
        )

    def denied(self) -> DeniedNames:
        return DeniedNames(
            tuple(Arr(self.root).map(lambda override: override.deny.root).flatten())
        )

    def ignored(self) -> Selectors:
        return Selectors(
            tuple(Arr(self.root).map(lambda override: override.ignore.root).flatten())
        )

    def parameter_names(self) -> NamePatterns:
        return NamePatterns(
            tuple(
                Arr(self.root)
                .map(lambda override: override.parameter_names().root)
                .flatten()
            )
        )

    def attribute_names(self) -> NamePatterns:
        return NamePatterns(
            tuple(
                Arr(self.root)
                .map(lambda override: override.attribute_names().root)
                .flatten()
            )
        )


# Pydantic attributes an after-validator error to Settings, not to the entry that
# caused it, so the block's own patterns are the only way back to it.
def _validated_entry(override: PathOverride, denied: DeniedTypes) -> None:
    try:
        _validated(override.allow, override.deny, denied)
        validate_selectors(override.ignore)
    except ValueError as error:
        raise PerPathError(override.paths, error) from error


class Settings(IgnoredNames):
    allow: AllowedNames = AllowedNames(())
    deny: DeniedNames = DeniedNames(())
    exclude: PathPatterns = PathPatterns(())
    preset: Preset = Preset.DEFAULT
    # None, not an empty tuple: unset means the preset's rules, not no rules.
    select: Selectors | None = None
    extend_select: Selectors = Selectors(())
    ignore: Selectors = Selectors(())
    per_path: PathOverrides = PathOverrides(())

    @model_validator(mode="after")
    def _names_are_coherent(self) -> Self:
        _ = self._selection(PathOverrides(()))
        _validated(self.allow, self.deny, DeniedTypes.default())
        top_level = self._top_level()
        _ = (
            Arr(self.per_path.root)
            .map(lambda override: _validated_entry(override, top_level))
            .to_list()
        )
        return self

    def _selection(self, matching: PathOverrides) -> Selection:
        return selection(
            self.preset,
            self.select,
            self.extend_select,
            Selectors(self.ignore.root + matching.ignored().root),
        )

    def _top_level(self) -> DeniedTypes:
        return _adjusted(DeniedTypes.default(), self.allow, self.deny)

    def resolve(self, path: RelativePath) -> CheckConfig:
        matching = self.per_path.matching(path)
        return CheckConfig(
            selection=self._selection(matching),
            denied=_adjusted(self._top_level(), matching.allowed(), matching.denied()),
            ignored_parameter_names=self.parameter_names().joined(
                matching.parameter_names()
            ),
            ignored_attribute_names=self.attribute_names().joined(
                matching.attribute_names()
            ),
        )
