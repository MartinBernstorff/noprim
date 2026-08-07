import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from iterpy import Arr

from noprim_core import Filename, SourceCode, Violation, check_source

app = typer.Typer(no_args_is_help=True)

log = logging.getLogger("noprim")


@app.callback()
def cli() -> None:
    """Find function parameters annotated with primitive types."""


def _check_file(path: Path) -> Arr[Violation]:
    return check_source(SourceCode(path.read_text()), Filename(str(path)))


@app.command()
def check(
    paths: Annotated[list[Path], typer.Argument(help="Files or directories to check.")],
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Only log errors.")
    ] = False,
) -> None:
    logging.basicConfig(
        level=logging.ERROR if quiet else logging.INFO, format="%(message)s"
    )

    files = (
        Arr(paths)
        .map(lambda p: list(p.rglob("*.py")) if p.is_dir() else [p])
        .flatten()
        .to_list()
    )
    log.info("Checking %d file(s)", len(files))

    violations = Arr(files).map(_check_file).flatten().to_list()
    for violation in violations:
        typer.echo(
            f"{violation.filename}:{violation.line}: "
            f"{violation.function}({violation.parameter}: {violation.annotation}) "
            f"takes a primitive"
        )

    if len(violations) > 0:
        sys.exit(1)
    log.info("No primitive parameters found")
