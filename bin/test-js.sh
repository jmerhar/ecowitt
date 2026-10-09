#!/usr/bin/env bash
# Run the tests for the scripts the admin pages load.
#
# Node's own test runner, with no packages to install: the scripts are small and tested against
# stand-ins for the DOM and the browser APIs rather than a real browser. Called by `make test-js`
# and by CI, so both run the same thing.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v node >/dev/null 2>&1; then
  echo "node is not installed; it is needed for the page script tests." >&2
  exit 1
fi

exec node --test backend/tests/js/
