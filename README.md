# noprim

A linter for Python signatures that leak primitives. A `str` parameter says nothing
about what it holds; a `UserId` does.

```console
$ noprim check .
src/billing/invoice.py:14:22: NOPRIM001 parameter "customer" is annotated "str"
src/billing/invoice.py:14:39: NOPRIM002 return type is annotated "int"
Checked 42 files in 31ms - found 2 violations
```

Exits 1 when anything is reported, 0 otherwise, and 2 when a path does not exist or
cannot be read.

## Rules

Every violation names the rule that fired, and rules are numbered by smell and by
surface — so a codebase drowning in return types can silence `NOPRIM002` without
allowing `int` everywhere.

| Code | Rule | Flags | Default |
| --- | --- | --- | --- |
| `NOPRIM001` | `primitive-parameter` | `def send(to: str) -> None` | on |
| `NOPRIM002` | `primitive-return` | `def total() -> int` | on |
| `NOPRIM003` | `primitive-attribute` | `class Order:` / `    id: str` | on |
| `NOPRIM004` | `top-type-parameter` | `def send(to: Any) -> None` | off |
| `NOPRIM005` | `top-type-return` | `def payload() -> Any` | off |
| `NOPRIM006` | `top-type-attribute` | `class Order:` / `    meta: Any` | off |
| `NOPRIM007` | `predicate-return` | `def is_ready() -> bool` | off |

`--preset` chooses which set to start from — `default` for the rules marked on above,
`all` for every rule there is. `--select` replaces that set outright,
`--extend-select` adds to it and `--ignore` subtracts, all three taking code prefixes
as ruff does. A selector that names no rule is an error.

```console
$ noprim check --ignore NOPRIM002 .          # every default rule but return types
$ noprim check --extend-select NOPRIM004 .   # the defaults, plus Any on parameters
$ noprim check --preset all .                # every rule there is
$ noprim check --preset all --ignore NOPRIM007 .   # every rule but predicates
```

An annotation can break two rules at once — `dict[str, Any]` is a primitive and a top
type — and reports once per rule, so the codes tell you which half to fix.

A denied type counts wherever it appears inside the annotation — `list[str]`,
`dict[str, UserId]` and `str | None` all count.

The deny-list covers the builtins (`int`, `str`, `float`, `bool`, `bytes`,
`bytearray`, `complex`), the stdlib value types (`Path`, `PurePath`, `UUID`,
`datetime`, `date`, `time`, `timedelta`, `Decimal`, `Fraction`) and the containers
(`list`, `dict`, `set`, `frozenset`, `tuple`). Adjust it per run with `--allow` and
`--deny`.

`Any` and `object` are not on it. They are top types, not primitives: they say the
type is unknown rather than too narrow, and `object` is the right annotation for
`**kwargs` you never inspect. That is a different smell, so it has rules of its own —
`NOPRIM004` to `NOPRIM006`, off until selected. Those rules are all or nothing, so
`--allow Any` is an error; `--deny Any` still works if you want one of them on the
deny-list by itself, reported as an ordinary primitive.

A container matches only when it is bare: `list` is reported, `list[Name]` is not,
because the annotation names a collection of a type that is already meaningful. It is
the contents that are judged, so `list[str]` is reported for the `str`.

## What is exempt

Some signatures are not the author's to choose, so noprim does not report them:

- **Dunder methods.** `__eq__` takes `object` because the data model says so.
- **`RootModel` subclass bodies.** Wrapping a primitive is the point of the pattern.
- **Overload implementations.** The stubs above them carry the real types.
- **Methods decorated `@override`.** A supertype dictated the signature, and the
  decorator says so in a form the type checker verifies. Matched on the decorator's
  name — `override`, `typing.override` or `typing_extensions.override` — so the
  exemption holds however it is imported, and unrelated names like `override_settings`
  are untouched.
