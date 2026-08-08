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


class ClassChain(RootModel[tuple[Qualname, ...]]):
    def child(self, name: Qualname) -> "ClassChain":
        return ClassChain((*self.root, name))

    # The outermost class is the one the module declares; every class below it is inner.
    def inner(self) -> "ClassChain":
        return ClassChain(self.root[1:])


class Owner(StrEnum):
    # Who chose the annotation: pytest dictates the signature of tests and fixtures,
    # and typer reads a command's parameters to build the command line.
    AUTHOR = "author"
    PYTEST = "pytest"
    TYPER = "typer"


class Surface(StrEnum):
    PARAMETER = "parameter"
    RETURN = "return"
    ATTRIBUTE = "attribute"


class LineNumber(RootModel[int]):
    # Used as a key when looking up the suppressions written on a line.
    model_config = ConfigDict(frozen=True)


class ColumnNumber(RootModel[int]):
    pass


class Site(BaseModel):
    line: LineNumber
    column: ColumnNumber
    surface: Surface
    qualname: Qualname
    annotation: AnnotationText
    names: TypeNames
    owner: Owner = Owner.AUTHOR
    enclosing_classes: ClassChain = ClassChain(())
