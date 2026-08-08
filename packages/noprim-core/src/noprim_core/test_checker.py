import pytest
from iterpy import Arr

from noprim_core.checker import (
    CheckConfig,
    DeniedTypes,
    Filename,
    IgnoredNames,
    SourceCode,
    Surface,
    Verdict,
    Violation,
    check_source,
)


def _check(source: SourceCode, config: CheckConfig | None = None) -> Arr[Violation]:
    return check_source(
        source,
        Filename("a.py"),
        config if config is not None else CheckConfig(),
    )


def test_flags_primitive_parameter() -> None:
    violations = _check(SourceCode("def greet(name: str) -> None: ...\n"))
    assert [v.qualname.root for v in violations] == ["greet.name"]
    assert violations[0].annotation.root == "str"
    assert violations[0].surface == Surface.PARAMETER


def test_locates_violations_at_the_annotation() -> None:
    violations = _check(SourceCode("def greet(name: str) -> int: ...\n"))
    assert [(v.line.root, v.column.root) for v in violations] == [(1, 17), (1, 25)]


def test_ignores_non_primitive_parameter() -> None:
    assert list(_check(SourceCode("def greet(name: Name) -> None: ...\n"))) == []


def test_flags_keyword_only_and_async() -> None:
    violations = _check(SourceCode("async def f(*, count: int) -> None: ...\n"))
    assert [v.qualname.root for v in violations] == ["f.count"]


def test_flags_primitive_return() -> None:
    violations = _check(SourceCode("def f(x: Name) -> str: ...\n"))
    assert [(v.qualname.root, v.surface, v.annotation.root) for v in violations] == [
        ("f", Surface.RETURN, "str")
    ]


@pytest.mark.parametrize("annotation", ["bool", "builtins.bool", '"bool"'])
def test_exempts_predicate_return(annotation: str) -> None:
    source = f"def is_ready(x: Name) -> {annotation}: ...\n"
    assert list(_check(SourceCode(source))) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f(flag: bool) -> None: ...\n", ["f.flag"]),
        ("def f(x: Name) -> list[bool]: ...\n", ["f"]),
        ("def f(x: Name) -> bool | None: ...\n", ["f"]),
        ("class Thing:\n    ready: bool\n", ["Thing.ready"]),
    ],
)
def test_predicate_exemption_covers_only_bool_returns(
    source: str, expected: list[str]
) -> None:
    assert [v.qualname.root for v in _check(SourceCode(source))] == expected


def test_checking_predicates_reports_bool_returns() -> None:
    config = CheckConfig(check_predicates=Verdict(root=True))
    violations = _check(SourceCode("def is_ready(x: Name) -> bool: ...\n"), config)
    assert [(v.qualname.root, v.surface) for v in violations] == [
        ("is_ready", Surface.RETURN)
    ]


def test_qualifies_method_surfaces_with_their_class() -> None:
    violations = _check(
        SourceCode("class Thing:\n    def m(self, y: int) -> str: ...\n")
    )
    assert [(v.qualname.root, v.surface) for v in violations] == [
        ("Thing.m.y", Surface.PARAMETER),
        ("Thing.m", Surface.RETURN),
    ]


@pytest.mark.parametrize(
    ("base", "annotation"),
    [
        ("", "int"),
        ("", "ClassVar[int]"),
        ("TypedDict", "int"),
        ("NamedTuple", "int"),
        ("Protocol", "int"),
    ],
)
def test_flags_primitive_class_attribute(base: str, annotation: str) -> None:
    violations = _check(SourceCode(f"class Thing({base}):\n    count: {annotation}\n"))
    assert [(v.qualname.root, v.surface, v.annotation.root) for v in violations] == [
        ("Thing.count", Surface.ATTRIBUTE, annotation)
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
    assert list(_check(SourceCode(source))) == []


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
    ],
)
def test_default_deny_list(annotation: str) -> None:
    violations = _check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"))
    assert [v.annotation.root for v in violations] == [annotation]


