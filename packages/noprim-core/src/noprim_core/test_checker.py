import pytest
from iterpy import Arr

from noprim_core.checker import check_source
from noprim_core.config import CheckConfig, NamePatterns
from noprim_core.rules.code import Selector, Selectors
from noprim_core.rules.preset import Preset
from noprim_core.rules.registry import default_selection, selection
from noprim_core.site import Filename, Surface
from noprim_core.source import SourceCode
from noprim_core.violation import Violation
from noprim_types.verdict import Verdict


def _config() -> CheckConfig:
    return CheckConfig(selection=default_selection())


def _selecting(codes: Selectors) -> CheckConfig:
    return CheckConfig(
        selection=selection(Preset.DEFAULT, codes, Selectors(()), Selectors(()))
    )


def _check(source: SourceCode, config: CheckConfig | None = None) -> Arr[Violation]:
    return _reported(
        source, Filename("a.py"), config if config is not None else _config()
    )


def _reported(
    source: SourceCode, filename: Filename, config: CheckConfig
) -> Arr[Violation]:
    return Arr(check_source(source, filename, config).reported)


def test_flags_primitive_parameter() -> None:
    violations = _check(SourceCode("def greet(name: str) -> None: ...\n"))
    assert [v.qualname.root for v in violations] == ["greet.name"]
    assert violations[0].annotation.root == "str"
    assert violations[0].surface == Surface.PARAMETER


def test_stamps_each_violation_with_the_rule_that_fired() -> None:
    violations = _check(
        SourceCode("class Thing:\n    def m(self, y: int) -> str:\n        ...\n")
    )
    assert [v.code.root for v in violations] == ["NOPRIM001", "NOPRIM002"]


def test_an_attribute_carries_the_attribute_rule() -> None:
    violations = _check(SourceCode("class Thing:\n    count: int\n"))
    assert [v.code.root for v in violations] == ["NOPRIM003"]


def test_a_deselected_rule_stops_reporting() -> None:
    config = _selecting(Selectors((Selector("NOPRIM001"),)))
    violations = _check(SourceCode("def f(x: int) -> str: ...\n"), config)
    assert [v.qualname.root for v in violations] == ["f.x"]


def test_two_rules_can_fire_on_one_annotation() -> None:
    config = _selecting(Selectors((Selector("NOPRIM"),)))
    violations = _check(SourceCode("def f(x: dict[str, Any]) -> None: ...\n"), config)
    assert [v.code.root for v in violations] == ["NOPRIM001", "NOPRIM004"]


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


def test_predicates_are_not_reported_by_default() -> None:
    assert list(_check(SourceCode("def is_ready(x: Name) -> bool: ...\n"))) == []


def test_selecting_the_predicate_rule_reports_bool_returns() -> None:
    config = _selecting(Selectors((Selector("NOPRIM007"),)))
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
    "source",
    [
        "def f(x: Name) -> None: ...\n",
        "def f(x: Name): ...\n",
        "def f(x) -> None: ...\n",
    ],
)
def test_passes_clean_annotations(source: str) -> None:
    assert list(_check(SourceCode(source))) == []


def test_reports_the_whole_annotation_not_the_primitive_inside_it() -> None:
    violations = _check(
        SourceCode("def f(x: list[list[dict[Name, str]]]) -> None: ...\n")
    )
    assert [(v.qualname.root, v.annotation.root) for v in violations] == [
        ("f.x", "list[list[dict[Name, str]]]")
    ]


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


@pytest.mark.parametrize(
    "source",
    [
        "class Thing:\n    @override\n    def save(self, force: bool) -> str: ...\n",
        "class Thing:\n    @typing.override\n    def save(self, force: bool) -> str: ...\n",
        "class Thing:\n    @typing_extensions.override\n    def save(self, force: bool) -> str: ...\n",
        "class Thing:\n    @cache\n    @override\n    def save(self, force: bool) -> str: ...\n",
    ],
)
def test_exempts_overriding_methods(source: str) -> None:
    assert list(_check(SourceCode(source))) == []


