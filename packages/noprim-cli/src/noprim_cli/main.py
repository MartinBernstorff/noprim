from pathlib import Path
from time import perf_counter
from typing import Annotated, NoReturn, override

import typer
from iterpy import Arr
from pydantic import BaseModel, RootModel, ValidationError

from noprim_core import (
    Baseline,
    BaselineOutcome,
    CheckConfig,
    ColumnNumber,
    DeniedTypes,
    Filename,
    IgnoredNames,
    LineNumber,
    Surface,
    TopTypes,
    Verdict,
    Violation,
    apply_baseline,
)
from noprim_io import (
    BaselinePath,
    CheckPaths,
    CheckReport,
    DiscoveryConfig,
    IgnorePatterns,
    MalformedBaselineError,
    UnsupportedBaselineVersionError,
    Violations,
    check_paths,
    keyed_violations,
    prunable_files,
    read_baseline,
    write_baseline,
)


class AllowedNames(RootModel[tuple[str, ...]]):
    pass


class DeniedNames(RootModel[tuple[str, ...]]):
    pass


class AllowedAndDeniedError(typer.BadParameter):
    def __init__(self, names: AllowedNames) -> None:
        super().__init__(f"passed to both --allow and --deny: {', '.join(names.root)}")


class EmptyNameError(typer.BadParameter):
    def __init__(self) -> None:
        super().__init__("--allow and --deny need a type name; got an empty one")


class NotOnDenyListError(typer.BadParameter):
    def __init__(self, names: AllowedNames) -> None:
        super().__init__(
            f"--allow of a name that is not on the deny-list: {', '.join(names.root)}"
        )


class WriteBaselineWithoutPathError(typer.BadParameter):
    def __init__(self) -> None:
        super().__init__("--write-baseline needs --baseline to say which file to write")


class AllowedTopTypeError(typer.BadParameter):
    def __init__(self, names: AllowedNames) -> None:
        super().__init__(
            f"--allow of a type governed by --top-types: {', '.join(names.root)}. "
            "Drop --top-types instead; the rule is all or nothing."
        )


app = typer.Typer(no_args_is_help=True)


class Duration(RootModel[float]):
    pass


class Count(RootModel[int]):
    pass


class Noun(RootModel[str]):
    pass


class DisplayText(RootModel[str]):
    # Interpolated into other messages, so it has to render as its text and not as
    # the model's repr.
    @override
    def __str__(self) -> str:
        return self.root

    @override
    def __repr__(self) -> str:
        return self.root


@app.callback()
def cli() -> None:
    """Find function parameters annotated with primitive types."""


def pretty_duration(duration: Duration) -> DisplayText:
    milliseconds = round(duration.root * 1000)
    seconds, remainder = divmod(milliseconds, 1000)
    if seconds == 0:
        return DisplayText(f"{remainder}ms")
    return DisplayText(f"{milliseconds / 1000:.2f}s")


def _plural(count: Count, noun: Noun) -> DisplayText:
    plural = "" if count.root == 1 else "s"
    return DisplayText(f"{count.root} {noun.root}{plural}")


def _message(violation: Violation) -> DisplayText:
    name = violation.qualname.leaf().root
    annotation = violation.annotation.root
    match violation.surface:
        case Surface.PARAMETER:
            return DisplayText(f'parameter "{name}" is annotated "{annotation}"')
        case Surface.RETURN:
            return DisplayText(f'return type is annotated "{annotation}"')
        case Surface.ATTRIBUTE:
            return DisplayText(f'attribute "{name}" is annotated "{annotation}"')


def _found(report: CheckReport, suppressed: Count) -> DisplayText:
    clauses = [
        f"found {_plural(Count(len(report.violations)), Noun('violation'))}"
        if len(report.violations) > 0
        else "no violations",
        *([f"{suppressed.root} suppressed by baseline"] if suppressed.root > 0 else []),
        *(
            [str(_plural(Count(len(report.errors)), Noun("error")))]
            if len(report.errors) > 0
            else []
        ),
    ]
    return DisplayText(", ".join(clauses))