- **Predicates** — functions returning a bare `bool`. A domain type around the answer
  to a yes-or-no question rarely earns its keep, so `NOPRIM002` leaves them to
  `NOPRIM007`, which is off by default. Only the bare return type is carved out: a
  `bool` parameter, attribute, `list[bool]` or `bool | None` is still reported.
- **`self` and `cls`.**
- **`Literal[...]` arguments**, which are values rather than types.
- **Parameters of pytest tests and fixtures**, in files matching `test_*.py` or
  `*_test.py`. pytest decides what a fixture injects and what `parametrize` feeds in,
  so the parameter type is not a free choice. Return types and attributes in those
  files are still checked, as are ordinary helpers that happen to live beside tests.

Anything else that is genuinely forced can be suppressed a line at a time:

```python
def check(
    quiet: Annotated[  # noprim: ignore
        bool, typer.Option("--quiet")
    ] = False,
) -> None: ...
```

The comment suppresses only the line it sits on, and must end the line. Name codes in
brackets to suppress just those — `# noprim: ignore[NOPRIM002]`, or
`# noprim: ignore[NOPRIM001, NOPRIM002]` — and leave the brackets off to suppress
every rule on the line. A code that no rule answers to suppresses nothing, so check
the spelling.

A whole module can opt out with `# noprim: ignore-file` in its leading comment block —
before the first statement, so it reads as a statement about the file rather than about
a line. It takes the same brackets: `# noprim: ignore-file[NOPRIM002, NOPRIM003]` opts
out of those two codes and leaves the rest reporting. The file is still checked and its
violations still join the suppressed count; `exclude` in the config is what stops it
being read at all.

When a framework dictates the same name everywhere — `factory_boy` hooks take `kwargs`,
`size`, `create` and `extracted` — suppressing it line by line is busywork. Skip the
name instead:

```
noprim check --ignore-names kwargs --ignore-names size .
```

`--ignore-param-names` and `--ignore-attribute-names` narrow that to one surface each,
and `--ignore-names` is the pair of them at once. The split matters where a framework
dictates a name on one surface but not the other: `django-filter` hooks take `name` and
`value` as parameters, while a class attribute called `value` is the finding it looks
like.

```
noprim check --ignore-param-names name --ignore-param-names value .
```

Every one of them matches gitignore-style globs as well as exact names, so
`--ignore-param-names '*_contains'` covers a whole family. A skipped name is skipped for
every rule on that surface, not just the primitive one — the point is that the name was
never yours to choose. A return type carries the function's name, not one of its own, so
it is never skipped this way.

Sometimes it is a whole block the framework dictates rather than one name — Django's and
django-filter's `class Meta`, whose shape is the framework's to decide. Skip the nested
class instead:

```
noprim check --ignore-inner-classes Meta .
```

Only a class inside another class matches: a module-level `class Meta`, or one defined
inside a function, is a class you wrote and stays checked. Everything inside a matching
body is skipped, however deeply nested, so the blast radius is whatever you deliberately
put in there.

## Flags

| Flag | Effect |
| --- | --- |
| `--allow NAME` | Remove a type from the deny-list. Repeatable. |
| `--deny NAME` | Add a type to the deny-list. Repeatable. |
| `--preset default\|all` | Which rules to start from before `--select`, `--extend-select` and `--ignore`. |
| `--select CODE` | Run these rule codes instead of the defaults. Prefixes count. Repeatable. |
| `--extend-select CODE` | Run these rule codes as well as the selected ones. Repeatable. |
| `--ignore CODE` | Drop these rule codes from the run. Repeatable. |
| `--ignore-names GLOB` | Skip parameters and attributes matching `GLOB`. Repeatable. |
| `--ignore-param-names GLOB` | Skip parameters matching `GLOB`. Repeatable. |
| `--ignore-attribute-names GLOB` | Skip attributes matching `GLOB`. Repeatable. |
| `--ignore-inner-classes GLOB` | Skip the body of a nested class matching `GLOB`. Repeatable. |
| `--exclude GLOB` | Skip paths while walking. Gitignore syntax, anchored at the config file's directory, or the repo root when there is no config. Repeatable. |
| `--quiet`, `-q` | Suppress the trailing summary. |
| `--statistics` | Print counts instead of one line per violation. |
| `--group-by AXIS` | Axes `--statistics` counts along: `rule`, `type`, `name`, `path`. Comma-separated, repeatable. Defaults to `rule`. |
| `--output-format text\|json` | How to print what was found. Defaults to `text`. |

