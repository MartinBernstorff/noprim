# noprim

CLI that lints Python for primitive-typed function parameters.

## Layout

- `packages/noprim-core/` (`noprim_core`) — pure linting logic and value objects. No CLI, no I/O.
- `packages/noprim-io/` (`noprim_io`) — path walking and file reading.
- `packages/noprim-cli/` (`noprim_cli`) — Typer app. Argument parsing and output formatting only.

Dependencies point one way: `noprim-core` <- `noprim-io` <- `noprim-cli`. Enforced by `tach` (`moon run :modularity`).

## Python

- **Never take primitives as function parameters.** Wrap them in a Pydantic `RootModel` — a `str` says nothing about what it is; `UserId` does. This is what the project lints for, so dogfood it.
- **No `tests/` folder.** Tests live beside the code as `test_<module>.py` — a test you can see is a test you maintain.
- **Never maintain `__all__`.** Import directly; the export list is a second source of truth that drifts.
- **Prefer iterators over manual for-loops.** Use `iterpy`: `Arr([1,2,3]).map(lambda x: x+1).filter(lambda x: x>2).to_list()` — pipelines read top-to-bottom without accumulator state.
- **Avoid constants.** Before defining one, ask whether it should be an argument from the caller — a constant is a decision frozen at the wrong layer.
- **Default to no comments.** If code needs a comment to be understood, fix the code. When you must, one line on *why* (constraint, invariant, bug), never *what*. No docstrings.

## Moon

Always run tasks through moon, never the tool directly: `moon run :test`, not `pytest`. Moon resolves task dependencies and caches aggressively.

| Task | Does |
| --- | --- |
| `moon run :test` | pytest |
| `moon run :lint` | ruff check |
| `moon run :lint-fix` | ruff check --fix |
| `moon run :format` | ruff format |
| `moon run :format-check` | ruff format --check |
| `moon run :typecheck` | pyrefly |
| `moon run :modularity` | tach check + tach check-external |
| `moon run :actionlint` | actionlint |

## Tooling

- Tool settings live in each tool's own file — `ruff.toml`, `pyrefly.toml`, `tach.toml`, `pytest.toml` — **not** in `pyproject.toml`. Keeps config where the tool's docs say to look.
- Commits are validated automatically by lefthook pre-commit hooks (`lefthook.yml`). Install with `lefthook install`.
