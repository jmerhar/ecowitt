#!/usr/bin/env bash
# Run one Python project's test suite.
#
# Called by `make test`, by bin/coverage.sh and by CI, so all three execute the same thing. The
# first argument names the project (its directory: core, collector, dashboard/api); the rest
# pass through to pytest, which is how a single test is run:
#   bin/test-python.sh collector tests/test_infra/test_ingest.py -k slash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
project="${1:?usage: bin/test-python.sh <project> [pytest arguments]}"
shift
if [ ! -f "$root/$project/pyproject.toml" ]; then
  echo "no Python project at '$project'" >&2
  exit 1
fi
cd "$root/$project"
# Coverage's sys.monitoring core traces lines after `await`; the legacy C core silently
# under-reports async code, and the listeners and loops here are async.
export COVERAGE_CORE=sysmon
# A path to the shared virtualenv locally, a bare command name in CI where the projects are
# installed into the runner's own Python. `command -v` accepts both.
python="${PYTHON:-$root/.venv/bin/python}"
if ! command -v "$python" >/dev/null 2>&1; then
  echo "No interpreter at '$python'. Run 'make install' first, or set PYTHON." >&2
  exit 1
fi
exec "$python" -m pytest "$@"
