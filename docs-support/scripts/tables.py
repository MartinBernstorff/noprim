import sys

from iterpy import Arr
from pydantic import ConfigDict, RootModel

from noprim_core.rules.registry import RULES
from noprim_core.rules.rule import Rule
from noprim_types.replacements import ReplacementTable


class Cell(RootModel[str]):
    pass


class Row(RootModel[tuple[Cell, ...]]):
    pass


class Width(RootModel[int]):
    pass


class Widths(RootModel[tuple[Width, ...]]):
    pass


class Table(RootModel[str]):
    pass


class TableName(RootModel[str]):
    model_config = ConfigDict(frozen=True)


def _widths(rows: Arr[Row]) -> Widths:
    columns = zip(*rows.map(lambda row: row.root), strict=True)
    return Widths(
        tuple(Width(max(len(cell.root) for cell in column)) for column in columns)
    )


def _rendered(row: Row, widths: Widths) -> Cell:
    padded = (
        cell.root.ljust(width.root)
        for cell, width in zip(row.root, widths.root, strict=True)
    )
    return Cell("  ".join(padded).rstrip())


def _aligned(rows: Arr[Row]) -> Table:
    widths = _widths(rows)
    return Table("\n".join(rows.map(lambda row: _rendered(row, widths).root)))


def _rule_row(rule: Rule) -> Row:
    return Row(
        (
            Cell(rule.code.root),
            Cell(rule.name.root),
            Cell(rule.example.root),
            Cell("yes" if rule.in_core else "no"),
        )
    )


def rules() -> Table:
    header = Row((Cell("Code"), Cell("Rule"), Cell("Flags"), Cell("In core")))
    return _aligned(Arr([header, *Arr(RULES).map(_rule_row)]))


# Insertion order carries the grouping the prose used to spell out: the builtins, then
# the stdlib value types, then the containers.
def denied() -> Table:
    header = Row((Cell("Denied"), Cell("Use instead")))
    rows = Arr(list(ReplacementTable.default().root.items())).map(
        lambda entry: Row(
            (
                Cell(entry[0].root),
                Cell(", ".join(name.root for name in entry[1].root)),
            )
        )
    )
    return _aligned(Arr([header, *rows]))


TABLES = {TableName("rules"): rules, TableName("denied"): denied}


if __name__ == "__main__":
    wanted = TableName(sys.argv[1])
    if wanted not in TABLES:
        sys.exit(f"no such table: {wanted.root}")
    print(TABLES[wanted]().root)  # noqa: T201
