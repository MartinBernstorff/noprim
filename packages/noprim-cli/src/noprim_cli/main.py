from pathlib import Path
from time import perf_counter
from tomllib import TOMLDecodeError
from typing import Annotated, override

import typer
from iterpy import Arr
from pydantic import BaseModel, RootModel, ValidationError

from noprim_core import (
    AllowedNames,
    ColumnNumber,
    DeniedNames,
    Filename,
    IgnoredNames,
    LineNumber,
    PathPatterns,
    Settings,
    Surface,
    Verdict,
    Violation,
)
from noprim_io import (
    CheckPaths,
    CheckReport,
    DiscoveryConfig,
    ExistingDirectory,
    LoadedSettings,
    check_paths,
    load_settings,
)


class ConfigError(typer.BadParameter):
    pass


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


def _found(report: CheckReport) -> DisplayText:
    violations = (
        f"found {_plural(Count(len(report.violations)), Noun('violation'))}"
        if len(report.violations) > 0
        else "no violations"
    )
    if len(report.errors) == 0:
        return DisplayText(violations)
    errors = _plural(Count(len(report.errors)), Noun("error"))
    return DisplayText(f"{violations}, {errors}")


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


class Overrides(BaseModel):
    allow: AllowedNames | None
    deny: DeniedNames | None
    exclude: PathPatterns | None
    ignore_names: IgnoredNames | None
    check_predicates: Verdict | None
    top_types: Verdict | None


def _overridden(loaded: LoadedSettings, overrides: Overrides) -> LoadedSettings:
    given = {
        key: value for key, value in overrides.model_dump().items() if value is not None
    }
    if len(given) == 0:
        return loaded
    return loaded.model_copy(
        update={
            "settings": Settings.model_validate(loaded.settings.model_dump() | given)
        }
    )


def _settings(overrides: Overrides) -> LoadedSettings:
    try:
        loaded = load_settings(ExistingDirectory(Path.cwd()))
        return _overridden(loaded, overrides)
    except (OSError, TOMLDecodeError, ValidationError) as error:
        raise ConfigError(str(error)) from error


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
        bool | None,
        typer.Option(
            "--check-predicates",
            help="Report functions returning bool instead of skipping them.",
        ),
    ] = None,
    top_types: Annotated[  # noprim: ignore
        bool | None,
        typer.Option("--top-types", help="Also report Any and object. Off by default."),
    ] = None,
    quiet: Annotated[  # noprim: ignore
        bool, typer.Option("--quiet", "-q", help="Suppress the summary.")
    ] = False,
) -> None:
    settings = _settings(
        Overrides(
            allow=AllowedNames(tuple(allow)) if allow is not None else None,
            deny=DeniedNames(tuple(deny)) if deny is not None else None,
            exclude=PathPatterns(tuple(exclude)) if exclude is not None else None,
            ignore_names=(
                IgnoredNames(frozenset(ignore_names))
                if ignore_names is not None
                else None
            ),
            check_predicates=(
                Verdict(root=check_predicates) if check_predicates is not None else None
            ),
            top_types=Verdict(root=top_types) if top_types is not None else None,
        )
    )

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
            DiscoveryConfig(settings=settings),
        )

    # A directory can vanish between being listed and being walked, which surfaces
    # as ExistingDirectory failing to validate rather than as an OSError.
    except (OSError, ValidationError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    elapsed = Duration(perf_counter() - started)

    diagnostics = _diagnostics(report).to_list()
    for line in diagnostics:
        typer.echo(str(line))

    if not quiet:
        typer.echo(
            f"Checked {_plural(Count(report.files_checked.root), Noun('file'))} "
            f"in {pretty_duration(elapsed)} - {_found(report)}",
            err=True,
        )

    raise typer.Exit(1 if len(diagnostics) > 0 else 0)
