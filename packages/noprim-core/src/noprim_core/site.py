from enum import StrEnum

from pydantic import BaseModel, ConfigDict, RootModel

from noprim_core.annotations import AnnotationText, TypeNames


class Filename(RootModel[str]):
    # Hashed as part of a baseline key.
    model_config = ConfigDict(frozen=True)


class Qualname(RootModel[str]):
    model_config = ConfigDict(frozen=True)

    def child(self, name: "Qualname") -> "Qualname":
        if self.root == "":
            return name
        return Qualname(f"{self.root}.{name.root}")

    def leaf(self) -> "Qualname":
        return Qualname(self.root.rsplit(".", 1)[-1])


class Surface(StrEnum):
    PARAMETER = "parameter"
    RETURN = "return"
    ATTRIBUTE = "attribute"


class LineNumber(RootModel[int]):
    pass


class ColumnNumber(RootModel[int]):
    pass


class Site(BaseModel):
    line: LineNumber
    column: ColumnNumber
    surface: Surface
    qualname: Qualname
    annotation: AnnotationText
    names: TypeNames
