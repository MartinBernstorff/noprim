from pathlib import Path
from time import perf_counter
from tomllib import TOMLDecodeError
from typing import Annotated, NoReturn

import typer
from pydantic import BaseModel, ValidationError

from noprim_cli.render import (
    Duration,
    Rendered,
    RenderOptions,
    RunOutcome,
    baseline_applied,
    baseline_written,
    render,
)
from noprim_core.baseline import Baseline, BaselineOutcome, apply_baseline
from noprim_core.checker import IgnoredNames
from noprim_core.settings import AllowedNames, DeniedNames, PathPatterns, Settings
from noprim_core.verdict import Verdict
from noprim_io.baseline import (
    BaselinePath,
    MalformedBaselineError,
    UnsupportedBaselineVersionError,
    Violations,
    keyed_violations,
    prunable_files,
    read_baseline,
    write_baseline,
)
from noprim_io.check import CheckPaths, CheckReport, DiscoveryConfig, check_paths
from noprim_io.paths import ExistingDirectory
from noprim_io.settings import LoadedSettings, load_settings


class ConfigError(typer.BadParameter):
    pass


class WriteBaselineWithoutPathError(typer.BadParameter):
    def __init__(self) -> None:
        super().__init__("--write-baseline needs --baseline to say which file to write")


app = typer.Typer(no_args_is_help=True)


@app.callback()
def cli() -> None:
    """Find function parameters annotated with primitive types."""


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
    if refresh and baseline is None:
        raise WriteBaselineWithoutPathError
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
        _fail(error)
    elapsed = Duration(perf_counter() - started)
    options = RenderOptions(quiet=Verdict(root=quiet))

    if baseline is None:
        _emit(render(RunOutcome(report=report), elapsed, options))

    path = BaselinePath(baseline)
    outcome = _against_baseline(report, CheckPaths(targets), path)

    if refresh or not path.root.exists():
        try:
            write_baseline(path, outcome.regenerated)
        except OSError as error:
            _fail(error)
        _emit(render(baseline_written(report, outcome, path), elapsed, options))

    _emit(render(baseline_applied(report, outcome), elapsed, options))


def _emit(rendered: Rendered) -> NoReturn:
    for line in rendered.stdout:
        typer.echo(str(line))
    for line in rendered.stderr:
        typer.echo(str(line), err=True)
    raise typer.Exit(rendered.exit_code.root)


def _fail(error: Exception) -> NoReturn:
    typer.echo(f"error: {error}", err=True)
    raise typer.Exit(2) from error


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
