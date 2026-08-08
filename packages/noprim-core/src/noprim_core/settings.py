from collections.abc import Callable
from typing import Self, TypeVar

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
from noprim_types.verdict import Verdict

# PEP 695 syntax would read better, but it is 3.12+ and the floor is 3.11.
_Gathered = TypeVar("_Gathered")


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


# The keys that name symbols rather than types, shared by the top level and by an
# override. ignore-names predates the split and stays the way to say both at once.
class NameKeys(BaseModel):
    model_config = _SCHEMA

    ignore_names: NamePatterns = NamePatterns(())
    ignore_param_names: NamePatterns = NamePatterns(())
    ignore_attribute_names: NamePatterns = NamePatterns(())
    ignore_inner_classes: NamePatterns = NamePatterns(())

    def parameter_names(self) -> NamePatterns:
        return self.ignore_names.joined(self.ignore_param_names)

    def attribute_names(self) -> NamePatterns:
        return self.ignore_names.joined(self.ignore_attribute_names)


class PathOverride(NameKeys):
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

    def _gathered(
        self, key: Callable[[PathOverride], tuple[_Gathered, ...]]
    ) -> tuple[_Gathered, ...]:
        return tuple(Arr(self.root).map(key).flatten())

    def allowed(self) -> AllowedNames:
        return AllowedNames(self._gathered(lambda override: override.allow.root))

    def denied(self) -> DeniedNames:
        return DeniedNames(self._gathered(lambda override: override.deny.root))

    def ignored(self) -> Selectors:
        return Selectors(self._gathered(lambda override: override.ignore.root))

    def parameter_names(self) -> NamePatterns:
        return NamePatterns(
            self._gathered(lambda override: override.parameter_names().root)
        )

    def attribute_names(self) -> NamePatterns:
        return NamePatterns(
            self._gathered(lambda override: override.attribute_names().root)
        )

    def inner_classes(self) -> NamePatterns:
        return NamePatterns(
            self._gathered(lambda override: override.ignore_inner_classes.root)
        )


# Pydantic attributes an after-validator error to Settings, not to the entry that
# caused it, so the block's own patterns are the only way back to it.
def _validated_entry(override: PathOverride, denied: DeniedTypes) -> None:
    try:
        _validated(override.allow, override.deny, denied)
        validate_selectors(override.ignore)
    except ValueError as error:
        raise PerPathError(override.paths, error) from error


class Settings(NameKeys):
    allow: AllowedNames = AllowedNames(())
    deny: DeniedNames = DeniedNames(())
    exclude: PathPatterns = PathPatterns(())
    # Every rule: an unconfigured run says everything it has to say, and a codebase
    # narrows from there rather than discovering later that a rule existed.
    preset: Preset = Preset.ALL
    # None, not an empty tuple: unset means the preset's rules, not no rules.
    select: Selectors | None = None
    extend_select: Selectors = Selectors(())
    ignore: Selectors = Selectors(())
    # Off, like every other exemption a key controls: hiding a violation is the
    # codebase's decision to make, not one it inherits.
    exempt_typer_args: Verdict = Verdict(root=False)
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
            ignored_inner_classes=self.ignore_inner_classes.joined(
                matching.inner_classes()
            ),
            exempt_typer_args=self.exempt_typer_args,
        )
