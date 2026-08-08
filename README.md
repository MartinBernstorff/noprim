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
`datetime`, `date`, `time`, `timedelta`, `Decimal`, `Fraction`), the containers
(`list`, `dict`, `set`, `frozenset`, `tuple`) and the escape hatches (`Any`,
`object`). Adjust it per run with `--allow` and `--deny`.

## What is exempt

Some signatures are not the author's to choose, so noprim does not report them:

- **Dunder methods.** `__eq__` takes `object` because the data model says so.
- **`RootModel` subclass bodies.** Wrapping a primitive is the point of the pattern.
- **Overload implementations.** The stubs above them carry the real types.
- **`self` and `cls`.**
- **`Literal[...]` arguments**, which are values rather than types.
- **Parameters of pytest tests and fixtures**, in files matching `test_*.py` or
  `*_test.py`. pytest decides what a fixture injects and what `parametrize` feeds in,
  so the parameter type is not a free choice. Return types and attributes in those
  files are still checked, as are ordinary helpers that happen to live beside tests.

Anything else that is genuinely forced can be suppressed a line at a time:

```python
def check(quiet: Annotated[  # noprim: ignore
    bool, typer.Option("--quiet")
] = False) -> None: ...
```

The comment suppresses only the line it sits on, and must end the line — which leaves
`# noprim: ignore[RULE]` free for later.

## Flags

| Flag | Effect |
| --- | --- |
| `--allow NAME` | Remove a type from the deny-list. Repeatable. |
| `--deny NAME` | Add a type to the deny-list. Repeatable. |
| `--exclude GLOB` | Skip paths while walking. Gitignore syntax, anchored at the repo root. Repeatable. |
| `--quiet`, `-q` | Suppress the trailing summary. |

Directories are walked recursively, honouring every `.gitignore` from the repo root
down. A file named explicitly on the command line is checked even if it is ignored.

## Dogfooding

`moon run :noprim` runs this linter over its own source with no `--allow` flags, as
part of the lint chain and the pre-commit hooks. Building it that way surfaced three
things worth recording:

- **`X | None` was invisible.** The checker matched `Optional[str]` but not the PEP 604
  spelling, because `ast.BinOp` had no case. Nothing in the repo caught it until the
  tool was pointed at code that used unions.
- **Booleans resist wrapping.** `Verdict` is a `RootModel[bool]` with `__bool__`, but
  `iterpy`'s `.filter()` is typed `Callable[[T], bool]`, so wrapped predicates need a
  `# pyrefly: ignore` at the call site until iterpy accepts anything boolish. There are
  8 such suppressions, split between `implicit-bool` and `bad-argument-type`.
- **Frameworks own some signatures.** Typer reads the command's annotations to build
  the CLI, so those five parameters carry `# noprim: ignore`. pytest's ownership of
  test signatures was frequent enough to become a rule rather than 40 comments.
