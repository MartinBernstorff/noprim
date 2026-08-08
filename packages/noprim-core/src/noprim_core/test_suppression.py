import pytest
from iterpy import Arr

from noprim_core.annotations import AnnotationText
from noprim_core.config import NamePatterns
from noprim_core.rules.code import RuleCode
from noprim_core.site import (
    ColumnNumber,
    Filename,
    LineNumber,
    Qualname,
    Surface,
)
from noprim_core.source import SourceCode
from noprim_core.suppression import (
    IgnoredFile,
    IgnoredLines,
    PytestOwned,
    SuppressionOutcome,
    SuppressionReason,
    Suppressions,
    tokens_in,
)
from noprim_core.violation import Violation


def _violation(
    qualname: Qualname, line: LineNumber, code: RuleCode, surface: Surface
) -> Violation:
    return Violation(
        filename=Filename("a.py"),
        code=code,
        line=line,
        column=ColumnNumber(1),
        surface=surface,
        qualname=qualname,
        annotation=AnnotationText("str"),
    )


def _parameter(qualname: Qualname, line: LineNumber) -> Violation:
    return _violation(qualname, line, RuleCode("NOPRIM001"), Surface.PARAMETER)


def _reasons(outcome: SuppressionOutcome) -> Arr[SuppressionReason]:
    return Arr(outcome.suppressed).map(lambda suppressed: suppressed.reason)


def test_reports_a_violation_nothing_suppresses() -> None:
    outcome = Suppressions().apply(Arr([_parameter(Qualname("f.x"), LineNumber(1))]))

    assert [v.qualname.root for v in outcome.reported] == ["f.x"]
    assert outcome.suppressed == ()


@pytest.mark.parametrize(
    ("comment", "code", "expected"),
    [
        ("# noprim: ignore", "NOPRIM001", [SuppressionReason.COMMENT]),
        ("# noprim: ignore", "NOPRIM002", [SuppressionReason.COMMENT]),
        ("# noprim: ignore[NOPRIM002]", "NOPRIM002", [SuppressionReason.COMMENT]),
        ("# noprim: ignore[NOPRIM002]", "NOPRIM001", []),
        (
            "# noprim: ignore[NOPRIM001, NOPRIM002]",
            "NOPRIM002",
            [SuppressionReason.COMMENT],
        ),
        ("# noprim: ignore[NOPRIM001,NOPRIM002]", "NOPRIM003", []),
        # Brackets narrow the suppression, so empty brackets narrow it to nothing.
        ("# noprim: ignore[]", "NOPRIM001", []),
        (
            "# type: ignore  # noprim: ignore[NOPRIM001]",
            "NOPRIM001",
            [SuppressionReason.COMMENT],
        ),
        ("# noprim: ignore[NOPRIM001]  # legacy", "NOPRIM001", []),
        ("# noqa", "NOPRIM001", []),
    ],
)
def test_a_comment_suppresses_the_codes_it_names(
    comment: str, code: str, expected: list[SuppressionReason]
) -> None:
    suppressions = Suppressions(
        lines=IgnoredLines.parse(tokens_in(SourceCode(f"x = 1  {comment}\n")))
    )

    outcome = suppressions.apply(
        Arr(
            [
                _violation(
                    Qualname("f.x"),
                    LineNumber(1),
                    RuleCode(code),
                    Surface.PARAMETER,
                )
            ]
        )
    )

    assert _reasons(outcome).to_list() == expected


@pytest.mark.parametrize(
    ("source", "code", "expected"),
    [
        ("# noprim: ignore-file\n", "NOPRIM001", [SuppressionReason.FILE_COMMENT]),
        (
            "#!/usr/bin/env python\n# noprim: ignore-file\n",
            "NOPRIM001",
            [SuppressionReason.FILE_COMMENT],
        ),
        (
            "# noprim: ignore-file[NOPRIM002, NOPRIM003]\n",
            "NOPRIM002",
            [SuppressionReason.FILE_COMMENT],
        ),
        ("# noprim: ignore-file[NOPRIM002, NOPRIM003]\n", "NOPRIM001", []),
        (
            "# noprim: ignore-file[NOPRIM002]\n# noprim: ignore-file[NOPRIM003]\n",
            "NOPRIM003",
            [SuppressionReason.FILE_COMMENT],
        ),
        (
            "# noprim: ignore-file[NOPRIM002]\n# noprim: ignore-file[NOPRIM003]\n",
            "NOPRIM001",
            [],
        ),
        ("# noprim: ignore-file[]\n", "NOPRIM001", []),
        # A line-level comment is not a file-level one, and vice versa.
        ("# noprim: ignore\n", "NOPRIM001", []),
        ("x = 1\n# noprim: ignore-file\n", "NOPRIM001", []),
        ('"""Docstring."""\n# noprim: ignore-file\n', "NOPRIM001", []),
        ("# noprim: ignore-file  # legacy\n", "NOPRIM001", []),
    ],
)
def test_a_leading_comment_suppresses_the_whole_file(
    source: str, code: str, expected: list[SuppressionReason]
) -> None:
    suppressions = Suppressions(file=IgnoredFile.parse(tokens_in(SourceCode(source))))

    outcome = suppressions.apply(
        Arr(
            [
                _violation(
                    Qualname("f.x"), LineNumber(9), RuleCode(code), Surface.PARAMETER
                )
            ]
        )
    )

    assert _reasons(outcome).to_list() == expected