@pytest.mark.parametrize(
    "source",
    [
        "class Thing:\n    def save(self, force: bool) -> str: ...\n",
        "class Thing:\n    @override_settings(DEBUG=True)\n    def save(self, force: bool) -> str: ...\n",
    ],
)
def test_checks_methods_without_the_override_decorator(source: str) -> None:
    assert [v.annotation.root for v in _check(SourceCode(source))] == ["bool", "str"]


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
    violations = _reported(
        SourceCode(
            "def test_walks(tmp_path: Path, expected: list[str]) -> None: ...\n"
        ),
        Filename(filename),
        _config(),
    )
    assert list(violations) == []


@pytest.mark.parametrize(
    "decorator", ["@pytest.fixture", "@fixture", "@pytest.fixture(scope='session')"]
)
def test_exempts_parameters_of_fixtures(decorator: str) -> None:
    violations = _reported(
        SourceCode(f"{decorator}\ndef repo(tmp_path: Path) -> Repo: ...\n"),
        Filename("test_thing.py"),
        _config(),
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
    violations = _reported(SourceCode(source), Filename(filename), _config())
    assert len(list(violations)) == 1


def test_private_functions_still_report() -> None:
    violations = _check(SourceCode("def _f(x: int) -> None: ...\n"))
    assert [v.qualname.root for v in violations] == ["_f.x"]


def test_ignores_configured_symbol_names() -> None:
    config = CheckConfig(
        selection=default_selection(),
        ignored_parameter_names=NamePatterns(("kwargs",)),
    )
    violations = _check(
        SourceCode("def f(x: str, **kwargs: str) -> None: ...\n"), config
    )
    assert [v.qualname.root for v in violations] == ["f.x"]


def test_ignored_names_leave_return_types_alone() -> None:
    config = CheckConfig(
        selection=default_selection(),
        ignored_parameter_names=NamePatterns(("size", "f")),
        ignored_attribute_names=NamePatterns(("size", "f")),
    )
    violations = _check(
        SourceCode("class Thing:\n    size: int\n\ndef f(y: Name) -> str: ...\n"),
        config,
    )
    assert [(v.qualname.root, v.surface) for v in violations] == [("f", Surface.RETURN)]


def test_an_ignored_name_covers_every_rule_on_that_surface() -> None:
    config = CheckConfig(
        selection=selection(
            Preset.ALL, None, Selectors(()), Selectors((Selector("NOPRIM007"),))
        ),
        ignored_parameter_names=NamePatterns(("x",)),
    )
    violations = _check(SourceCode("def f(x: Any, y: Any) -> None: ...\n"), config)
    assert [(v.qualname.root, v.code.root) for v in violations] == [
        ("f.y", "NOPRIM004")
    ]


def test_a_parameter_and_an_attribute_of_one_name_are_ignored_apart() -> None:
    config = CheckConfig(
        selection=default_selection(),
        ignored_parameter_names=NamePatterns(("value",)),
    )
    violations = _check(
        SourceCode("class Thing:\n    value: int\n\ndef f(value: str) -> None: ...\n"),
        config,
    )
    assert [(v.qualname.root, v.surface) for v in violations] == [
        ("Thing.value", Surface.ATTRIBUTE)
    ]


_FILTER = """\
class Filter:
    name: str

    class Meta:
        fields: list[str] = []
"""


def _ignoring_meta() -> CheckConfig:
    return CheckConfig(
        selection=default_selection(), ignored_inner_classes=NamePatterns(("Meta",))
    )


def test_ignores_the_body_of_a_configured_inner_class() -> None:
    violations = _check(SourceCode(_FILTER), _ignoring_meta())
    assert [v.qualname.root for v in violations] == ["Filter.name"]


def test_an_inner_class_pattern_takes_a_glob() -> None:
    config = CheckConfig(
        selection=default_selection(), ignored_inner_classes=NamePatterns(("*Meta",))
    )
    violations = _check(
        SourceCode("class F:\n    class FilterMeta:\n        fields: list[str] = []\n"),
        config,
    )
    assert [v.qualname.root for v in violations] == []


def test_an_ignored_inner_class_is_suppressed_rather_than_never_found() -> None:
    outcome = check_source(SourceCode(_FILTER), Filename("a.py"), _ignoring_meta())
    assert [(s.violation.qualname.root, str(s.reason)) for s in outcome.suppressed] == [
        ("Filter.Meta.fields", "inner-class")
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("class Meta:\n    fields: list[str] = []\n", ["Meta.fields"]),
        ("class F:\n    class Meta:\n        fields: list[str] = []\n", []),
        (
            "class F:\n    class Inner:\n        class Meta:\n            f: list[str] = []\n",
            [],
        ),
        (
            "class F:\n    class Other:\n        fields: list[str] = []\n",
            ["F.Other.fields"],
        ),
        ("class F:\n    class Meta:\n        def m(self, x: int) -> None: ...\n", []),
        (
            "def build() -> None:\n    class Meta:\n        fields: list[str] = []\n",
            ["build.Meta.fields"],
        ),
    ],
)
def test_only_a_nested_class_of_that_name_is_ignored(
    source: str, expected: list[str]
) -> None:
    violations = _check(SourceCode(source), _ignoring_meta())
    assert [v.qualname.root for v in violations] == expected


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
        ("def f(x: str) -> str: ...  # noprim: ignore[NOPRIM002]\n", ["f.x"]),
        ("def f(x: str) -> str: ...  # noprim: ignore[NOPRIM001, NOPRIM002]\n", []),
        ("def f(x: str) -> str: ...  # noprim: ignore[NOPRIM003]\n", ["f.x", "f"]),
        ("def f(x: str) -> None: ...  # noprim: ignore  # legacy\n", ["f.x"]),
        ("def f(x: str) -> None: ...  # noqa\n", ["f.x"]),
    ],
)
def test_ignore_comment_suppresses_only_its_own_line(
    source: str, expected: list[str]
) -> None:
    assert [v.qualname.root for v in _check(SourceCode(source))] == expected


