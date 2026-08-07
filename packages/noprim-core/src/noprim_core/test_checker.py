import pytest
from iterpy import Arr

from noprim_core.checker import (
    CheckConfig,
    DeniedTypes,
    Filename,
    SourceCode,
    Surface,
    Violation,
    check_source,
)


def _check(source: str, config: CheckConfig | None = None) -> Arr[Violation]:
    return check_source(
        SourceCode(source),
        Filename("a.py"),
        config if config is not None else CheckConfig(),
    )


def test_flags_primitive_parameter() -> None:
    violations = _check("def greet(name: str) -> None: ...\n")
    assert [v.qualname for v in violations] == ["greet.name"]
    assert violations[0].annotation == "str"
    assert violations[0].surface == Surface.PARAMETER


def test_ignores_non_primitive_parameter() -> None:
    assert list(_check("def greet(name: Name) -> None: ...\n")) == []


def test_flags_keyword_only_and_async() -> None:
    violations = _check("async def f(*, count: int) -> None: ...\n")
    assert [v.qualname for v in violations] == ["f.count"]


def test_flags_primitive_return() -> None:
    violations = _check("def f(x: Name) -> bool: ...\n")
    assert [(v.qualname, v.surface, v.annotation) for v in violations] == [
        ("f", Surface.RETURN, "bool")
    ]


def test_qualifies_method_surfaces_with_their_class() -> None:
    violations = _check("class Thing:\n    def m(self, y: int) -> bool: ...\n")
    assert [(v.qualname, v.surface) for v in violations] == [
        ("Thing.m.y", Surface.PARAMETER),
        ("Thing.m", Surface.RETURN),
    ]


@pytest.mark.parametrize(
    ("base", "member"),
    [
        ("", "count: int"),
        ("", "count: ClassVar[int]"),
        ("TypedDict", "count: int"),
        ("NamedTuple", "count: int"),
        ("Protocol", "count: int"),
    ],
)
def test_flags_primitive_class_attribute(base: str, member: str) -> None:
    violations = _check(f"class Thing({base}):\n    {member}\n")
    assert [(v.qualname, v.surface, v.annotation) for v in violations] == [
        ("Thing.count", Surface.ATTRIBUTE, "int")
    ]


@pytest.mark.parametrize(
    "source",
    [
        "count: int = 1\n",
        "def f() -> None:\n    count: int = 1\n",
        "class Thing:\n    def f(self) -> None:\n        count: int = 1\n",
    ],
)
def test_ignores_annotations_outside_class_bodies(source: str) -> None:
    assert list(_check(source)) == []


@pytest.mark.parametrize(
    "annotation",
    [
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
        "Any",
        "object",
    ],
)
def test_default_deny_list(annotation: str) -> None:
    violations = _check(f"def f(x: {annotation}) -> None: ...\n")
    assert [v.annotation for v in violations] == [annotation]


@pytest.mark.parametrize("annotation", ["datetime.datetime", "dt.datetime"])
def test_matches_on_last_dotted_segment(annotation: str) -> None:
    violations = _check(f"def f(x: {annotation}) -> None: ...\n")
    assert [v.annotation for v in violations] == ["datetime"]


@pytest.mark.parametrize(
    "source",
    [
        "def f(x: list[Name]) -> None: ...\n",
        "def f(x: dict[Name, Name]) -> None: ...\n",
        "def f(x: Name) -> None: ...\n",
        "def f(x: Name): ...\n",
        "def f(x) -> None: ...\n",
        "T = TypeVar('T')\ndef f(x: T) -> T: ...\n",
        "class Color(Enum): ...\ndef f(x: Color) -> Color: ...\n",
    ],
)
def test_passes_clean_annotations(source: str) -> None:
    assert list(_check(source)) == []


def test_uses_configured_deny_list() -> None:
    config = CheckConfig(denied=DeniedTypes(frozenset({"Name"})))
    violations = _check("def f(x: Name, y: str) -> None: ...\n", config)
    assert [v.qualname for v in violations] == ["f.x"]
