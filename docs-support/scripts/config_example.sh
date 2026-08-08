#!/usr/bin/env bash
# Prints a config example, having first proved noprim can load it. A renamed or
# removed key makes the run exit 2 under extra="forbid", which fails the render — so
# the documented config cannot drift from the schema.
set -euo pipefail

directory="$1"

if [ ! -f "$directory/noprim.toml" ]; then
  printf 'config example is missing: %s/noprim.toml\n' "$directory" >&2
  exit 1
fi

(cd "$directory" && uv run noprim check . >/dev/null 2>&1)

cat "$directory/noprim.toml"
