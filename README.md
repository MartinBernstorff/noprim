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

`--select` replaces the default set, `--extend-select` adds to it and `--ignore`
subtracts, all three taking code prefixes as ruff does. A selector that names no rule
is an error.

```console
$ noprim check --ignore NOPRIM002 .          # every default rule but return types
$ noprim check --extend-select NOPRIM004 .   # the defaults, plus Any on parameters
$ noprim check --select NOPRIM .             # every rule there is
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

The comment suppresses only the line it sits on, and must end the line — which leaves
`# noprim: ignore[RULE]` free for later.

When a framework dictates the same name everywhere — `factory_boy` hooks take `kwargs`,
`size`, `create` and `extracted` — suppressing it line by line is busywork. Skip the
name instead:

```
noprim check --ignore-names kwargs --ignore-names size .
```

Names are matched on parameters and attributes only; a return type carries the
function's name, not one of its own, so it is never skipped this way.

## Flags

| Flag | Effect |
| --- | --- |
| `--allow NAME` | Remove a type from the deny-list. Repeatable. |
| `--deny NAME` | Add a type to the deny-list. Repeatable. |
| `--select CODE` | Run these rule codes instead of the defaults. Prefixes count. Repeatable. |
| `--extend-select CODE` | Run these rule codes as well as the selected ones. Repeatable. |
| `--ignore CODE` | Drop these rule codes from the run. Repeatable. |
| `--ignore-names NAME` | Skip parameters and attributes called `NAME`. Repeatable. |
| `--exclude GLOB` | Skip paths while walking. Gitignore syntax, anchored at the config file's directory, or the repo root when there is no config. Repeatable. |
| `--quiet`, `-q` | Suppress the trailing summary. |

Directories are walked recursively, honouring every `.gitignore` from the repo root
down. A file named explicitly on the command line is checked even if it is ignored.

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
extend-select = ["NOPRIM004"]
ignore = ["NOPRIM002"]
```

Every key is a flag of the same name, and passing that flag replaces the key outright
rather than adding to it — `--deny Enum` ignores whatever `deny` the file set.

### Per-path overrides

One deny-list for a whole codebase is the wrong shape: the domain deserves stricter
rules than the Django layer. `per-path` entries adjust the list for the paths they
match.

```toml
[[per-path]]
paths = ["domain/**", "api/**"]
deny = ["Enum", "Flag"]

[[per-path]]
paths = ["test_infra/**", "django_app/**"]
allow = ["str", "int", "bool"]
```

Overrides carry `allow` and `deny` only. The remaining keys are whole-run settings:
`exclude` decides which files are walked at all, and `select`, `extend-select` and
`ignore` choose rules rather than deny-lists.

Patterns use gitignore syntax, anchored at the directory holding the config, so
`test_*.py` matches at any depth and `domain/**` does not. Every entry that matches a
file contributes — there is no first-match or most-specific rule — and each is applied
on top of the top-level lists, so an override can relax something the top level denied.

Allowing a name that nothing denies is an error, as is allowing and denying the same
name for the same path, as is a key noprim does not recognise. A config that quietly
does nothing is the failure this feature exists to prevent.

## Dogfooding

`moon run :noprim` runs this linter over its own source with every rule selected and
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
