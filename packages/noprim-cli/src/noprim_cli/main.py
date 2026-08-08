from pathlib import Path
from time import perf_counter
from typing import Annotated, override

import typer
from iterpy import Arr
from pydantic import BaseModel, RootModel, ValidationError

from noprim_core import (
    CheckConfig,
    ColumnNumber,
    DeniedTypes,
    Filename,
    LineNumber,
    Surface,
    TopTypes,
    Verdict,
    Violation,
)
from noprim_io import (
    CheckPaths,
    CheckReport,
    DiscoveryConfig,
    IgnorePatterns,
    check_paths,
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


class AllowedTopTypeError(typer.BadParameter):
    def __init__(self, names: AllowedNames) -> None:
        super().__init__(
            f"--allow of a type governed by --top-types: {', '.join(names.root)}. "
            "Drop --top-types instead; the rule is all or nothing."
        )


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


def _resolve_config(
    allow: AllowedNames, deny: DeniedNames, top_types: Verdict
) -> CheckConfig:
    default = DeniedTypes.default().root
    # "" is the sentinel for unresolvable annotations, so denying it matches everything.
    if "" in set(allow.root) | set(deny.root):
        raise EmptyNameError
    conflicting = sorted(set(allow.root) & set(deny.root))
    if len(conflicting) > 0:
        raise AllowedAndDeniedError(AllowedNames(tuple(conflicting)))
    top = sorted(set(allow.root) & TopTypes.default().root)
    if len(top) > 0:
        raise AllowedTopTypeError(AllowedNames(tuple(top)))
    unknown = sorted(set(allow.root) - default)
    if len(unknown) > 0:
        raise NotOnDenyListError(AllowedNames(tuple(unknown)))
    return CheckConfig(
        denied=DeniedTypes((default - set(allow.root)) | set(deny.root)),
        top_types=top_types,
    )


# Typer derives the command-line interface from these annotations: a RootModel here
# would be parsed as one opaque argument, losing the flag names and the arity.
@app.command()
def check(
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
    exclude: Annotated[  # noprim: ignore
        list[str] | None,
        typer.Option("--exclude", help="Glob to skip while walking. Repeatable."),
    ] = None,
    top_types: Annotated[  # noprim: ignore
        bool,
        typer.Option("--top-types", help="Also report Any and object. Off by default."),
    ] = False,
    quiet: Annotated[  # noprim: ignore
        bool, typer.Option("--quiet", "-q", help="Suppress the summary.")
    ] = False,
) -> None:
    source = _resolve_config(
        AllowedNames(tuple(allow if allow is not None else ())),
        DeniedNames(tuple(deny if deny is not None else ())),
        Verdict(top_types),
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
            DiscoveryConfig(
                excludes=IgnorePatterns(tuple(exclude if exclude is not None else ())),
                source=source,
            ),
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
