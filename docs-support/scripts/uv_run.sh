#!/usr/bin/env bash
# documator merges a block's stderr into its stdout, and uv writes venv creation and
# build progress there the first time it runs in a tree — every CI run and every fresh
# clone. One discarded run moves that noise outside the capture, so a cold tree renders
# byte-identically to a warm one.
set -euo pipefail

uv run noprim --help >/dev/null 2>&1

exec uv run "$@"