class Diagnostic(BaseModel):
    filename: Filename
    line: LineNumber
    column: ColumnNumber
    text: DisplayText

    def __lt__(self, other: "Diagnostic") -> bool:
        return (self.filename.root, self.line.root, self.column.root) < (
            other.filename.root,
            other.line.root,
            other.column.root,
        )

    def rendered(self) -> DisplayText:
        return DisplayText(
            f"{self.filename.root}:{self.line.root}:{self.column.root}: {self.text}"
        )


def _diagnostics(report: CheckReport) -> Arr[DisplayText]:
    located: list[Diagnostic] = [
        *(
            Diagnostic(
                filename=v.filename, line=v.line, column=v.column, text=_message(v)
            )
            for v in report.violations
        ),
        *(
            Diagnostic(
                filename=e.filename,
                line=e.line,
                column=e.column,
                text=DisplayText(e.message.root),
            )
            for e in report.errors
        ),
    ]
    return Arr(sorted(located)).map(Diagnostic.rendered)


def _resolve_config(
    allow: AllowedNames,
    deny: DeniedNames,
    check_predicates: Verdict,
    ignore_names: IgnoredNames,
    top_types: Verdict,
) -> CheckConfig:
    default = DeniedTypes.default().root
    # "" is the sentinel for unresolvable annotations, so denying it matches everything.
    if "" in set(allow.root) | set(deny.root):
        raise EmptyNameError
    conflicting = sorted(set(allow.root) & set(deny.root))
    if len(conflicting) > 0:
        raise AllowedAndDeniedError(AllowedNames(tuple(conflicting)))
    top = sorted(set(allow.root) & TopTypes.default().root)
    if len(top) > 0:
        raise AllowedTopTypeError(AllowedNames(tuple(top)))
    unknown = sorted(set(allow.root) - default)
    if len(unknown) > 0:
        raise NotOnDenyListError(AllowedNames(tuple(unknown)))
    return CheckConfig(
        denied=DeniedTypes((default - set(allow.root)) | set(deny.root)),
        check_predicates=check_predicates,
        ignored_names=ignore_names,
        top_types=top_types,
    )


# Typer derives the command-line interface from these annotations: a RootModel here
# would be parsed as one opaque argument, losing the flag names and the arity.
@app.command()
def check(  # noqa: PLR0913, PLR0917
    paths: Annotated[  # noprim: ignore
        list[Path] | None, typer.Argument(help="Files or directories to check.")
    ] = None,
    allow: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option("--allow", help="Remove a type from the deny-list. Repeatable."),
    ] = None,
    deny: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option("--deny", help="Add a type to the deny-list. Repeatable."),
    ] = None,
    ignore_names: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option(
            "--ignore-names",
            help="Skip parameters and attributes with this name. Repeatable.",
        ),
    ] = None,
    exclude: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option("--exclude", help="Glob to skip while walking. Repeatable."),
    ] = None,
    check_predicates: Annotated[  # noprim: ignore
        bool,
        typer.Option(
            "--check-predicates",
            help="Report functions returning bool instead of skipping them.",
        ),
    ] = False,
    top_types: Annotated[  # noprim: ignore
        bool,
        typer.Option("--top-types", help="Also report Any and object. Off by default."),
    ] = False,
    baseline: Annotated[  # noprim: ignore
        Path | None,
        typer.Option(
            "--baseline",
            help="Suppress violations recorded in this file, writing it if absent.",
        ),
    ] = None,
    refresh: Annotated[  # noprim: ignore
        bool,
        typer.Option("--write-baseline", help="Rewrite an existing baseline file."),
    ] = False,
    quiet: Annotated[  # noprim: ignore
        bool, typer.Option("--quiet", "-q", help="Suppress the summary.")
    ] = False,
) -> None:
    source = _resolve_config(
        AllowedNames(tuple(allow if allow is not None else ())),
        DeniedNames(tuple(deny if deny is not None else ())),
        Verdict(check_predicates),
        IgnoredNames(frozenset(ignore_names if ignore_names is not None else ())),
        Verdict(top_types),
    )
    if refresh and baseline is None:
        raise WriteBaselineWithoutPathError

    targets = tuple(paths) if paths is not None else (Path.cwd(),)
    missing = [path for path in targets if not path.exists()]
    if len(missing) > 0:
        for path in missing:
            typer.echo(f"error: {path}: no such file or directory", err=True)
        raise typer.Exit(2)

    started = perf_counter()
    try:
        report = check_paths(
            CheckPaths(targets),
            DiscoveryConfig(
                excludes=IgnorePatterns(tuple(exclude if exclude is not None else ())),
                source=source,
            ),
        )

    # A directory can vanish between being listed and being walked, which surfaces
    # as ExistingDirectory failing to validate rather than as an OSError.
    except (OSError, ValidationError) as error:
        _fail(error)
    elapsed = Duration(perf_counter() - started)

    if baseline is None:
        _report_run(report, elapsed, Verdict(quiet), Count(0))

    path = BaselinePath(baseline)
    outcome = _against_baseline(report, CheckPaths(targets), path)

    if refresh or not path.root.exists():
        try:
            write_baseline(path, outcome.regenerated)
        except OSError as error:
            _fail(error)
        _report_written(report, outcome, path, elapsed, Verdict(quiet))

    if len(outcome.stale) > 0 and not quiet:
        typer.echo(f"note: {_stale_note(Count(len(outcome.stale)))}", err=True)
    _report_run(
        report.model_copy(update={"violations": outcome.reported}),
        elapsed,
        Verdict(quiet),
        Count(len(outcome.suppressed)),
    )


