from pathlib import Path

import pytest
from pydantic import RootModel

from noprim_core.config import DeniedTypes
from noprim_core.settings import RelativePath
from noprim_io.check import CheckPaths, DiscoveryConfig, check_paths
from noprim_io.paths import ExistingDirectory
from noprim_io.settings import load_settings


class ConfigText(RootModel[str]):
    pass


class DeniedSet(RootModel[frozenset[str]]):
    pass


class LeafNames(RootModel[tuple[str, ...]]):
    pass


def _repo(root: ExistingDirectory) -> ExistingDirectory:
    (root.root / ".git").mkdir()
    return root


def _written(root: ExistingDirectory, body: ConfigText) -> ExistingDirectory:
    _ = (root.root / "noprim.toml").write_text(body.root)
    return root


def _denied(directory: ExistingDirectory) -> DeniedSet:
    return DeniedSet(
        load_settings(directory).settings.resolve(RelativePath("a.py")).denied.root
    )


class Subpath(RootModel[str]):
    pass


def _under(root: ExistingDirectory, part: Subpath) -> ExistingDirectory:
    nested = root.root / part.root
    nested.mkdir(parents=True)
    return ExistingDirectory(nested)


_DENY_ENUM = ConfigText('deny = ["Enum"]\n')


def test_no_config_anywhere_leaves_the_defaults_alone(tmp_path: Path) -> None:
    denied = _denied(_repo(ExistingDirectory(tmp_path)))
    assert denied == DeniedSet(DeniedTypes.default().root)


def test_a_noprim_toml_beside_the_code_is_used(tmp_path: Path) -> None:
    root = _written(_repo(ExistingDirectory(tmp_path)), _DENY_ENUM)
    assert "Enum" in _denied(root).root


def test_a_pyproject_tool_table_is_used(tmp_path: Path) -> None:
    root = _repo(ExistingDirectory(tmp_path))
    _ = (tmp_path / "pyproject.toml").write_text('[tool.noprim]\ndeny = ["Enum"]\n')
    assert "Enum" in _denied(root).root


def test_a_config_in_an_ancestor_is_found(tmp_path: Path) -> None:
    _ = _written(_repo(ExistingDirectory(tmp_path)), _DENY_ENUM)
    assert (
        "Enum"
        in _denied(_under(ExistingDirectory(tmp_path), Subpath("packages/app"))).root
    )


def test_the_nearest_config_wins(tmp_path: Path) -> None:
    _ = _written(_repo(ExistingDirectory(tmp_path)), _DENY_ENUM)
    nested = _written(
        _under(ExistingDirectory(tmp_path), Subpath("app")),
        ConfigText('deny = ["Flag"]\n'),
    )

    denied = _denied(nested).root

    assert "Flag" in denied
    assert "Enum" not in denied


def test_a_pyproject_without_the_table_does_not_stop_the_walk(tmp_path: Path) -> None:
    _ = _written(_repo(ExistingDirectory(tmp_path)), _DENY_ENUM)
    nested = _under(ExistingDirectory(tmp_path), Subpath("app"))
    _ = (nested.root / "pyproject.toml").write_text('[project]\nname = "app"\n')

    assert "Enum" in _denied(nested).root


def test_noprim_toml_wins_over_a_sibling_pyproject(tmp_path: Path) -> None:
    root = _written(_repo(ExistingDirectory(tmp_path)), _DENY_ENUM)
    _ = (tmp_path / "pyproject.toml").write_text('[tool.noprim]\ndeny = ["Flag"]\n')

    denied = _denied(root).root

    assert "Enum" in denied
    assert "Flag" not in denied


def test_the_walk_stops_at_the_repo_root(tmp_path: Path) -> None:
    _ = _written(ExistingDirectory(tmp_path), _DENY_ENUM)
    inner = _repo(_under(ExistingDirectory(tmp_path), Subpath("vendored")))

    assert "Enum" not in _denied(inner).root


def test_without_a_repo_only_the_starting_directory_is_read(tmp_path: Path) -> None:
    root = _written(ExistingDirectory(tmp_path), _DENY_ENUM)

    assert (
        "Enum" not in _denied(_under(ExistingDirectory(tmp_path), Subpath("app"))).root
    )
    assert "Enum" in _denied(root).root