def test_a_comment_suppresses_only_its_own_line() -> None:
    suppressions = Suppressions(
        lines=IgnoredLines.parse(
            tokens_in(SourceCode("x = 1  # noprim: ignore\ny = 2\n"))
        )
    )

    outcome = suppressions.apply(
        Arr(
            [
                _parameter(Qualname("f.x"), LineNumber(1)),
                _parameter(Qualname("f.y"), LineNumber(2)),
            ]
        )
    )

    assert [v.qualname.root for v in outcome.reported] == ["f.y"]
    assert _reasons(outcome).to_list() == [SuppressionReason.COMMENT]


@pytest.mark.parametrize(
    ("suppressions", "surface", "expected"),
    [
        (
            Suppressions(parameter_names=NamePatterns(("kwargs",))),
            Surface.PARAMETER,
            [SuppressionReason.IGNORED_NAME],
        ),
        (Suppressions(parameter_names=NamePatterns(("kwargs",))), Surface.RETURN, []),
        (
            Suppressions(parameter_names=NamePatterns(("kwargs",))),
            Surface.ATTRIBUTE,
            [],
        ),
        (
            Suppressions(attribute_names=NamePatterns(("kwargs",))),
            Surface.ATTRIBUTE,
            [SuppressionReason.IGNORED_NAME],
        ),
        (
            Suppressions(attribute_names=NamePatterns(("kwargs",))),
            Surface.PARAMETER,
            [],
        ),
    ],
)
def test_a_name_is_ignored_on_the_surface_it_names(
    suppressions: Suppressions, surface: Surface, expected: list[SuppressionReason]
) -> None:
    outcome = suppressions.apply(
        Arr(
            [
                _violation(
                    Qualname("f.kwargs"),
                    LineNumber(1),
                    RuleCode("NOPRIM001"),
                    surface,
                )
            ]
        )
    )

    assert _reasons(outcome).to_list() == expected


@pytest.mark.parametrize(
    ("pattern", "name", "expected"),
    [
        ("kwargs", "kwargs", [SuppressionReason.IGNORED_NAME]),
        ("kwargs", "kwargs_2", []),
        ("*_contains", "name_contains", [SuppressionReason.IGNORED_NAME]),
        ("is_*", "is_ready", [SuppressionReason.IGNORED_NAME]),
        ("is_*", "ready", []),
    ],
)
def test_an_ignored_name_matches_as_a_glob(
    pattern: str, name: str, expected: list[SuppressionReason]
) -> None:
    suppressions = Suppressions(parameter_names=NamePatterns((pattern,)))

    outcome = suppressions.apply(
        Arr([_parameter(Qualname(f"f.{name}"), LineNumber(1))])
    )

    assert _reasons(outcome).to_list() == expected


def test_pytest_owns_the_parameters_it_names() -> None:
    suppressions = Suppressions(
        pytest_owned=PytestOwned(frozenset({Qualname("test_walks.tmp_path")}))
    )

    outcome = suppressions.apply(
        Arr(
            [
                _parameter(Qualname("test_walks.tmp_path"), LineNumber(1)),
                _violation(
                    Qualname("test_walks"),
                    LineNumber(1),
                    RuleCode("NOPRIM002"),
                    Surface.RETURN,
                ),
            ]
        )
    )

    assert [v.qualname.root for v in outcome.reported] == ["test_walks"]
    assert _reasons(outcome).to_list() == [SuppressionReason.PYTEST]
