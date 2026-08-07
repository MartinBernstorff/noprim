from pathlib import Path
from time import perf_counter
from typing import Annotated

import typer
from pydantic import RootModel

from noprim_core import Surface, Violation
from noprim_io import (
    CheckPaths,
    CheckReport,
    DiscoveryConfig,
    IgnorePatterns,
    check_paths,
)

app = typer.Typer(no_args_is_help=True)


class Duration(RootModel[float]):
    pass


class Count(RootModel[int]):
    pass


class Noun(RootModel[str]):
    pass


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


def _diagnostics(report: CheckReport) -> list[str]:
    located = sorted(
        [(v.filename, v.line, v.column, _message(v)) for v in report.violations]
        + [(e.filename, e.line, e.column, e.message) for e in report.errors]
    )
    return [
        f"{filename}:{line}:{column}: {text}"
        for filename, line, column, text in located
    ]


@app.command()
def check(
    paths: Annotated[
        list[Path] | None, typer.Argument(help="Files or directories to check.")
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option("--exclude", help="Glob to skip while walking. Repeatable."),
    ] = None,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress the summary.")
    ] = False,
) -> None:
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
                excludes=IgnorePatterns(tuple(exclude if exclude is not None else ()))
            ),
        )
    except OSError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    elapsed = Duration(perf_counter() - started)

    diagnostics = _diagnostics(report)
    for line in diagnostics:
        typer.echo(line)

    if not quiet:
        found = (
            f"found {_plural(Count(len(diagnostics)), Noun('violation'))}"
            if len(diagnostics) > 0
            else "no violations"
        )
        typer.echo(
            f"Checked {_plural(Count(report.files_checked), Noun('file'))} "
            f"in {pretty_duration(elapsed)} - {found}",
            err=True,
        )

    raise typer.Exit(1 if len(diagnostics) > 0 else 0)
