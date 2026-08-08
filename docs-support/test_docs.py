import json
import re
import subprocess
from pathlib import Path

import pytest
from iterpy import Arr
from pydantic import RootModel

import noprim_types


class DocumentName(RootModel[str]):
    pass


class Markdown(RootModel[str]):
    pass


class Heading(RootModel[str]):
    pass


class Names(RootModel[frozenset[str]]):
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


README = DocumentName("README.md")
AGENTS = DocumentName("AGENTS.md")


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