def test_globs_are_anchored_at_the_directory_holding_the_config(tmp_path: Path) -> None:
    root = _written(
        _repo(ExistingDirectory(tmp_path)),
        ConfigText('[[per-path]]\npaths = ["legacy/**"]\nallow = ["str"]\n'),
    )
    nested = _under(ExistingDirectory(tmp_path), Subpath("legacy"))

    assert load_settings(nested).anchor == root


def _tree(root: ExistingDirectory, body: ConfigText) -> DiscoveryConfig:
    _ = _written(_repo(root), body)
    for area in ("domain", "test_infra"):
        area_root = _under(root, Subpath(area))
        _ = (area_root.root / "a.py").write_text("def f(x: str) -> None: ...\n")
    return DiscoveryConfig(settings=load_settings(root))


def _violations(paths: CheckPaths, config: DiscoveryConfig) -> LeafNames:
    report = check_paths(paths, config)
    return LeafNames(tuple(sorted(v.qualname.leaf().root for v in report.violations)))


_LENIENT_TEST_INFRA = ConfigText(
    '[[per-path]]\npaths = ["test_infra/**"]\nallow = ["str"]\n'
)
_EXCLUDE_TEST_INFRA = ConfigText('exclude = ["test_infra/**"]\n')
_IGNORE_RULE_IN_TEST_INFRA = ConfigText(
    '[[per-path]]\npaths = ["test_infra/**"]\nignore = ["NOPRIM001"]\n'
)


def test_an_override_ignores_a_rule_only_for_the_paths_it_matches(
    tmp_path: Path,
) -> None:
    config = _tree(ExistingDirectory(tmp_path), _IGNORE_RULE_IN_TEST_INFRA)

    assert _violations(CheckPaths((tmp_path,)), config) == LeafNames(("x",))


def test_an_override_relaxes_only_the_paths_it_matches(tmp_path: Path) -> None:
    config = _tree(ExistingDirectory(tmp_path), _LENIENT_TEST_INFRA)

    assert _violations(CheckPaths((tmp_path,)), config) == LeafNames(("x",))


def test_an_override_applies_to_an_explicitly_named_file(tmp_path: Path) -> None:
    config = _tree(ExistingDirectory(tmp_path), _LENIENT_TEST_INFRA)
    target = tmp_path / "test_infra" / "a.py"

    assert _violations(CheckPaths((target,)), config) == LeafNames(())


def test_an_override_matches_the_same_file_named_two_ways(tmp_path: Path) -> None:
    config = _tree(ExistingDirectory(tmp_path), _LENIENT_TEST_INFRA)
    target = tmp_path / "test_infra" / "a.py"

    assert _violations(CheckPaths((target.resolve(),)), config) == _violations(
        CheckPaths((target,)), config
    )


def test_config_exclude_skips_files_while_walking(tmp_path: Path) -> None:
    config = _tree(ExistingDirectory(tmp_path), _EXCLUDE_TEST_INFRA)

    assert _violations(CheckPaths((tmp_path,)), config) == LeafNames(("x",))


def test_config_exclude_does_not_apply_to_an_explicitly_named_file(
    tmp_path: Path,
) -> None:
    config = _tree(ExistingDirectory(tmp_path), _EXCLUDE_TEST_INFRA)
    target = tmp_path / "test_infra" / "a.py"

    assert _violations(CheckPaths((target,)), config) == LeafNames(("x",))


def test_a_broken_sibling_pyproject_is_not_read(tmp_path: Path) -> None:
    root = _written(_repo(ExistingDirectory(tmp_path)), _DENY_ENUM)
    _ = (tmp_path / "pyproject.toml").write_text("deny = [\n")

    assert "Enum" in _denied(root).root


def test_config_exclude_applies_to_a_relative_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _tree(ExistingDirectory(tmp_path), _EXCLUDE_TEST_INFRA)
    monkeypatch.chdir(tmp_path)

    assert _violations(CheckPaths((Path(),)), config) == LeafNames(("x",))