@pytest.mark.parametrize("annotation", ["Any", "object"])
def test_top_types_are_not_denied_by_default(annotation: str) -> None:
    assert list(_check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"))) == []


@pytest.mark.parametrize("annotation", ["Any", "object", "dict[str, Any]"])
def test_top_types_reported_when_rule_is_enabled(annotation: str) -> None:
    config = CheckConfig(top_types=Verdict(root=True))
    violations = _check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"), config)
    assert [v.annotation.root for v in violations] == [annotation]


def test_top_types_rule_leaves_the_deny_list_alone() -> None:
    config = CheckConfig(
        denied=DeniedTypes(frozenset({"Name"})), top_types=Verdict(root=True)
    )
    violations = _check(
        SourceCode("def f(x: Name, y: Any, z: str) -> None: ...\n"), config
    )
    assert [v.qualname.root for v in violations] == ["f.x", "f.y"]


@pytest.mark.parametrize("annotation", ["datetime.datetime", "dt.datetime"])
def test_matches_on_last_dotted_segment(annotation: str) -> None:
    violations = _check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"))
    assert [v.annotation.root for v in violations] == [annotation]


@pytest.mark.parametrize(
    "source",
    [
        "def f(x: list[Name]) -> None: ...\n",
        "def f(x: dict[Name, Name]) -> None: ...\n",
        "def f(x: Name) -> None: ...\n",
        'def f(x: "Name") -> None: ...\n',
        "def f(x: Name): ...\n",
        "def f(x) -> None: ...\n",
        "T = TypeVar('T')\ndef f(x: T) -> T: ...\n",
        "class Color(Enum): ...\ndef f(x: Color) -> Color: ...\n",
    ],
)
def test_passes_clean_annotations(source: str) -> None:
    assert list(_check(SourceCode(source))) == []


@pytest.mark.parametrize(
    "annotation",
    [
        "list[str]",
        "dict[str, UserId]",
        "Callable[[Event], str]",
        "Annotated[str, Field(gt=0)]",
        "MyGeneric[str]",
        "list[list[dict[Name, str]]]",
    ],
)
def test_flags_nested_primitive_once_with_full_text(annotation: str) -> None:
    violations = _check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"))
    assert [(v.qualname.root, v.annotation.root) for v in violations] == [
        ("f.x", annotation)
    ]


@pytest.mark.parametrize(
    "annotation",
    ["str | None", "None | str", "Name | str", "list[Name] | str"],
)
def test_flags_primitives_inside_unions(annotation: str) -> None:
    violations = _check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"))
    assert [(v.qualname.root, v.annotation.root) for v in violations] == [
        ("f.x", annotation)
    ]


@pytest.mark.parametrize("annotation", ["Name | None", "Name | Other"])
def test_passes_unions_without_primitives(annotation: str) -> None:
    assert list(_check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"))) == []


@pytest.mark.parametrize(
    "annotation",
    ["Literal['a', 'b']", "typing.Literal[1, 2]", "dict[Name, Literal['a']]"],
)
def test_ignores_literal_arguments(annotation: str) -> None:
    assert list(_check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"))) == []


@pytest.mark.parametrize(
    "annotation", ['"str"', 'list["str"]', '"list[str]"', '"str | None"']
)
def test_parses_string_annotations(annotation: str) -> None:
    violations = _check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"))
    assert [v.qualname.root for v in violations] == ["f.x"]


@pytest.mark.parametrize("annotation", ['"not python!!"', '""', '"list["'])
def test_skips_unparseable_string_annotations(annotation: str) -> None:
    assert list(_check(SourceCode(f"def f(x: {annotation}) -> None: ...\n"))) == []


@pytest.mark.parametrize(
    "source",
    [
        'class Thing:\n    def m(self: "Thing") -> None: ...\n',
        'class Thing:\n    @classmethod\n    def m(cls: "type[Thing]") -> None: ...\n',
    ],
)
def test_exempts_self_and_cls(source: str) -> None:
    assert list(_check(SourceCode(source))) == []


@pytest.mark.parametrize(
    "source",
    [
        "class Thing:\n    def __init__(self, x: int) -> None: ...\n",
        "class Thing:\n    def __eq__(self, other: object) -> bool: ...\n",
    ],
)
def test_exempts_dunder_methods(source: str) -> None:
    assert list(_check(SourceCode(source))) == []


@pytest.mark.parametrize(
    "source",
    [
        "class Id(RootModel[str]):\n    def get(self, key: int) -> str: ...\n",
        "class Id(RootModel):\n    root: str\n",
    ],
)
def test_exempts_root_model_bodies(source: str) -> None:
    assert list(_check(SourceCode(source))) == []


@pytest.mark.parametrize(
    "source",
    [
        'UserId = NewType("UserId", str)\n',
        'class Thing:\n    UserId = NewType("UserId", str)\n',
    ],
)
def test_exempts_new_type_calls(source: str) -> None:
    assert list(_check(SourceCode(source))) == []


def test_exempts_overload_implementation() -> None:
    source = "@overload\ndef f(x: Name) -> Name: ...\ndef f(x: object) -> object: ...\n"
    assert list(_check(SourceCode(source))) == []


def test_reports_overload_stubs_only() -> None:
    violations = _check(
        SourceCode(
            "@overload\ndef f(x: int) -> str: ...\n"
            "@overload\ndef f(x: Name) -> Name: ...\n"
            "def f(x: object) -> object: ...\n"
        )
    )
    assert [(v.line.root, v.annotation.root) for v in violations] == [
        (2, "int"),
        (2, "str"),
    ]


@pytest.mark.parametrize("filename", ["test_thing.py", "thing_test.py"])
def test_exempts_parameters_of_test_functions(filename: str) -> None:
    violations = check_source(
        SourceCode(
            "def test_walks(tmp_path: Path, expected: list[str]) -> None: ...\n"
        ),
        Filename(filename),
        CheckConfig(),
    )
    assert list(violations) == []


@pytest.mark.parametrize(
    "decorator", ["@pytest.fixture", "@fixture", "@pytest.fixture(scope='session')"]
)
def test_exempts_parameters_of_fixtures(decorator: str) -> None:
    violations = check_source(
        SourceCode(f"{decorator}\ndef repo(tmp_path: Path) -> Repo: ...\n"),
        Filename("test_thing.py"),
        CheckConfig(),
    )
    assert list(violations) == []


@pytest.mark.parametrize(
    ("filename", "source"),
    [
        ("thing.py", "def test_walks(tmp_path: Path) -> None: ...\n"),
        ("thing.py", "@pytest.fixture\ndef repo(tmp_path: Path) -> Repo: ...\n"),
        ("test_thing.py", "def _helper(source: str) -> None: ...\n"),
        ("test_thing.py", "def test_walks(x: Name) -> str: ...\n"),
        ("test_thing.py", "@pytest.fixture\ndef repo() -> Path: ...\n"),
        ("contest_thing.py", "def test_walks(tmp_path: Path) -> None: ...\n"),
    ],
)
def test_exemption_covers_only_test_function_parameters(
    filename: str, source: str
) -> None:
    violations = check_source(SourceCode(source), Filename(filename), CheckConfig())
    assert len(list(violations)) == 1


def test_private_functions_still_report() -> None:
    violations = _check(SourceCode("def _f(x: int) -> None: ...\n"))
    assert [v.qualname.root for v in violations] == ["_f.x"]


def test_uses_configured_deny_list() -> None:
    config = CheckConfig(denied=DeniedTypes(frozenset({"Name"})))
    violations = _check(SourceCode("def f(x: Name, y: str) -> None: ...\n"), config)
    assert [v.qualname.root for v in violations] == ["f.x"]


def test_ignores_configured_symbol_names() -> None:
    config = CheckConfig(ignored_names=IgnoredNames(frozenset({"kwargs"})))
    violations = _check(
        SourceCode("def f(x: str, **kwargs: str) -> None: ...\n"), config
    )
    assert [v.qualname.root for v in violations] == ["f.x"]


def test_ignored_names_leave_return_types_alone() -> None:
    config = CheckConfig(ignored_names=IgnoredNames(frozenset({"size", "f"})))
    violations = _check(
        SourceCode("class Thing:\n    size: int\n\ndef f(y: Name) -> str: ...\n"),
        config,
    )
    assert [(v.qualname.root, v.surface) for v in violations] == [("f", Surface.RETURN)]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f(x: str) -> None: ...  # noprim: ignore\n", []),
        ("def f(x: Name) -> str:  # noprim: ignore\n    ...\n", []),
        ("class Thing:\n    count: int  # noprim: ignore\n", []),
        (
            "def f(  # noprim: ignore\n    x: str,\n) -> None: ...\n",
            ["f.x"],
        ),
        (
            "def f(  # noprim: ignore\n    x: str,  # noprim: ignore\n) -> str: ...\n",
            ["f"],
        ),
        ("def f(x: str) -> None: ...  # type: ignore  # noprim: ignore\n", []),
        ("def f(x: str) -> None: ...  # noprim: ignore[NOPRIM002]\n", ["f.x"]),
        ("def f(x: str) -> None: ...  # noprim: ignore  # legacy\n", ["f.x"]),
        ("def f(x: str) -> None: ...  # noqa\n", ["f.x"]),
    ],
)
def test_ignore_comment_suppresses_only_its_own_line(
    source: str, expected: list[str]
) -> None:
    assert [v.qualname.root for v in _check(SourceCode(source))] == expected
