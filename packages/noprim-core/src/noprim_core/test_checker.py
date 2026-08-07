from noprim_core.checker import Filename, SourceCode, check_source


def test_flags_primitive_parameter() -> None:
    violations = check_source(
        SourceCode("def greet(name: str) -> None: ...\n"), Filename("a.py")
    )
    assert [v.parameter for v in violations] == ["name"]
    assert violations[0].annotation == "str"


def test_ignores_non_primitive_parameter() -> None:
    violations = check_source(
        SourceCode("def greet(name: Name) -> None: ...\n"), Filename("a.py")
    )
    assert list(violations) == []


def test_flags_keyword_only_and_async() -> None:
    violations = check_source(
        SourceCode("async def f(*, count: int) -> None: ...\n"), Filename("a.py")
    )
    assert [v.parameter for v in violations] == ["count"]
