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

A rule is one module under `noprim_core/rules/`, holding one class that **inherits
`Rule`** and declares its `code`, whether it is `on_by_default`, and
`applies(site, config) -> Verdict` — plus a table-driven test beside it over `Site`
values. `rules/registry.py` lists them in one tuple; adding a rule is a new file and
one line there, so two rules being added at once touch disjoint files.

Inherit `Rule` explicitly rather than matching it structurally: a forgotten `code` or
a mistyped `applies` then fails at the class itself, instead of silently at runtime or
far away at the registry's annotation. `Rule` stays a `Protocol`, so it is still
satisfiable structurally where that is useful. Its `code` and `on_by_default` are
properties for the same reason — a subclass that never sets a plain declared attribute
typechecks clean, one that never implements a property does not.

`Rule.message` has a body: the generic "…is annotated…" text, keyed on surface. A rule
only defines `message` when it wants different wording, and can reach the generic
version with `super().message(violation)`.

Two tests in `test_registry.py` keep the tuple honest — every `Rule` subclass defined
under `rules/` must appear in `RULES`, so a finished rule cannot sit there doing
nothing, and a module may define at most one of them.

Codes number by smell *and* by surface (`NOPRIM001` primitive parameter, `NOPRIM002`
primitive return, ...), because the surface is the axis people actually want to turn
off: a codebase can drown in return types while its parameters are fine. Both halves
are a public commitment — baselines and `# noprim: ignore[NOPRIM002]` encode them.

The pipeline is: walk to `Site`s, ask each selected rule at every site, then hand the
violations to `Suppressions`. `Site` carries raw syntactic facts only — no
rule-specific booleans. Anything the author does not choose (dunder methods,
`RootModel` bodies, overload implementations, `@override` methods) is exempt during the
walk and never becomes a site.

`@override` is matched on the decorator's name only — `override`, `typing.override`,
`typing_extensions.override` — with no import resolution. It is deliberately the
exemption rather than a list of method names: a name glob cannot tell a Django
`Model.save` override from a domain `delete()` that should stay checked, and if the base
method disappears the type checker errors, so the exemption cannot rot.

`Site.owner` is the one fact on a site that no rule reads: who chose the annotation.
It is there because the walk is the only place that can see it — pytest ownership is
the enclosing function's name and decorators plus the module's filename — and
`Suppressions` would otherwise have to walk the tree a second time to re-derive it.

## Suppressions

Rules fire unconditionally; `noprim_core.suppression` is the one place that decides
whether a violation is reported, and returns `(reported, suppressed)` rather than a
silently shortened list. Each suppressed violation names its `SuppressionReason` —
`comment`, `ignored-name`, `pytest` or `baseline` — so "why was this not reported?"
has a single answer, and the summary can count them all rather than just the
baseline's. Suppression is not a rule.

`# noprim: ignore` covers every code on its line; `# noprim: ignore[NOPRIM002]` covers
the ones it names. The comment must end the line, so a suppression cannot hide behind
trailing prose.

`SuppressionReason.requested()` is what the summary counts: pytest owning a test or
fixture signature is structural, like a dunder method being exempt, and counting those
would swamp the suppressions the author actually wrote. The baseline suppresses later,
at the CLI, because keying an entry needs a path relative to the repo — but it hands
back the same `SuppressedViolation`s and joins the same count.

## Settings

The schema (`noprim_core.settings`) is one `Settings` model: `allow`, `deny`,
`exclude`, and `per-path` overrides. Resolution — unioning every matching override on
top of the top-level lists into a `CheckConfig` — is pure logic over a relative path,
so it lives in core alongside `pathspec`. `noprim_io.settings` does the I/O half:
walking up for the file and reading it through `pydantic-settings`' TOML sources.

`preset` names the base selection the other rule keys work on top of, as pyrefly's does:
`select` replaces it, `extend-select` adds and `ignore` subtracts. Only `default` and
`all` exist, because a rule is either on by default or it is not — there is no third
tier for a `strict` between them to name.

