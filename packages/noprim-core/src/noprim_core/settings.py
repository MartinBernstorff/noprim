from typing import Self

import pathspec
from iterpy import Arr
from pydantic import BaseModel, ConfigDict, RootModel, model_validator

from noprim_core.checker import (
    CheckConfig,
    DeniedTypes,
    IgnoredNames,
    TopTypes,
    Verdict,
)


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
            f"allow of a type governed by top-types: {', '.join(names.root)}. "
            "Drop top-types instead; the rule is all or nothing."
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


class FieldName(RootModel[str]):
    pass


def _to_kebab(name: FieldName) -> FieldName:
    return FieldName(name.root.replace("_", "-"))


# pydantic fixes this signature, so the primitive cannot be wrapped.
def _alias(name: str) -> str:  # noprim: ignore
    return _to_kebab(FieldName(name)).root


_SCHEMA = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=_alias)


class PathOverride(BaseModel):
    model_config = _SCHEMA

    paths: PathPatterns
    allow: AllowedNames = AllowedNames(())
    deny: DeniedNames = DeniedNames(())

    def matches(self, path: RelativePath) -> Verdict:
        # Empty means the file lies outside the tree the patterns are anchored to.
        if path.root == "":
            return Verdict(root=False)
        spec = pathspec.PathSpec.from_lines("gitignore", self.paths.root)
        return Verdict(spec.match_file(path.root))


class Settings(BaseModel):
    model_config = _SCHEMA

    allow: AllowedNames = AllowedNames(())
    deny: DeniedNames = DeniedNames(())
    exclude: PathPatterns = PathPatterns(())
    ignore_names: IgnoredNames = IgnoredNames(frozenset())
    check_predicates: Verdict = Verdict(root=False)
    top_types: Verdict = Verdict(root=False)
    per_path: tuple[PathOverride, ...] = ()

    @model_validator(mode="after")
    def _names_are_coherent(self) -> Self:
        _validated(self.allow, self.deny, DeniedTypes.default())
        top_level = self._top_level()
        _ = (
            Arr(self.per_path)
            .map(lambda o: _validated(o.allow, o.deny, top_level))
            .to_list()
        )
        return self

    def _top_level(self) -> DeniedTypes:
        return _adjusted(DeniedTypes.default(), self.allow, self.deny)

    def resolve(self, path: RelativePath) -> CheckConfig:
        top_level = self._top_level()
        matching = (
            Arr(self.per_path)
            .filter(lambda override: bool(override.matches(path)))
            .to_list()
        )
        return CheckConfig(
            denied=_adjusted(
                top_level,
                AllowedNames(
                    tuple(Arr(matching).map(lambda o: o.allow.root).flatten())
                ),
                DeniedNames(tuple(Arr(matching).map(lambda o: o.deny.root).flatten())),
            ),
            check_predicates=self.check_predicates,
            ignored_names=self.ignore_names,
            top_types=self.top_types,
        )