def _fail(error: Exception) -> NoReturn:
    typer.echo(f"error: {error}", err=True)
    raise typer.Exit(2) from error


def _stale_note(count: Count) -> DisplayText:
    subject = (
        f"{count.root} baseline entry no longer matches"
        if count.root == 1
        else f"{count.root} baseline entries no longer match"
    )
    return DisplayText(f"{subject}; rerun with --write-baseline to prune")


def _against_baseline(
    report: CheckReport, targets: CheckPaths, path: BaselinePath
) -> BaselineOutcome:
    # A baseline path under a directory that does not exist surfaces as
    # ExistingDirectory failing to validate rather than as an OSError.
    try:
        existing = read_baseline(path) if path.root.exists() else Baseline.empty()
        return apply_baseline(
            keyed_violations(Violations(report.violations), path),
            existing,
            prunable_files(report, targets, existing, path),
        )
    except (
        MalformedBaselineError,
        UnsupportedBaselineVersionError,
        OSError,
        ValidationError,
    ) as error:
        _fail(error)


def _summary_line(
    report: CheckReport, elapsed: Duration, summary: DisplayText
) -> DisplayText:
    return DisplayText(
        f"Checked {_plural(Count(len(report.checked)), Noun('file'))} "
        f"in {pretty_duration(elapsed)} - {summary}"
    )


def _report_written(
    report: CheckReport,
    outcome: BaselineOutcome,
    path: BaselinePath,
    elapsed: Duration,
    quiet: Verdict,
) -> NoReturn:
    for line in _diagnostics(report.model_copy(update={"violations": ()})).to_list():
        typer.echo(str(line))
    if not quiet.root:
        written = _plural(Count(len(outcome.regenerated.root)), Noun("violation"))
        typer.echo(
            str(
                _summary_line(
                    report, elapsed, DisplayText(f"wrote {written} to {path.root}")
                )
            ),
            err=True,
        )
    raise typer.Exit(1 if len(report.errors) > 0 else 0)


def _report_run(
    report: CheckReport, elapsed: Duration, quiet: Verdict, suppressed: Count
) -> NoReturn:
    diagnostics = _diagnostics(report).to_list()
    for line in diagnostics:
        typer.echo(str(line))

    if not quiet.root:
        typer.echo(
            str(_summary_line(report, elapsed, _found(report, suppressed))), err=True
        )

    raise typer.Exit(1 if len(diagnostics) > 0 else 0)
