# noprim

CLI that lints Python for primitive-typed function parameters.

## Layout

- `packages/noprim-types/` (`noprim_types`) — the shipped utility types. Depends on nothing but pydantic, and is the one package with a public import surface.
- `packages/noprim-core/` (`noprim_core`) — pure linting logic and value objects, plus the settings schema and per-path resolution. No CLI, no I/O.
- `packages/noprim-io/` (`noprim_io`) — path walking, file reading, and config discovery.
- `packages/noprim-cli/` (`noprim_cli`) — Typer app. Argument parsing and output formatting only.

`noprim_cli.render` is the whole of the formatting: `render(outcome, elapsed, options)` turns a run into a `Rendered` — `stdout`, `stderr`, `exit_code` — and `main._emit` is the only thing that echoes or exits. Wording, pluralisation, sort order and exit codes are therefore tested in `test_render.py` against a returned value; `test_main.py` only checks that flags reach the right place.

## Reporting

`RenderOptions` carries two independent axes, and `render` crosses them: **what** to
print (`--statistics` counts instead of one line per violation) and **how**
(`--output-format json`). All four combinations are reachable, so neither flag has to
know about the other.

The exit code is computed from the report, never from what was printed — otherwise
`--statistics` grouping away every violation, or a JSON document that is one non-empty
line whatever it contains, would silently change it. For the same reason a file that
would not parse keeps its own line under `--statistics`, and its own `errors` entry in
the JSON: no count can express it, and its violations are missing from every count.

`--group-by` names the axes `--statistics` counts along: `rule`, `type`, `name` or
`path`, comma-separated and repeatable. `GroupAxis`' values *are* the JSON keys, so
`_json_group` splats them and a new axis needs a `GroupAxis` member, a case in
`_axis_value` and a field on `JsonGroup`. Groups sort descending by count and then by
their axis values, because equal counts otherwise come out in walk order and a diff of
two runs is noise.

`_axes` rejects rather than shrugs, three ways: an unknown axis, no axis at all
(`--group-by ""`), and the same axis twice — the last because the axis names are JSON
keys, so a repeat that text prints as two columns would silently collapse to one. And
`--group-by` without `--statistics` is rejected rather than ignored. `GroupAxes.default()`
is the one place the default axis lives; `RenderOptions` and `check` both reach for it.

JSON goes through pydantic models (`JsonReport`, `JsonStatistics`) rather than
`json.dumps` over dicts: every field is a `RootModel`, which serialises as its root, so
the shape is declared in one place and dogfoods the deny-list.

Dependencies point one way: `noprim-types` <- `noprim-core` <- `noprim-io` <- `noprim-cli`. Enforced by `tach` (`moon run :modularity`).

Four modules, **one distribution**. The root `pyproject.toml` is the only publishable package (`noprim`); it owns the `noprim` script and vendors every module dir into a single wheel. It uses hatchling rather than `uv_build` because `uv_build`'s `module-root` is one directory and cannot reach across `packages/*`.

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

A Typer command's `bool` parameters are the framework's rather than the author's — click
decides flag-ness from the annotation being literally `bool`, so there is no other
spelling of a bare flag — and `exempt-typer-args` covers them, on by default. It
suppresses rather than skips, like pytest ownership, because a config key can turn it
off.

Only `bool`, deliberately. A `str` or `Path` option *can* become an `enum.Enum` or a
`typer.Option(parser=...)`, so exempting it would wave through a case with a real fix.
Those report instead, and `PrimitiveParameter.message` names the two alternatives — which
is why `Violation` carries `owner`: it is the one thing a rule needs from the walk that
the surface and the annotation do not say. It stays out of the baseline key, so the
wording can change without invalidating anyone's baseline. Only parameters — a command's
return type is still the author's.

Unlike `@override` it is matched on the *attribute* rather than the name alone —
`<anything>.command`, never a bare `@command` — because `command` and `callback` are
names another library could plausibly export, and typer never spells it that way. It
still misses a module-level `DEPLOY_ENV = Annotated[str, typer.Option(...)]` used as
`env: DEPLOY_ENV`, but so does every rule: the use site names the alias and the
definition is an assignment no surface covers.