@pytest.mark.parametrize(
    ("source", "reasons"),
    [
        ("def f(x: str) -> None: ...  # noprim: ignore\n", ["comment"]),
        ("def f(x: str) -> None: ...\n", []),
    ],
)
def test_a_suppressed_violation_says_why_it_was_not_reported(
    source: str, reasons: list[str]
) -> None:
    outcome = check_source(SourceCode(source), Filename("a.py"), _config())

    assert [str(s.reason) for s in outcome.suppressed] == reasons


def test_pytest_parameters_are_suppressed_rather_than_never_found() -> None:
    outcome = check_source(
        SourceCode("def test_walks(tmp_path: Path) -> None: ...\n"),
        Filename("test_thing.py"),
        _config(),
    )

    assert [s.violation.qualname.root for s in outcome.suppressed] == [
        "test_walks.tmp_path"
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("@app.command()\ndef ship(name: str) -> None: ...\n", []),
        ("@app.command()\ndef ship(force: bool = False) -> None: ...\n", []),
        (
            "@app.command()\ndef ship(name: Annotated[str, typer.Option()]) -> None: ...\n",
            [],
        ),
        ("@app.callback()\ndef cli(verbose: bool = False) -> None: ...\n", []),
        ("@cli.command('ship')\ndef ship(name: str) -> None: ...\n", []),
        ("@command_runner.run()\ndef ship(name: str) -> None: ...\n", ["ship.name"]),
        ("@command\ndef ship(name: str) -> None: ...\n", ["ship.name"]),
        ("@app.command()\ndef ship() -> str: ...\n", ["ship"]),
        (
            (
                "@app.command()\ndef ship(name: str) -> None:\n"
                "    def inner(raw: str) -> None: ...\n"
            ),
            ["ship.inner.raw"],
        ),
        ("def _helper(name: str) -> None: ...\n", ["_helper.name"]),
    ],
)
def test_the_typer_exemption_covers_only_a_command_s_parameters(
    source: str, expected: list[str]
) -> None:
    assert [v.qualname.root for v in _check(SourceCode(source))] == expected


def test_typer_parameters_report_when_the_exemption_is_off() -> None:
    config = CheckConfig(
        selection=default_selection(), exempt_typer_args=Verdict(root=False)
    )
    violations = _check(
        SourceCode("@app.command()\ndef ship(name: str) -> None: ...\n"), config
    )
    assert [v.qualname.root for v in violations] == ["ship.name"]


def test_typer_parameters_are_suppressed_rather_than_never_found() -> None:
    outcome = check_source(
        SourceCode("@app.command()\ndef ship(name: str) -> None: ...\n"),
        Filename("a.py"),
        _config(),
    )

    assert [(s.violation.qualname.root, str(s.reason)) for s in outcome.suppressed] == [
        ("ship.name", "typer")
    ]
