import importlib
import inspect
import pkgutil

import pytest

import noprim_types
from noprim_types.replacements import TypeName


def _classes_defined_in_the_package() -> frozenset[TypeName]:
    modules = [
        importlib.import_module(f"noprim_types.{found.name}")
        for found in pkgutil.iter_modules(noprim_types.__path__)
        if not found.name.startswith("test_")
    ]
    return frozenset(
        TypeName(name)
        for module in modules
        for name, value in vars(module).items()
        if not name.startswith("_")
        and inspect.isclass(value)
        and value.__module__ == module.__name__
    )


@pytest.mark.parametrize("exported", noprim_types.__all__)
def test_every_exported_name_is_importable(exported: str) -> None:
    assert inspect.isclass(getattr(noprim_types, exported))


def test_all_lists_every_class_the_package_defines() -> None:
    assert frozenset(TypeName(name) for name in noprim_types.__all__) == (
        _classes_defined_in_the_package()
    )
