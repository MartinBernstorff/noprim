import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import RootModel

from noprim_core import CheckConfig, DeniedTypes, Surface
from noprim_io import CheckPaths, DiscoveryConfig, IgnorePatterns, check_paths


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
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Only log errors.")
    ] = False,
) -> None:
    logging.basicConfig(
        level=logging.ERROR if quiet else logging.INFO, format="%(message)s"
    )

    source = _resolve_config(
        AllowedNames(tuple(allow if allow is not None else ())),
        DeniedNames(tuple(deny if deny is not None else ())),
    )

    report = check_paths(
        CheckPaths(tuple(paths) if paths is not None else (Path.cwd(),)),
        DiscoveryConfig(
            excludes=IgnorePatterns(tuple(exclude if exclude is not None else ())),
            source=source,
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