Directories are walked recursively, honouring every `.gitignore` from the repo root
down. A file named explicitly on the command line is checked even if it is ignored.

## Triage

`--statistics` answers "where is the debt?" without a throwaway script over the text
output:

```console
$ noprim check --statistics --group-by rule,type --quiet .
312  NOPRIM002  str
187  NOPRIM001  str
 44  NOPRIM001  int
```

`--group-by name` is the one that usually pays: it counts the leaf name — the parameter
or attribute, or the function for a return type — so the handful of `id`, `path` and
`name` annotations that account for most of the list surface immediately.

`--output-format json` emits the whole list machine-readably, and stays valid when
there is nothing to report:

```console
$ noprim check --output-format json --quiet .
{
  "violations": [
    {
      "path": "app/users.py",
      "line": 12,
      "column": 20,
      "code": "NOPRIM001",
      "surface": "parameter",
      "name": "user_id",
      "qualname": "greet.user_id",
      "annotation": "str"
    }
  ],
  "errors": []
}
```

The two compose: `--statistics --output-format json` emits a `statistics` array whose
entries carry a `count` and one key per requested axis. Neither flag changes the exit
code — 1 when anything was found, 0 otherwise.

A file that could not be parsed keeps its own line under `--statistics`, and its own
`errors` entry in either JSON shape: no count can stand in for it, and the violations
it would have contributed are missing from every count.

## Configuration

Settings live in `noprim.toml`, or in `pyproject.toml` under `[tool.noprim]`. noprim
walks up from the working directory to the repo root and uses the first one it finds;
`noprim.toml` wins over a `pyproject.toml` beside it. A `pyproject.toml` without the
table is not a config file, so it does not stop the search.

```toml
allow = ["str"]
deny = ["Enum"]
exclude = ["generated/**"]
ignore-names = ["kwargs", "size"]
ignore-param-names = ["value", "*_contains"]
ignore-attribute-names = ["_*"]
ignore-inner-classes = ["Meta"]
preset = "all"
extend-select = ["NOPRIM004"]
ignore = ["NOPRIM002"]
```

Every key is a flag of the same name, and passing that flag replaces the key outright
rather than adding to it — `--deny Enum` ignores whatever `deny` the file set.

### Per-path overrides

One deny-list for a whole codebase is the wrong shape: the domain deserves stricter
rules than the Django layer. `per-path` entries adjust both the deny-list and the rules
that run for the paths they match.

```toml
[[per-path]]
paths = ["domain/**", "api/**"]
deny = ["Enum", "Flag"]

[[per-path]]
paths = ["test_infra/**", "django_app/**"]
allow = ["str", "int", "bool"]
ignore = ["NOPRIM002"]
ignore-param-names = ["name", "value"]
ignore-inner-classes = ["Meta"]
```

An override's name patterns are appended to the top level's, and gitignore's
last-match-wins applies across the join — so `ignore-param-names = ["!value"]` in an
override puts `value` back under the rules for the paths it matches.

Overrides carry `allow`, `deny`, `ignore`, the three `ignore-*-names` keys and
`ignore-inner-classes`.
`exclude` is not among them — it decides which files are walked at all, before any path
has a config.

