import pytest
from pydantic import ValidationError

from noprim_types.strings import NonBlankString


@pytest.mark.parametrize("given", ["", " ", "\t", "\n  \n"], ids=repr)
def test_rejects_a_blank_string(given: str) -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        _ = NonBlankString(given)


@pytest.mark.parametrize("given", ["a", " padded ", "two words"], ids=repr)
def test_keeps_a_non_blank_string_verbatim(given: str) -> None:
    assert NonBlankString(given).root == given
