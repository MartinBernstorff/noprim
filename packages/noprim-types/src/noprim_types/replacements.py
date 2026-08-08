from pydantic import ConfigDict, RootModel


class TypeName(RootModel[str]):
    # Hashed as a replacement table key.
    model_config = ConfigDict(frozen=True)


class Replacements(RootModel[tuple[TypeName, ...]]):
    pass


class ReplacementTable(RootModel[dict[TypeName, Replacements]]):
    @property
    def covered(self) -> frozenset[TypeName]:
        return frozenset(self.root)

    def suggestions_for(self, name: TypeName) -> Replacements:
        return self.root.get(name, Replacements(()))

    @classmethod
    def default(cls) -> "ReplacementTable":
        recommended = {
            "bool": ("Verdict",),
            "int": ("PositiveInt", "NonNegativeInt", "RootModel[int]"),
            "float": ("PositiveFloat", "FiniteFloat", "RootModel[float]"),
            "str": ("NonBlankString", "SecretStr", "RootModel[str]"),
            "bytes": ("Base64Bytes", "RootModel[bytes]"),
            "bytearray": ("RootModel[bytearray]",),
            "complex": ("RootModel[complex]",),
            "Path": ("DirectoryPath", "FilePath", "NewPath", "EnsuredDir"),
            "PurePath": ("DirectoryPath", "FilePath", "RootModel[PurePath]"),
            "UUID": ("UUID4", "RootModel[UUID]"),
            "datetime": (
                "AwareDatetime",
                "PastDatetime",
                "FutureDatetime",
                "RootModel[datetime]",
            ),
            "date": ("PastDate", "FutureDate", "RootModel[date]"),
            "time": ("RootModel[time]",),
            "timedelta": ("RootModel[timedelta]",),
            "Decimal": ("RootModel[Decimal]",),
            "Fraction": ("RootModel[Fraction]",),
            "list": ("RootModel[list[T]]",),
            "dict": ("RootModel[dict[K, V]]",),
            "set": ("RootModel[set[T]]",),
            "frozenset": ("RootModel[frozenset[T]]",),
            "tuple": ("RootModel[tuple[T, ...]]",),
        }
        return cls(
            {
                TypeName(denied): Replacements(tuple(TypeName(n) for n in names))
                for denied, names in recommended.items()
            }
        )
