# noprim

CLI that lints Python for primitive-typed function parameters.

## Layout

- `packages/noprim-core/` (`noprim_core`) — pure linting logic and value objects, plus the settings schema and per-path resolution. No CLI, no I/O.
- `packages/noprim-io/` (`noprim_io`) — path walking, file reading, and config discovery.
- `packages/noprim-cli/` (`noprim_cli`) — Typer app. Argument parsing and output formatting only.

Dependencies point one way: `noprim-core` <- `noprim-io` <- `noprim-cli`. Enforced by `tach` (`moon run :modularity`).

Three modules, **one distribution**. The root `pyproject.toml` is the only publishable package (`noprim`); it owns the `noprim` script and vendors all three module dirs into a single wheel. It uses hatchling rather than `uv_build` because `uv_build`'s `module-root` is one directory and cannot reach across `packages/*`.

The per-package `pyproject.toml` files are **not** distributions — they have no `[build-system]` and are never built. They exist so `tach check-external` can enforce per-module external dependencies, which is what keeps `typer` out of `noprim-core`. Add a third-party dependency to both the module's manifest and the root's: the module's manifest satisfies `tach`, and the root's is what actually ships. Forgetting the root one usually surfaces as `moon run root:smoke` failing, though a lazily-imported dependency can slip past it.

## Baselines

`noprim check --baseline .noprim.json` suppresses violations recorded in that file, writing it when it does not yet exist; `--write-baseline` refreshes an existing one. Entries key on `(file, surface, qualname, annotation)` — never a line number — so they survive edits that move code around.

**Check the baseline into git.** It is shared debt: a gitignored one means every developer and CI silently suppresses something different.

Once the file exists, a `check` run never writes to disk. Entries that no longer match are ignored and reported on stderr; they are pruned the next time the file is written. Prune candidates are only the files the run actually analysed, plus entries under a checked path whose file is gone — so re-baselining a subdirectory leaves the rest of the file alone, and a file that stopped parsing keeps its entries rather than losing them to a syntax error.

## Settings

The schema (`noprim_core.settings`) is one `Settings` model: `allow`, `deny`,
`exclude`, and `per-path` overrides. Resolution — unioning every matching override on
top of the top-level lists into a `CheckConfig` — is pure logic over a relative path,
so it lives in core alongside `pathspec`. `noprim_io.settings` does the I/O half:
walking up for the file and reading it through `pydantic-settings`' TOML sources.

Two things keep this honest, and both will fail loudly if you break them:

- **Every config key is a CLI flag of the same name.** `test_every_config_key_has_a_flag_of_the_same_name` compares `Settings.model_fields` against `check`'s signature, so adding one without the other fails.
- **`LoadedSettings.anchor` is `None` when no config was found.** Patterns then have no directory to hang off, and the walk falls back to the target's repo root — which is what makes `--exclude` behave the same with and without a config file.

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
| `moon run root:smoke` | builds the wheel, installs it into a clean venv, runs it |
| `moon run :noprim` | noprim against this repo's own source |

## Tooling

- Tool settings live in each tool's own file — `ruff.toml`, `pyrefly.toml`, `tach.toml`, `pytest.toml` — **not** in `pyproject.toml`. Keeps config where the tool's docs say to look. Packaging is the exception: `[build-system]` and `[tool.hatch.build.*]` have nowhere else to live.
- Commits are validated automatically by lefthook pre-commit hooks (`lefthook.yml`). Install with `lefthook install`.
