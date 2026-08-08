from iterpy import Arr
from pydantic import RootModel

from noprim_core.rules.registry import RULES
from noprim_core.rules.rule import Rule


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


HEADER = Row((Cell("Code"), Cell("Rule"), Cell("Flags"), Cell("Default")))


def _row(rule: Rule) -> Row:
    return Row(
        (
            Cell(rule.code.root),
            Cell(rule.name.root),
            Cell(rule.example.root),
            Cell("on" if rule.on_by_default else "off"),
        )
    )


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


def table() -> Table:
    rows = Arr([HEADER, *Arr(RULES).map(_row)])
    widths = _widths(rows)
    return Table("\n".join(rows.map(lambda row: _rendered(row, widths).root)))


if __name__ == "__main__":
    print(table().root)  # noqa: T201
