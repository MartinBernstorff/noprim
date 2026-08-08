#!/usr/bin/env bash
# The elapsed time is the one part of a run that is not a claim about behaviour, so it
# is pinned; every other byte is what the CLI actually printed.
set -uo pipefail

expected="$1"
directory="$2"
shift 2

# Checked before the run: a missing fixture otherwise exits with the very code the
# example expects, and the block renders an error as if it were output.
if [ ! -d "$directory" ]; then
  printf 'example fixture is missing: %s\n' "$directory" >&2
  exit 1
fi

# See uv_run.sh: a cold tree would otherwise fold uv's build progress into the example.
(cd "$directory" && uv run noprim --help >/dev/null 2>&1)

output="$(cd "$directory" && uv run noprim "$@" 2>&1)"
status=$?

printf '%s\n' "$output" | sed -E 's/ in [0-9]+(\.[0-9]+)?(ms|s) - / in 31ms - /'

if [ "$status" -ne "$expected" ]; then
  printf 'example expected exit %s, got %s\n' "$expected" "$status" >&2
  exit 1
fi
