from pydantic import BaseModel, Field, RootModel

from noprim_core.annotations import TypeNames
from noprim_core.rules.code import Selection
from noprim_core.site import Qualname
from noprim_core.verdict import Verdict


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


class IgnoredNames(RootModel[frozenset[str]]):
    def contains(self, name: Qualname) -> Verdict:
        return Verdict(name.root in self.root)


class CheckConfig(BaseModel):
    # Required: which rules run is the caller's decision, not a default frozen here.
    selection: Selection
    denied: DeniedTypes = Field(default_factory=DeniedTypes.default)
    # Separate from the deny-list: a top type says the type is unknown rather than
    # too narrow, so allowing one of them is a different decision.
    top_types: TopTypes = Field(default_factory=TopTypes.default)
    ignored_names: IgnoredNames = IgnoredNames(frozenset())