An override carries `allow`, `deny` and `ignore`. `ignore` names rule codes and only
ever *subtracts* — there is deliberately no per-path `select`, so the top-level
selection stays the ceiling and `--select NOPRIM001` still means only `NOPRIM001` ran.
It deselects rather than suppresses: the rule never fires, so nothing reaches
`Suppressions` and nothing is counted, exactly like the top-level `ignore`.

Three things keep this honest, and all will fail loudly if you break them:

- **A flag overrides the config key with its own name.** `check` hands its parameters to `_overrides`, which keeps the ones `Settings.model_fields` knows and lets pydantic coerce the raw `list[str]` into the field's type — so a new setting needs a Typer annotation and nothing else. The name is the wiring, and `test_every_flag_that_is_not_run_mode_names_a_config_key` is what stops a mistyped parameter from becoming a flag that silently does nothing.
- **`LoadedSettings.anchor` is `None` when no config was found.** Patterns then have no directory to hang off, and the walk falls back to the target's repo root — which is what makes `--exclude` behave the same with and without a config file.
- **`_validated_entry` is the one seam that locates a per-path complaint.** Pydantic attributes an after-validator error to `Settings`, not to the entry, so every complaint raised there is re-wrapped in `PerPathError` carrying the block's own patterns. Validate a new override key inside `_validated_entry` and it is located for free; validate it anywhere else and the user gets a message with no way back to the block. Schema-level rejections — an unrecognised key under `extra="forbid"` — never reach the validator and are located by position instead.

## Python

- **Never take primitives as function parameters.** Wrap them in a Pydantic `RootModel` — a `str` says nothing about what it is; `UserId` does. This is what the project lints for, so dogfood it.
- **No `tests/` folder.** Tests live beside the code as `test_<module>.py` — a test you can see is a test you maintain.
- **Never maintain `__all__`, and keep every `__init__.py` empty.** A wall of `from x import Y as Y` is an `__all__` in disguise: a second source of truth that drifts, and a sorted list every branch inserts into. Import from the defining module (`from noprim_core.violation import Violation`); `tach` is what enforces the layer boundary.
- **A `Verdict` never unwraps.** It defines `__bool__`, so it reads as the answer it is: `if site.covers(v):`, `.filter(rule.on_by_default)`, `assert _raised(...)`. `and_`, `or_`, `negated` and `Verdict.any` compose several into one without leaving `Verdict` terms. Neither `.root` nor `bool(v)` should appear at a call site — the only `.root` is inside `Verdict` itself. Two settings buy this and are load-bearing: `implicit-bool = false` in `pyrefly.toml`, and `iterpy>=1.15`, whose `Arr.filter` takes a `Callable[[T], object]`.
- **Prefer iterators over manual for-loops.** Use `iterpy`: `Arr([1,2,3]).map(lambda x: x+1).filter(lambda x: x>2).to_list()` — pipelines read top-to-bottom without accumulator state.
- **Avoid constants.** Before defining one, ask whether it should be an argument from the caller — a constant is a decision frozen at the wrong layer.
- **Default to no comments.** If code needs a comment to be understood, fix the code. When you must, one line on *why* (constraint, invariant, bug), never *what*. No docstrings.

## Moon

Always run tasks through moon, never the tool directly: `moon run :test`, not `pytest`. Moon resolves task dependencies and caches aggressively.

**A task's inputs must include the sources it reads across a package boundary.** `dependsOn` orders projects; it does not make the upstream package's files an input, so a downstream `test` or `typecheck` would replay a stale cache after an upstream edit — a test that no longer holds still reports a pass. Each downstream package carries an `upstream` file group for exactly this, listed as an input on `test` and `typecheck`. `lint` and `format` are per-file and do not need it. A new package means a new `upstream` group.

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
