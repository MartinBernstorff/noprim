from noprim_core.baseline import (
    Baseline,
    BaselineKey,
    KeyedViolation,
    KeyedViolations,
    PrunableFiles,
    apply_baseline,
)
from noprim_core.checker import Surface, Violation


def _violation(qualname: str, line: int = 1) -> Violation:
    return Violation(
        filename="/abs/src/a.py",
        line=line,
        column=1,
        surface=Surface.PARAMETER,
        qualname=qualname,
        annotation="str",
    )


def _key(qualname: str) -> BaselineKey:
    return BaselineKey(
        filename="src/a.py",
        surface=Surface.PARAMETER,
        qualname=qualname,
        annotation="str",
    )


def _keyed(*qualnames: str) -> KeyedViolations:
    return KeyedViolations(
        tuple(
            KeyedViolation(key=_key(qualname), violation=_violation(qualname))
            for qualname in qualnames
        )
    )


def test_reports_violations_absent_from_the_baseline() -> None:
    outcome = apply_baseline(
        _keyed("f.a", "f.b"),
        Baseline(frozenset({_key("f.a")})),
        PrunableFiles(frozenset({"src/a.py"})),
    )

    assert [v.qualname for v in outcome.reported] == ["f.b"]
    assert [v.qualname for v in outcome.suppressed] == ["f.a"]


def test_treats_an_unmatched_entry_in_a_walked_file_as_stale() -> None:
    outcome = apply_baseline(
        _keyed("f.a"),
        Baseline(frozenset({_key("f.a"), _key("f.gone")})),
        PrunableFiles(frozenset({"src/a.py"})),
    )

    assert outcome.stale == (_key("f.gone"),)


def test_keeps_entries_for_files_this_run_never_walked() -> None:
    elsewhere = BaselineKey(
        filename="src/b.py",
        surface=Surface.PARAMETER,
        qualname="g.b",
        annotation="str",
    )

    outcome = apply_baseline(
        _keyed("f.a"),
        Baseline(frozenset({_key("f.a"), elsewhere})),
        PrunableFiles(frozenset({"src/a.py"})),
    )

    assert outcome.stale == ()
    assert outcome.regenerated.root == frozenset({_key("f.a"), elsewhere})


def test_regenerates_from_the_violations_this_run_found() -> None:
    outcome = apply_baseline(
        _keyed("f.a", "f.new"),
        Baseline(frozenset({_key("f.a"), _key("f.gone")})),
        PrunableFiles(frozenset({"src/a.py"})),
    )

    assert outcome.regenerated.root == frozenset({_key("f.a"), _key("f.new")})


def test_suppresses_a_violation_that_moved_to_another_line() -> None:
    moved = KeyedViolations(
        (KeyedViolation(key=_key("f.a"), violation=_violation("f.a", line=42)),)
    )

    outcome = apply_baseline(
        moved,
        Baseline(frozenset({_key("f.a")})),
        PrunableFiles(frozenset({"src/a.py"})),
    )

    assert outcome.reported == ()
