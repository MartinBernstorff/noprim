from pydantic import RootModel, field_validator


class BlankStringError(ValueError):
    def __init__(self) -> None:
        super().__init__("must not be blank")


class NonBlankString(RootModel[str]):
    @field_validator("root")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise BlankStringError
        # Stripping would make NonBlankString(x).root != x; blankness is the only claim.
        return value
