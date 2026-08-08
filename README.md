# noprim

A linter for Python signatures that leak primitives. A `str` parameter says nothing
about what it holds; a `UserId` does.

```console
$ noprim check .
src/billing/invoice.py:14:22: parameter "customer" is annotated "str"
src/billing/invoice.py:14:39: return type is annotated "bool"
Checked 42 files in 31ms - found 2 violations
```

Exits 1 when anything is reported, 0 otherwise, and 2 when a path does not exist or
cannot be read.

## What gets flagged

Three surfaces, wherever a denied type appears anywhere inside the annotation —
`list[str]`, `dict[str, UserId]` and `str | None` all count:

| Surface | Example |
| --- | --- |
| Parameter | `def send(to: str) -> None` |
| Return type | `def total() -> int` |
| Class attribute | `class Order:\n    id: str` |

The deny-list covers the builtins (`int`, `str`, `float`, `bool`, `bytes`,
`bytearray`, `complex`), the stdlib value types (`Path`, `PurePath`, `UUID`,
`datetime`, `date`, `time`, `timedelta`, `Decimal`, `Fraction`) and the containers
(`list`, `dict`, `set`, `frozenset`, `tuple`). Adjust it per run with `--allow` and
`--deny`.

`Any` and `object` are not on it. They are top types, not primitives: they say the
type is unknown rather than too narrow, and `object` is the right annotation for
`**kwargs` you never inspect. That is a different smell, so it is its own rule and
`--top-types` opts into it. The rule is all or nothing, so `--allow Any` is an error;
`--deny Any` still works if you want one of them on the deny-list by itself.

A container matches only when it is bare: `list` is reported, `list[Name]` is not,
because the annotation names a collection of a type that is already meaningful. It is
the contents that are judged, so `list[str]` is reported for the `str`.

## What is exempt

Some signatures are not the author's to choose, so noprim does not report them:

- **Dunder methods.** `__eq__` takes `object` because the data model says so.
- **`RootModel` subclass bodies.** Wrapping a primitive is the point of the pattern.
- **Overload implementations.** The stubs above them carry the real types.
- **Predicates** — functions returning a bare `bool`. A domain type around the answer
  to a yes-or-no question rarely earns its keep. Only the return type is exempt: a
  `bool` parameter, attribute, `list[bool]` or `bool | None` is still reported. Pass
  `--check-predicates` to report them too.
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
| `--top-types` | Also report `Any` and `object`. Off by default. |
| `--check-predicates` | Report functions returning `bool` instead of skipping them. |
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

Patterns use gitignore syntax, anchored at the directory holding the config, so
`test_*.py` matches at any depth and `domain/**` does not. Every entry that matches a
file contributes — there is no first-match or most-specific rule — and each is applied
on top of the top-level lists, so an override can relax something the top level denied.

Allowing a name that nothing denies is an error, as is allowing and denying the same
name for the same path, as is a key noprim does not recognise. A config that quietly
does nothing is the failure this feature exists to prevent.

## Dogfooding

`moon run :noprim` runs this linter over its own source with no `--allow` flags, as
part of the lint chain and the pre-commit hooks. Building it that way surfaced three
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
