import logging
import sys
from pathlib import Path
from typing import Annotated

import typer

from noprim_core import Surface
from noprim_io import CheckPaths, DiscoveryConfig, IgnorePatterns, check_paths

app = typer.Typer(no_args_is_help=True)

log = logging.getLogger("noprim")


@app.callback()
def cli() -> None:
    """Find function parameters annotated with primitive types."""


def _verb(surface: Surface) -> str:
    match surface:
        case Surface.PARAMETER:
            return "takes"
        case Surface.RETURN:
            return "returns"
        case Surface.ATTRIBUTE:
            return "holds"


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
        bool, typer.Option("--quiet", "-q", help="Only log errors.")
    ] = False,
) -> None:
    logging.basicConfig(
        level=logging.ERROR if quiet else logging.INFO, format="%(message)s"
    )

    report = check_paths(
        CheckPaths(tuple(paths) if paths is not None else (Path.cwd(),)),
        DiscoveryConfig(
            excludes=IgnorePatterns(tuple(exclude if exclude is not None else ()))
        ),
    )

    log.info("Checked %d file(s)", report.files_checked)

    for violation in report.violations:
        typer.echo(
            f"{violation.filename}:{violation.line}: {violation.qualname} "
            f"{_verb(violation.surface)} a primitive '{violation.annotation}'"
        )
    for error in report.errors:
        typer.echo(f"error: {error.filename}: {error.message}")

    if len(report.violations) > 0 or len(report.errors) > 0:
        sys.exit(1)
    log.info("No primitive parameters found")
