from pathlib import Path
from time import perf_counter
from tomllib import TOMLDecodeError
from typing import Annotated, NoReturn, override

import typer
from iterpy import Arr
from pydantic import BaseModel, RootModel, ValidationError

from noprim_core.baseline import Baseline, BaselineOutcome, apply_baseline
from noprim_core.config import IgnoredNames
from noprim_core.rules.code import Selector, Selectors
from noprim_core.rules.registry import rule_for
from noprim_core.settings import AllowedNames, DeniedNames, PathPatterns, Settings
from noprim_core.site import ColumnNumber, Filename, LineNumber
from noprim_core.verdict import Verdict
from noprim_core.violation import Violation
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
    rule = rule_for(violation.code)
    return DisplayText(f"{violation.code.root} {rule.message(violation).root}")


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


class Overrides(BaseModel):
    allow: AllowedNames | None
    deny: DeniedNames | None
    exclude: PathPatterns | None
    ignore_names: IgnoredNames | None
    select: Selectors | None
    extend_select: Selectors | None
    ignore: Selectors | None


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


def _selectors(given: list[str] | None) -> Selectors | None:  # noprim: ignore
    return None if given is None else Selectors(tuple(Arr(given).map(Selector)))


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
            select=_selectors(select),
            extend_select=_selectors(extend_select),
            ignore=_selectors(ignore),
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

    if baseline is None:
        _report_run(report, elapsed, Verdict(root=quiet), Count(0))

    path = BaselinePath(baseline)
    outcome = _against_baseline(
        report, CheckPaths(targets), path, Verdict(root=refresh)
    )

    if refresh or not path.root.exists():
        try:
            write_baseline(path, outcome.regenerated)
        except OSError as error:
            _fail(error)
        _report_written(report, outcome, path, elapsed, Verdict(root=quiet))

    if len(outcome.stale) > 0 and not quiet:
        typer.echo(f"note: {_stale_note(Count(len(outcome.stale)))}", err=True)
    _report_run(
        report.model_copy(update={"violations": outcome.reported}),
        elapsed,
        Verdict(root=quiet),
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


def _existing_baseline(path: BaselinePath, refresh: Verdict) -> Baseline:
    if not path.root.exists():
        return Baseline.empty()
    try:
        return read_baseline(path)
    except UnsupportedBaselineVersionError as error:
        # --write-baseline is the remedy the error names, so it has to survive it.
        if not (refresh.root and error.outdated.root):
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