`@override` is the exemption rather than a list of method names: a name glob cannot tell
a Django `Model.save` override from a domain `delete()` that should stay checked, and if
the base method disappears the type checker errors, so the exemption cannot rot. It is
matched on the decorator's name alone, without resolving imports.

`Site.owner` is the one fact on a site that no rule reads: who chose the annotation.
It is there because the walk is the only place that can see it — pytest ownership is
the enclosing function's name and decorators plus the module's filename — and
`Suppressions` would otherwise have to walk the tree a second time to re-derive it.

## Suppressions

Rules fire unconditionally; `noprim_core.suppression` is the one place that decides
whether a violation is reported, and returns `(reported, suppressed)` rather than a
silently shortened list. Each suppressed violation names its `SuppressionReason` —
`comment`, `file-comment`, `ignored-name`, `inner-class`, `pytest`, `typer` or `baseline` — so "why was this
not reported?" has a single answer, and the summary can count them all rather than just
the baseline's. Suppression is not a rule.

`# noprim: ignore` covers every code on its line; `# noprim: ignore[NOPRIM002]` covers
the ones it names. The comment must end the line, so a suppression cannot hide behind
trailing prose.

`# noprim: ignore-file` is the same grammar at module `Scope`, and only counts in the
leading comment block — the comments before the first code token, which is the only
part of a file that speaks for the file rather than for a line. It suppresses rather
than skips: the file is still walked, still counted as checked, and its violations
still join the suppressed count. Wanting the file not to be read at all is what
`exclude` is for.

Both comment parsers take a token stream rather than a `SourceCode`, so `tokens_in` runs
once per file and the line-level and file-level readings cannot disagree about what a
token is.

`SuppressionReason.requested()` is what the summary counts: a framework owning a
signature — pytest's tests and fixtures, typer's commands — is structural, like a dunder
method being exempt, and counting those would swamp the suppressions the author actually
wrote. The baseline suppresses later,
at the CLI, because keying an entry needs a path relative to the repo — but it hands
back the same `SuppressedViolation`s and joins the same count.

## Settings

The schema (`noprim_core.settings`) is one `Settings` model: `allow`, `deny`,
`exclude`, the `ignore-*-names` keys it shares with an override through `NameKeys`, and
`per-path` overrides. Resolution — unioning every matching override on top of the
top-level lists into a `CheckConfig` — is pure logic over a relative path,
so it lives in core alongside `pathspec`. `noprim_io.settings` does the I/O half:
walking up for the file and reading it through `pydantic-settings`' TOML sources.

`preset` names the base selection the other rule keys work on top of, as pyrefly's does:
`select` replaces it, `extend-select` adds and `ignore` subtracts. Only `default` and
`all` exist, because a rule is either on by default or it is not — there is no third
tier for a `strict` between them to name.

A name-matching key comes in three: `ignore-param-names` and `ignore-attribute-names`
name one surface each, and `ignore-names` is the pair of them, kept because it predates
the split. A surface is the axis that matters — a framework dictating `value` as a
parameter says nothing about a class attribute of that name — and there is no third key
for returns, which carry the function's name rather than one of their own. All three
take gitignore patterns rather than exact names, matched by `pathspec` against the
qualname's leaf, and all three are override keys too.

They suppress by surface, not by code, so ignoring a parameter name silences every rule
that fires on a parameter — `NOPRIM004` as well as `NOPRIM001`. The author is saying the
name is not theirs to choose, which is true of the whole annotation or none of it.

`ignore-inner-classes` names a *place* rather than a surface, so it is a fourth key —
also an override key — and deliberately not part of `ignore-names`: it covers everything
inside a class nested in another class, which is what a framework-dictated `class Meta`
is. Only a class-in-a-class matches. A module-level class of that name is one the author
chose, and a class defined in a function is not the framework's block either; only the
walk can tell those apart, so `Enclosing` carries the chain of enclosing *classes* and
`ClassChain.inner()` drops the outermost. Like pytest ownership it suppresses rather than
skips, so the block still shows up in the `N suppressed` count.

An override's patterns are appended to the top level's and compiled as one spec, so
gitignore's last-match-wins holds across the join: a per-path `!value` re-includes a name
the top level ignored, which is how a directory says the framework's excuse stops here.

