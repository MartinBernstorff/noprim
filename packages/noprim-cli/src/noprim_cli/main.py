from pathlib import Path
from time import perf_counter
from typing import Annotated, NoReturn

import typer
from pydantic import RootModel

from noprim_core import (
    Baseline,
    BaselineOutcome,
    CheckConfig,
    DeniedTypes,
    Surface,
    Violation,
    apply_baseline,
)
from noprim_io import (
    BaselinePath,
    CheckPaths,
    CheckReport,
    DiscoveryConfig,
    FileError,
    Filenames,
    IgnorePatterns,
    MalformedBaselineError,
    UnsupportedBaselineVersionError,
    Violations,
    check_paths,
    keyed_violations,
    read_baseline,
    walked_files,
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


app = typer.Typer(no_args_is_help=True)


class Duration(RootModel[float]):
    pass


class Count(RootModel[int]):
    pass


class Noun(RootModel[str]):
    pass


class Errors(RootModel[tuple[FileError, ...]]):
    pass


class WriteBaselineWithoutPathError(typer.BadParameter):
    def __init__(self) -> None:
        super().__init__("--write-baseline needs --baseline to say which file to write")


@app.callback()
def cli() -> None:
    """Find function parameters annotated with primitive types."""


def pretty_duration(duration: Duration) -> str:
    milliseconds = round(duration.root * 1000)
    seconds, remainder = divmod(milliseconds, 1000)
    if seconds == 0:
        return f"{remainder}ms"
    return f"{milliseconds / 1000:.2f}s"


def _plural(count: Count, noun: Noun) -> str:
    return (
        f"{count.root} {noun.root}" if count.root == 1 else f"{count.root} {noun.root}s"
    )


def _message(violation: Violation) -> str:
    name = violation.qualname.rsplit(".", 1)[-1]
    match violation.surface:
        case Surface.PARAMETER:
            return f'parameter "{name}" is annotated "{violation.annotation}"'
        case Surface.RETURN:
            return f'return type is annotated "{violation.annotation}"'
        case Surface.ATTRIBUTE:
            return f'attribute "{name}" is annotated "{violation.annotation}"'


def _found(reported: Count, suppressed: Count, errors: Count) -> str:
    clauses = [
        f"found {_plural(reported, Noun('violation'))}"
        if reported.root > 0
        else "no violations",
        *([f"{suppressed.root} suppressed by baseline"] if suppressed.root > 0 else []),
        *([_plural(errors, Noun("error"))] if errors.root > 0 else []),
    ]
    return ", ".join(clauses)


def _diagnostics(violations: Violations, errors: Errors) -> list[str]:
    located = sorted(
        [(v.filename, v.line, v.column, _message(v)) for v in violations.root]
        + [(e.filename, e.line, e.column, e.message) for e in errors.root]
    )
    return [
        f"{filename}:{line}:{column}: {text}"
        for filename, line, column, text in located
    ]


def _resolve_config(allow: AllowedNames, deny: DeniedNames) -> CheckConfig:
    default = DeniedTypes.default().root
    # "" is the sentinel for unresolvable annotations, so denying it matches everything.
    if "" in set(allow.root) | set(deny.root):
        raise EmptyNameError
    conflicting = sorted(set(allow.root) & set(deny.root))
    if len(conflicting) > 0:
        raise AllowedAndDeniedError(AllowedNames(tuple(conflicting)))
    unknown = sorted(set(allow.root) - default)
    if len(unknown) > 0:
        raise NotOnDenyListError(AllowedNames(tuple(unknown)))
    return CheckConfig(denied=DeniedTypes((default - set(allow.root)) | set(deny.root)))


@app.command()
def check(
    paths: Annotated[
        list[Path] | None, typer.Argument(help="Files or directories to check.")
    ] = None,
    allow: Annotated[
        list[str] | None,
        typer.Option("--allow", help="Remove a type from the deny-list. Repeatable."),
    ] = None,
    deny: Annotated[
        list[str] | None,
        typer.Option("--deny", help="Add a type to the deny-list. Repeatable."),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option("--exclude", help="Glob to skip while walking. Repeatable."),
    ] = None,
    baseline: Annotated[
        Path | None,
        typer.Option(
            "--baseline",
            help="Suppress violations recorded in this file, writing it if absent.",
        ),
    ] = None,
    refresh: Annotated[
        bool,
        typer.Option("--write-baseline", help="Rewrite an existing baseline file."),
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress the summary.")
    ] = False,
) -> None:
    source = _resolve_config(
        AllowedNames(tuple(allow if allow is not None else ())),
        DeniedNames(tuple(deny if deny is not None else ())),
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
    except OSError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    elapsed = Duration(perf_counter() - started)

    if baseline is None:
        _report_run(report, elapsed, quiet=quiet, suppressed=Count(0))

    path = BaselinePath(baseline)
    outcome = _against_baseline(report, path)

    if refresh or not path.root.exists():
        try:
            write_baseline(path, outcome.regenerated)
        except OSError as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(2) from error
        _report_written(report, outcome, path, elapsed, quiet=quiet)

    if len(outcome.stale) > 0 and not quiet:
        typer.echo(f"note: {_stale_note(Count(len(outcome.stale)))}", err=True)
    _report_run(
        report.model_copy(update={"violations": outcome.reported}),
        elapsed,
        quiet=quiet,
        suppressed=Count(len(outcome.suppressed)),
    )


def _stale_note(count: Count) -> str:
    subject = (
        f"{count.root} baseline entry no longer matches"
        if count.root == 1
        else f"{count.root} baseline entries no longer match"
    )
    return f"{subject}; rerun with --write-baseline to prune"


def _against_baseline(report: CheckReport, path: BaselinePath) -> BaselineOutcome:
    try:
        existing = read_baseline(path) if path.root.exists() else Baseline.empty()
    except (MalformedBaselineError, UnsupportedBaselineVersionError, OSError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    return apply_baseline(
        keyed_violations(Violations(report.violations), path),
        existing,
        walked_files(Filenames(report.checked), path),
    )


def _report_written(
    report: CheckReport,
    outcome: BaselineOutcome,
    path: BaselinePath,
    elapsed: Duration,
    *,
    quiet: bool,
) -> NoReturn:
    for line in _diagnostics(Violations(()), Errors(report.errors)):
        typer.echo(line)
    if not quiet:
        typer.echo(
            f"Checked {_plural(Count(len(report.checked)), Noun('file'))} "
            f"in {pretty_duration(elapsed)} - wrote "
            f"{_plural(Count(len(outcome.regenerated.root)), Noun('violation'))} "
            f"to {path.root}",
            err=True,
        )
    raise typer.Exit(1 if len(report.errors) > 0 else 0)


def _report_run(
    report: CheckReport,
    elapsed: Duration,
    *,
    quiet: bool,
    suppressed: Count,
) -> NoReturn:
    diagnostics = _diagnostics(Violations(report.violations), Errors(report.errors))
    for line in diagnostics:
        typer.echo(line)

    if not quiet:
        summary = _found(
            Count(len(report.violations)), suppressed, Count(len(report.errors))
        )
        typer.echo(
            f"Checked {_plural(Count(len(report.checked)), Noun('file'))} "
            f"in {pretty_duration(elapsed)} - {summary}",
            err=True,
        )

    raise typer.Exit(1 if len(diagnostics) > 0 else 0)