Patterns use gitignore syntax, anchored at the directory holding the config, so
`test_*.py` matches at any depth and `domain/**` does not. A leading `!` re-includes, as
in a `.gitignore`, so `paths = ["**/*.py", "!src/**"]` reads "everything but `src`".
Every entry that matches a file contributes — there is no first-match or most-specific
rule — and each is applied on top of the top-level lists, so an override can relax
something the top level denied.

### Ignoring a rule for some paths

An override's `ignore` takes rule codes, exactly like the top-level key, and subtracts
them for the paths it matches. It only ever subtracts: there is no per-path `select` or
`extend-select`, so the rules named at the top level stay the ceiling on what any file
is checked for, and `--select NOPRIM001` still means only `NOPRIM001` ran. To check a
rule in one directory alone, select it globally and ignore it everywhere else.

A per-path ignore deselects rather than suppresses. The rule never runs, so nothing is
counted in the summary the way a `# noprim: ignore` comment is — the same as the
top-level `ignore`. If a baseline recorded violations for a code you then ignore for
those paths, its entries stop matching, are reported as stale on stderr, and are pruned
the next time the baseline is written.

Passing `--ignore` on the command line replaces the top-level `ignore` key only;
per-path entries still apply on top of it.

A selector that names no rule at all is an error, as is allowing a name that nothing
denies, allowing and denying the same name for the same path, or a key noprim does not
recognise. A config that quietly does nothing is the failure this feature exists to
prevent. Ignoring a code that is not currently selected is *not* an error, though —
deselecting a rule globally should not break an unrelated override that mentions it.

These complaints name the block they came from by its patterns:

```
allow of a name that is not on the deny-list: Enum (per-path entry for legacy/**)
```

An unrecognised key is caught earlier, by the schema, and is located by position
instead — `per-path.0.selct  Extra inputs are not permitted`.

## Types

Installing `noprim` also installs `noprim_types` — the wrappers the linter itself uses,
for the cases pydantic does not already cover.

| Type | Wraps | Guarantee |
| --- | --- | --- |
| `Verdict` | `bool` | Composes with `and_`, `or_`, `negated` and `Verdict.any` without ever unwrapping. Defines `__bool__`, so it reads as the answer it is. |
| `EnsuredDir` | `Path` | The directory exists once you hold one — created with its parents if it did not. Raises if a file holds the path. |
| `NonBlankString` | `str` | Not empty and not all whitespace. The value passes through verbatim; nothing is stripped. |

```python
from noprim_types import EnsuredDir, NonBlankString, Verdict


def write_report(into: EnsuredDir, title: NonBlankString) -> Verdict: ...
```

For an existing directory or file, use pydantic's own `DirectoryPath` and `FilePath`
rather than anything here. `ReplacementTable.default()` is the full map from each denied
type to what to reach for instead, and every name on the deny-list has an entry.

## Dogfooding

`moon run :noprim` runs this linter over its own source under `--preset all` and with
no `--allow` flags, as part of the lint chain and the pre-commit hooks. Building it that way surfaced three
things worth recording:

- **`X | None` was invisible.** The checker matched `Optional[str]` but not the PEP 604
  spelling, because `ast.BinOp` had no case. Nothing in the repo caught it until the
  tool was pointed at code that used unions.
- **Booleans resist wrapping.** `Verdict` is a `RootModel[bool]` with `__bool__`, which
  pyrefly rejects in both directions: `.filter()` is typed `Callable[[T], bool]` and
  will not take a `Verdict`-returning predicate (2 `bad-argument-type` suppressions),
  and `preset = "all"` forbids implicit truthiness (6 `implicit-bool` suppressions).
  The second group could be spelled `.root` instead; the suppressions are deliberate,
  so that the call sites read as booleans and every one of them disappears when iterpy
  accepts anything boolish.
- **Frameworks own some signatures.** Typer reads the command's annotations to build
  the CLI, so those five parameters carry `# noprim: ignore`, as does one test double
  bound to `Path.is_dir`'s signature. pytest's ownership of test signatures was
  frequent enough to become a rule rather than 40 comments.