An override carries `allow`, `deny`, `ignore`, the `ignore-*-names` keys and
`ignore-inner-classes`. `ignore`
names rule codes and only ever *subtracts* — there is deliberately no per-path `select`,
so the top-level selection stays the ceiling and `--select NOPRIM001` still means only
`NOPRIM001` ran.
It deselects rather than suppresses: the rule never fires, so nothing reaches
`Suppressions` and nothing is counted, exactly like the top-level `ignore`.

Three things keep this honest, and all will fail loudly if you break them:

- **A flag overrides the config key with its own name.** `check` hands its parameters to `_overrides`, which keeps the ones `Settings.model_fields` knows and lets pydantic coerce the raw `list[str]` into the field's type — so a new setting needs a Typer annotation and nothing else. The name is the wiring, and `test_every_flag_that_is_not_run_mode_names_a_config_key` is what stops a mistyped parameter from becoming a flag that silently does nothing.
- **`LoadedSettings.anchor` is `None` when no config was found.** Patterns then have no directory to hang off, and the walk falls back to the target's repo root — which is what makes `--exclude` behave the same with and without a config file.
- **`_validated_entry` is the one seam that locates a per-path complaint.** Pydantic attributes an after-validator error to `Settings`, not to the entry, so every complaint raised there is re-wrapped in `PerPathError` carrying the block's own patterns. Validate a new override key inside `_validated_entry` and it is located for free; validate it anywhere else and the user gets a message with no way back to the block. Schema-level rejections — an unrecognised key under `extra="forbid"` — never reach the validator and are located by position instead.

## Python

- **Never take primitives as function parameters.** Wrap them in a Pydantic `RootModel` — a `str` says nothing about what it is; `UserId` does. This is what the project lints for, so dogfood it.
- **No `tests/` folder.** Tests live beside the code as `test_<module>.py` — a test you can see is a test you maintain.
- **`noprim_types` is the library others import.** `Verdict`, `EnsuredDir` and
  `NonBlankString` live there — only what pydantic lacks, which is why there is no
  `ExistingDir` beside `DirectoryPath`. `ReplacementTable.default()` maps every denied
  type to what to use instead, and `test_replacements.py` in core asserts its keys are
  *exactly* `DeniedTypes.default()`: a new denied type fails a test until someone writes
  the recommendation. Keep the module free of `iterpy` — `Verdict.any` takes an
  `Iterable` for that reason — so importing it costs a user only pydantic.
- **Never maintain `__all__`, and keep every `__init__.py` empty.** A wall of `from x import Y as Y` is an `__all__` in disguise: a second source of truth that drifts, and a sorted list every branch inserts into. Import from the defining module (`from noprim_core.violation import Violation`); `tach` is what enforces the layer boundary. `noprim_types/__init__.py` is the single
  exception, carved out in `moon run :modularity`: a public surface is what an `__all__`
  is *for*, and `test_public_surface.py` fails when it drifts from the classes the
  package defines.
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

## Releasing

The version is not written down anywhere — `hatch-vcs` derives it from the git tag, and python-semantic-release derives the tag from commit messages. So **the PR title is the release note**, and it must be a [conventional commit](https://www.conventionalcommits.org/):

| Prefix | Effect below 1.0.0 |
| --- | --- |
| `fix: …` | patch — `0.3.1` → `0.3.2` |
| `feat: …` | minor — `0.3.1` → `0.4.0` |
| `feat!: …` or a `BREAKING CHANGE:` footer | minor, until 1.0.0 (`major_on_zero = false`) |
| `chore: …`, `docs: …`, `refactor: …`, `test: …`, `ci: …` | no release |

PRs are squash-merged, so the PR title becomes the commit subject on main and is the only thing the parser reads — an individual commit inside the branch is never parsed. Nothing enforces this; a non-conventional title means `release` runs, finds no releasable change, and exits without publishing.

Merging to main runs `ci`; on success, `release` tags, creates the GitHub Release, builds, and publishes to PyPI via trusted publishing (no API token). To cut a release from an unchanged main, dispatch `release` manually.

Publishing requires a trusted publisher registered at [pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing/) — owner `MartinBernstorff`, repository `noprim`, workflow `release.yml`, no environment. A one-time manual step, since only a logged-in human can do it.
