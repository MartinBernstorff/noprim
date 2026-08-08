from pathlib import Path
from time import perf_counter
from tomllib import TOMLDecodeError
from typing import Annotated, NoReturn

import typer
from iterpy import Arr
from pydantic import RootModel, ValidationError

from noprim_cli.render import (
    Duration,
    GroupAxes,
    GroupAxis,
    OutputFormat,
    Rendered,
    RenderOptions,
    RunOutcome,
    baseline_applied,
    baseline_written,
    render,
)
from noprim_core.baseline import Baseline, BaselineOutcome, apply_baseline
from noprim_core.rules.preset import Preset
from noprim_core.settings import Settings
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


class GroupByWithoutStatisticsError(typer.BadParameter):
    def __init__(self) -> None:
        super().__init__("--group-by needs --statistics to have anything to group")


class UnknownGroupAxisError(typer.BadParameter):
    def __init__(self, name: "AxisName") -> None:
        expected = ", ".join(axis.value for axis in GroupAxis)
        super().__init__(
            f"--group-by got an unknown axis: {name.root}; expected one of {expected}"
        )


class RepeatedGroupAxisError(typer.BadParameter):
    def __init__(self, name: "AxisName") -> None:
        super().__init__(f"--group-by got the same axis twice: {name.root}")


class EmptyGroupByError(typer.BadParameter):
    def __init__(self) -> None:
        super().__init__("--group-by needs at least one axis")


app = typer.Typer(no_args_is_help=True)


@app.callback()
def cli() -> None:
    """Find function parameters annotated with primitive types."""


class Arguments(RootModel[dict[str, object]]):
    pass


class AxisName(RootModel[str]):
    pass


class AxisNames(RootModel[tuple[str, ...]]):
    def split(self) -> Arr[AxisName]:
        return (
            Arr(self.root)
            .map(lambda spelling: spelling.split(","))
            .flatten()
            .map(str.strip)
            .filter(lambda name: name != "")
            .map(AxisName)
        )


def _axis(name: AxisName) -> GroupAxis:
    if name.root not in set(GroupAxis):
        raise UnknownGroupAxisError(name)
    return GroupAxis(name.root)


def _axes(names: AxisNames) -> GroupAxes:
    axes = tuple(names.split().map(_axis))
    if len(axes) == 0:
        raise EmptyGroupByError
    repeated = Arr(axes).filter(lambda axis: axes.count(axis) > 1).to_list()
    if len(repeated) > 0:
        raise RepeatedGroupAxisError(AxisName(repeated[0].value))
    return GroupAxes(axes)


class Overrides(RootModel[dict[str, object]]):
    pass


# check's parameters are named after the settings they override, so the settings
# schema is what picks the config flags out of them: a new key needs a Typer
# annotation and nothing else.
def _overrides(arguments: Arguments) -> Overrides:
    return Overrides(
        {
            name: value
            for name, value in arguments.root.items()
            if name in Settings.model_fields and value is not None
        }
    )


def _overridden(loaded: LoadedSettings, overrides: Overrides) -> LoadedSettings:
    if len(overrides.root) == 0:
        return loaded
    return loaded.model_copy(
        update={
            "settings": Settings.model_validate(
                loaded.settings.model_dump() | overrides.root
            )
        }
    )


def _settings(arguments: Arguments) -> LoadedSettings:
    try:
        loaded = load_settings(ExistingDirectory(Path.cwd()))
        return _overridden(loaded, _overrides(arguments))
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
            help="Skip parameters and attributes matching this glob. Repeatable.",
        ),
    ] = None,
    ignore_param_names: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option(
            "--ignore-param-names",
            help="Skip parameters matching this glob. Repeatable.",
        ),
    ] = None,
    ignore_attribute_names: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option(
            "--ignore-attribute-names",
            help="Skip attributes matching this glob. Repeatable.",
        ),
    ] = None,
    exclude: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option("--exclude", help="Glob to skip while walking. Repeatable."),
    ] = None,
    preset: Annotated[
        Preset | None,
        typer.Option(
            "--preset",
            help="Which rules to start from before select, extend-select and ignore.",
        ),
    ] = None,
    select: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option(
            "--select",
            help="Run these rule codes instead of the defaults. Prefixes count."
            " Repeatable.",
        ),
    ] = None,
    extend_select: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option(
            "--extend-select",
            help="Run these rule codes as well as the selected ones. Repeatable.",
        ),
    ] = None,
    ignore: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option(
            "--ignore", help="Drop these rule codes from the run. Repeatable."
        ),
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
    statistics: Annotated[  # noprim: ignore
        bool,
        typer.Option("--statistics", help="Print counts instead of one line each."),
    ] = False,
    group_by: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option(
            "--group-by",
            help="Axes to count --statistics along: rule, type, name or path."
            " Comma-separated, repeatable.",
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--output-format", help="How to print what was found."),
    ] = OutputFormat.TEXT,
) -> None:
    if refresh and baseline is None:
        raise WriteBaselineWithoutPathError
    if group_by is not None and not statistics:
        raise GroupByWithoutStatisticsError
    # Nothing is bound yet, so locals() is exactly the parameters above.
    settings = _settings(Arguments(locals()))
    options = RenderOptions(
        quiet=Verdict(root=quiet),
        output_format=output_format,
        statistics=Verdict(root=statistics),
        group_by=(
            GroupAxes.default()
            if group_by is None
            else _axes(AxisNames(tuple(group_by)))
        ),
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

    if baseline is None:
        _emit(render(RunOutcome(report=report), elapsed, options))

    path = BaselinePath(baseline)
    outcome = _against_baseline(
        report, CheckPaths(targets), path, Verdict(root=refresh)
    )

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


def _existing_baseline(path: BaselinePath, refresh: Verdict) -> Baseline:
    if not path.root.exists():
        return Baseline.empty()
    try:
        return read_baseline(path)
    except UnsupportedBaselineVersionError as error:
        # --write-baseline is the remedy the error names, so it has to survive it.
        if refresh.and_(error.outdated).negated:
            raise
        return Baseline.empty()


def _against_baseline(
    report: CheckReport, targets: CheckPaths, path: BaselinePath, refresh: Verdict
) -> BaselineOutcome:
    # A baseline path under a directory that does not exist surfaces as
    # ExistingDirectory failing to validate rather than as an OSError.
    try:
        existing = _existing_baseline(path, refresh)
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
