# noprim

CLI that lints Python for primitive-typed function parameters.

## Layout

- `packages/noprim-core/` (`noprim_core`) — pure linting logic and value objects, plus the settings schema and per-path resolution. No CLI, no I/O.
- `packages/noprim-io/` (`noprim_io`) — path walking, file reading, and config discovery.
- `packages/noprim-cli/` (`noprim_cli`) — Typer app. Argument parsing and output formatting only.

`noprim_cli.render` is the whole of the formatting: `render(outcome, elapsed, options)` turns a run into a `Rendered` — `stdout`, `stderr`, `exit_code` — and `main._emit` is the only thing that echoes or exits. Wording, pluralisation, sort order and exit codes are therefore tested in `test_render.py` against a returned value; `test_main.py` only checks that flags reach the right place.

Dependencies point one way: `noprim-core` <- `noprim-io` <- `noprim-cli`. Enforced by `tach` (`moon run :modularity`).

Three modules, **one distribution**. The root `pyproject.toml` is the only publishable package (`noprim`); it owns the `noprim` script and vendors all three module dirs into a single wheel. It uses hatchling rather than `uv_build` because `uv_build`'s `module-root` is one directory and cannot reach across `packages/*`.

The per-package `pyproject.toml` files are **not** distributions — they have no `[build-system]` and are never built. They exist so `tach check-external` can enforce per-module external dependencies, which is what keeps `typer` out of `noprim-core`. Add a third-party dependency to both the module's manifest and the root's: the module's manifest satisfies `tach`, and the root's is what actually ships. Forgetting the root one usually surfaces as `moon run root:smoke` failing, though a lazily-imported dependency can slip past it.

## Baselines

`noprim check --baseline .noprim.json` suppresses violations recorded in that file, writing it when it does not yet exist; `--write-baseline` refreshes an existing one. Entries key on `(file, code, surface, qualname, annotation)` — never a line number — so they survive edits that move code around. The `code` is what keeps two rules firing on one annotation as two entries; it arrived in baseline version 2, and a version-1 file is rejected with a note to rerun with `--write-baseline`.

**Check the baseline into git.** It is shared debt: a gitignored one means every developer and CI silently suppresses something different.

Once the file exists, a `check` run never writes to disk. Entries that no longer match are ignored and reported on stderr; they are pruned the next time the file is written. Prune candidates are only the files the run actually analysed, plus entries under a checked path whose file is gone — so re-baselining a subdirectory leaves the rest of the file alone, and a file that stopped parsing keeps its entries rather than losing them to a syntax error.

## Rules

A rule is one module under `noprim_core/rules/`, holding its code, whether it is on
by default, `applies(site, config) -> Verdict` and its message — plus a
table-driven test beside it over `Site` values. `rules/registry.py` lists them in one
tuple; adding a rule is a new file and one line there, so two rules being added at
once touch disjoint files.

Codes number by smell *and* by surface (`NOPRIM001` primitive parameter, `NOPRIM002`
primitive return, ...), because the surface is the axis people actually want to turn
off: a codebase can drown in return types while its parameters are fine. Both halves
are a public commitment — baselines and, later, `# noprim: ignore[NOPRIM002]` encode
them.

The pipeline is: walk to `Site`s, drop the suppressed ones, then for each site ask
each selected rule. `Site` carries raw syntactic facts only — no rule-specific
booleans. Anything the author does not choose (dunder methods, `RootModel` bodies,
overload implementations, pytest test and fixture parameters) is exempt during the
walk and never becomes a site; `# noprim: ignore` and `ignore-names` drop sites before
the rules run. Neither is a rule.

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
- **Never maintain `__all__`, and keep every `__init__.py` empty.** A wall of `from x import Y as Y` is an `__all__` in disguise: a second source of truth that drifts, and a sorted list every branch inserts into. Import from the defining module (`from noprim_core.violation import Violation`); `tach` is what enforces the layer boundary.
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
| `moon run :modularity` | tach check + tach check-external, and fails on a non-empty `__init__.py` |
| `moon run :actionlint` | actionlint |
| `moon run root:smoke` | builds the wheel, installs it into a clean venv, runs it |
| `moon run :noprim` | noprim against this repo's own source |

## Tooling

- Tool settings live in each tool's own file — `ruff.toml`, `pyrefly.toml`, `tach.toml`, `pytest.toml` — **not** in `pyproject.toml`. Keeps config where the tool's docs say to look. Packaging is the exception: `[build-system]` and `[tool.hatch.build.*]` have nowhere else to live.
- Commits are validated automatically by lefthook pre-commit hooks (`lefthook.yml`). Install with `lefthook install`.
