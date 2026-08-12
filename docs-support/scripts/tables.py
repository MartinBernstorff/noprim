import json
import sys
from enum import Enum
from typing import get_args

from iterpy import Arr
from pydantic import BaseModel, ConfigDict, RootModel
from pydantic.fields import FieldInfo

from noprim_core.config import NamePatterns
from noprim_core.rules.code import Selectors
from noprim_core.rules.registry import RULES
from noprim_core.rules.rule import Rule
from noprim_core.settings import (
    AllowedNames,
    DeniedNames,
    FieldName,
    PathOverride,
    PathOverrides,
    PathPatterns,
    Settings,
    description,
    key_name,
)
from noprim_types.replacements import ReplacementTable
from noprim_types.verdict import Verdict


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
            Cell(rule.in_preset.value if rule.in_preset is not None else "none"),
        )
    )


def rules() -> Table:
    header = Row((Cell("Code"), Cell("Rule"), Cell("Flags"), Cell("Preset")))
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


_TYPES = {
    AllowedNames: "list of type names",
    DeniedNames: "list of type names",
    PathPatterns: "list of globs",
    NamePatterns: "list of globs",
    Selectors: "list of rule codes",
    Verdict: "true | false",
    PathOverrides: "list of tables",
}


class UnlabelledTypeError(ValueError):
    def __init__(self, name: FieldName) -> None:
        super().__init__(
            f"config key with a type the table cannot name: {name.root}. "
            "Give it a label in _TYPES."
        )


def _declared(field: FieldInfo) -> type:
    candidates = Arr(get_args(field.annotation) or (field.annotation,)).filter(
        lambda candidate: candidate is not type(None)
    )
    return candidates.to_list()[0]


def _type(name: FieldName, field: FieldInfo) -> Cell:
    declared = _declared(field)
    if issubclass(declared, Enum):
        return Cell(" | ".join(f'"{member.value}"' for member in declared))
    if declared not in _TYPES:
        raise UnlabelledTypeError(name)
    return Cell(_TYPES[declared])


def _default(field: FieldInfo) -> Cell:
    if field.is_required():
        return Cell("required")
    # Unset, not empty: no select means the preset's rules rather than no rules.
    if field.default is None:
        return Cell("unset")
    if isinstance(field.default, BaseModel):
        return Cell(json.dumps(field.default.model_dump()))
    return Cell(json.dumps(field.default))


def _key_row(model: type[BaseModel], name: FieldName) -> Row:
    field = model.model_fields[name.root]
    return Row(
        (
            Cell(key_name(name).root),
            _type(name, field),
            _default(field),
            Cell(description(model, name).root),
        )
    )


def _keys(model: type[BaseModel]) -> Table:
    header = Row((Cell("Key"), Cell("Type"), Cell("Default"), Cell("Description")))
    ordered = sorted(
        model.model_fields, key=lambda name: key_name(FieldName(name)).root
    )
    rows = Arr(ordered).map(lambda name: _key_row(model, FieldName(name)))
    return _aligned(Arr([header, *rows]))


def settings() -> Table:
    return _keys(Settings)


def overrides() -> Table:
    return _keys(PathOverride)


TABLES = {
    TableName("rules"): rules,
    TableName("denied"): denied,
    TableName("settings"): settings,
    TableName("overrides"): overrides,
}


if __name__ == "__main__":
    wanted = TableName(sys.argv[1])
    if wanted not in TABLES:
        sys.exit(f"no such table: {wanted.root}")
    print(TABLES[wanted]().root)  # noqa: T201
