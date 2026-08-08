import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from iterpy import Arr
from pydantic import RootModel

import noprim_types
from noprim_core.config import DeniedTypes
from noprim_core.settings import Settings


class DocumentName(RootModel[str]):
    pass


class Markdown(RootModel[str]):
    pass


class Heading(RootModel[str]):
    pass


class InfoString(RootModel[str]):
    pass


class Names(RootModel[frozenset[str]]):
    pass


class Blocks(RootModel[tuple[Markdown, ...]]):
    pass


REPO = Path(__file__).resolve().parent.parent


def _rendered(name: DocumentName) -> Markdown:
    return Markdown((REPO / name.root).read_text())


def _section(document: Markdown, heading: Heading) -> Markdown:
    around = re.split(
        rf"^#+ {re.escape(heading.root)}$", document.root, flags=re.MULTILINE
    )
    assert len(around) == 2, f"expected exactly one '{heading.root}' heading"
    return Markdown(re.split(r"^#+ ", around[1], flags=re.MULTILINE)[0])


def _code_spans(text: Markdown) -> Names:
    return Names(frozenset(re.findall(r"`([^`\n]+)`", text.root)))


def _fenced(text: Markdown, info: InfoString) -> Blocks:
    found = re.findall(
        rf"^```{info.root}\n(.*?)^```", text.root, flags=re.MULTILINE | re.DOTALL
    )
    return Blocks(tuple(Markdown(block) for block in found))


README = DocumentName("README.md")
AGENTS = DocumentName("AGENTS.md")


# The three-way grouping in the prose is editorial and has no counterpart in code, so
# the guard is that no denied type goes unmentioned, not that the list is generated.
def test_the_deny_list_prose_names_every_denied_type() -> None:
    named = _code_spans(_section(_rendered(README), Heading("Rules")))
    assert DeniedTypes.default().root <= named.root


def test_the_types_table_names_only_exported_types() -> None:
    rows = re.findall(
        r"^\| `(\w+)` \|",
        _section(_rendered(README), Heading("Types")).root,
        flags=re.MULTILINE,
    )
    assert rows, "the Types table has no rows"
    assert set(rows) <= set(noprim_types.__all__)


@pytest.mark.parametrize("document", [README, AGENTS], ids=lambda name: name.root)
def test_no_rendered_document_carries_a_documator_marker(
    document: DocumentName,
) -> None:
    assert "[documator:" not in _rendered(document).root


def test_every_toml_block_in_the_readme_is_a_valid_config() -> None:
    blocks = _fenced(_rendered(README), InfoString("toml"))
    assert blocks.root, "the README documents no config"
    for block in blocks.root:
        _ = Settings.model_validate(tomllib.loads(block.root))


def _moon_tasks() -> Names:
    listed = subprocess.run(
        ["moon", "query", "tasks"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    )
    projects = json.loads(listed.stdout)["tasks"].values()
    return Names(
        frozenset(Arr(projects).map(lambda tasks: list(tasks.keys())).flatten())
    )


def test_the_task_table_names_only_real_moon_tasks() -> None:
    documented = set(
        re.findall(
            r"^\| `moon run [\w-]*:([\w-]+)` \|",
            _section(_rendered(AGENTS), Heading("Moon")).root,
            flags=re.MULTILINE,
        )
    )
    assert documented, "the task table has no rows"
    assert documented <= _moon_tasks().root
