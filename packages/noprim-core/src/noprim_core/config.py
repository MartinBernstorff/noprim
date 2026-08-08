from functools import cached_property

import pathspec
from iterpy import Arr
from pydantic import BaseModel, Field, RootModel

from noprim_core.annotations import TypeNames
from noprim_core.rules.code import Selection
from noprim_core.site import ClassChain, Qualname
from noprim_types.verdict import Verdict


class NameSet(RootModel[frozenset[str]]):
    def matches(self, names: TypeNames) -> Verdict:
        return Verdict(len(names.root & self.root) > 0)


class DeniedTypes(NameSet):
    @classmethod
    def default(cls) -> "DeniedTypes":
        return cls(
            frozenset(
                {
                    "int",
                    "str",
                    "float",
                    "bool",
                    "bytes",
                    "bytearray",
                    "complex",
                    "Path",
                    "PurePath",
                    "UUID",
                    "datetime",
                    "date",
                    "time",
                    "timedelta",
                    "Decimal",
                    "Fraction",
                    "list",
                    "dict",
                    "set",
                    "frozenset",
                    "tuple",
                }
            )
        )


class TopTypes(NameSet):
    @classmethod
    def default(cls) -> "TopTypes":
        return cls(frozenset({"Any", "object"}))


class NamePatterns(RootModel[tuple[str, ...]]):
    # Asked once per violation rather than once per file, so compiling every time
    # would put pathspec's parser on the hot path.
    @cached_property
    def _spec(self) -> pathspec.PathSpec[pathspec.pattern.Pattern]:
        return pathspec.PathSpec.from_lines("gitignore", self.root)

    def matches(self, name: Qualname) -> Verdict:
        return Verdict(self._spec.match_file(name.root))

    def matches_any(self, names: ClassChain) -> Verdict:
        return Verdict.any(Arr(names.root).map(self.matches))

    def joined(self, other: "NamePatterns") -> "NamePatterns":
        return NamePatterns(self.root + other.root)


class CheckConfig(BaseModel):
    # Required: which rules run is the caller's decision, not a default frozen here.
    selection: Selection
    denied: DeniedTypes = Field(default_factory=DeniedTypes.default)
    # Separate from the deny-list: a top type says the type is unknown rather than
    # too narrow, so allowing one of them is a different decision.
    top_types: TopTypes = Field(default_factory=TopTypes.default)
    ignored_parameter_names: NamePatterns = NamePatterns(())
    ignored_attribute_names: NamePatterns = NamePatterns(())
    ignored_inner_classes: NamePatterns = NamePatterns(())
    # Typer reads a command's annotations to build the command line, so its parameters
    # are not the author's to choose.
    exempt_typer_args: Verdict = Verdict(root=True)
