from noprim_core.annotations import AnnotationText
from noprim_core.baseline import (
    Baseline,
    BaselineKey,
    KeyedViolation,
    KeyedViolations,
    PrunableFiles,
    apply_baseline,
)
from noprim_core.rules.code import RuleCode
from noprim_core.site import (
    ColumnNumber,
    Filename,
    LineNumber,
    Qualname,
    Surface,
)
from noprim_core.violation import Violation


def _violation(qualname: Qualname, line: LineNumber) -> Violation:
    return Violation(
        filename=Filename("/abs/src/a.py"),
        code=RuleCode("NOPRIM001"),
        line=line,
        column=ColumnNumber(1),
        surface=Surface.PARAMETER,
        qualname=qualname,
        annotation=AnnotationText("str"),
    )


def _key(qualname: Qualname) -> BaselineKey:
    return BaselineKey(
        filename=Filename("src/a.py"),
        code=RuleCode("NOPRIM001"),
        surface=Surface.PARAMETER,
        qualname=qualname,
        annotation=AnnotationText("str"),
    )


def _keyed(*qualnames: Qualname) -> KeyedViolations:
    return KeyedViolations(
        tuple(
            KeyedViolation(
                key=_key(qualname), violation=_violation(qualname, LineNumber(1))
            )
            for qualname in qualnames
        )
    )


def _walked() -> PrunableFiles:
    return PrunableFiles(frozenset({Filename("src/a.py")}))


def test_reports_violations_absent_from_the_baseline() -> None:
    outcome = apply_baseline(
        _keyed(Qualname("f.a"), Qualname("f.b")),
        Baseline(frozenset({_key(Qualname("f.a"))})),
        _walked(),
    )

    assert [v.qualname.root for v in outcome.reported] == ["f.b"]
    assert [v.qualname.root for v in outcome.suppressed] == ["f.a"]


def test_treats_an_unmatched_entry_in_a_walked_file_as_stale() -> None:
    outcome = apply_baseline(
        _keyed(Qualname("f.a")),
        Baseline(frozenset({_key(Qualname("f.a")), _key(Qualname("f.gone"))})),
        _walked(),
    )

    assert outcome.stale == (_key(Qualname("f.gone")),)


def test_keeps_entries_for_files_this_run_never_walked() -> None:
    elsewhere = BaselineKey(
        filename=Filename("src/b.py"),
        code=RuleCode("NOPRIM001"),
        surface=Surface.PARAMETER,
        qualname=Qualname("g.b"),
        annotation=AnnotationText("str"),
    )

    outcome = apply_baseline(
        _keyed(Qualname("f.a")),
        Baseline(frozenset({_key(Qualname("f.a")), elsewhere})),
        _walked(),
    )

    assert outcome.stale == ()
    assert outcome.regenerated.root == frozenset({_key(Qualname("f.a")), elsewhere})


def test_regenerates_from_the_violations_this_run_found() -> None:
    outcome = apply_baseline(
        _keyed(Qualname("f.a"), Qualname("f.new")),
        Baseline(frozenset({_key(Qualname("f.a")), _key(Qualname("f.gone"))})),
        _walked(),
    )

    assert outcome.regenerated.root == frozenset(
        {_key(Qualname("f.a")), _key(Qualname("f.new"))}
    )


def test_suppresses_a_violation_that_moved_to_another_line() -> None:
    moved = KeyedViolations(
        (
            KeyedViolation(
                key=_key(Qualname("f.a")),
                violation=_violation(Qualname("f.a"), LineNumber(42)),
            ),
        )
    )

    outcome = apply_baseline(
        moved, Baseline(frozenset({_key(Qualname("f.a"))})), _walked()
    )

    assert outcome.reported == ()
