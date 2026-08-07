import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from iterpy import Arr
from pydantic import RootModel

from noprim_core import (
    CheckConfig,
    DeniedTypes,
    Filename,
    SourceCode,
    Surface,
    Violation,
    check_source,
)


class AllowedNames(RootModel[tuple[str, ...]]):
    pass


class DeniedNames(RootModel[tuple[str, ...]]):
    pass


class AllowedAndDeniedError(typer.BadParameter):
    def __init__(self, names: AllowedNames) -> None:
        super().__init__(f"passed to both --allow and --deny: {', '.join(names.root)}")


class NotOnDenyListError(typer.BadParameter):
    def __init__(self, names: AllowedNames) -> None:
        super().__init__(
            f"--allow of a name that is not on the deny-list: {', '.join(names.root)}"
        )


app = typer.Typer(no_args_is_help=True)

log = logging.getLogger("noprim")


@app.callback()
def cli() -> None:
    """Find function parameters annotated with primitive types."""


def _check_file(path: Path, config: CheckConfig) -> Arr[Violation]:
    return check_source(SourceCode(path.read_text()), Filename(str(path)), config)


def _verb(surface: Surface) -> str:
    match surface:
        case Surface.PARAMETER:
            return "takes"
        case Surface.RETURN:
            return "returns"
        case Surface.ATTRIBUTE:
            return "holds"


def _resolve_config(allow: AllowedNames, deny: DeniedNames) -> CheckConfig:
    default = DeniedTypes.default().root
    conflicting = sorted(set(allow.root) & set(deny.root))
    if len(conflicting) > 0:
        raise AllowedAndDeniedError(AllowedNames(tuple(conflicting)))
    unknown = sorted(set(allow.root) - default)
    if len(unknown) > 0:
        raise NotOnDenyListError(AllowedNames(tuple(unknown)))
    return CheckConfig(denied=DeniedTypes((default - set(allow.root)) | set(deny.root)))


@app.command()
def check(
    paths: Annotated[list[Path], typer.Argument(help="Files or directories to check.")],
    allow: Annotated[
        list[str] | None,
        typer.Option("--allow", help="Remove a type from the deny-list."),
    ] = None,
    deny: Annotated[
        list[str] | None, typer.Option("--deny", help="Add a type to the deny-list.")
    ] = None,
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

    config = _resolve_config(
        AllowedNames(tuple(allow if allow is not None else ())),
        DeniedNames(tuple(deny if deny is not None else ())),
    )
    violations = Arr(files).map(lambda p: _check_file(p, config)).flatten().to_list()
    for violation in violations:
        typer.echo(
            f"{violation.filename}:{violation.line}: {violation.qualname} "
            f"{_verb(violation.surface)} a primitive '{violation.annotation}'"
        )

    if len(violations) > 0:
        sys.exit(1)
    log.info("No primitive parameters found")
