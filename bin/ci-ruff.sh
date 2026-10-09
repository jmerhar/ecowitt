#!/usr/bin/env bash
# Lint and format-check the Python: the package and its tests, and the scripts in bin/.
#
# The bin/ scripts sit outside the backend project, so ruff is pointed at its configuration
# explicitly; otherwise it would check them against its defaults. Called by CI with the runner's
# ruff on PATH; `make lint` runs the same checks from the virtualenv.
set -euo pipefail

cd "$(dirname "$0")/../backend"
ruff="${RUFF:-ruff}"
"$ruff" check .
"$ruff" check --config pyproject.toml ../bin/*.py
"$ruff" format --check . ../bin/*.py
