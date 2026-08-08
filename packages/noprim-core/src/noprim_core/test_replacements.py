from noprim_core.config import DeniedTypes
from noprim_types.replacements import ReplacementTable, TypeName


def test_every_denied_type_has_a_recommended_replacement() -> None:
    denied = frozenset(TypeName(name) for name in DeniedTypes.default().root)

    assert ReplacementTable.default().covered == denied
