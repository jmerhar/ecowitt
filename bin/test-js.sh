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

# Files rather than the directory: Node before 23 treats a directory argument as a module to
# load, and fails with MODULE_NOT_FOUND instead of running the tests in it.
shopt -s nullglob
tests=(backend/tests/js/*.test.js)
if [ "${#tests[@]}" -eq 0 ]; then
  echo "no page script tests found in backend/tests/js" >&2
  exit 1
fi

exec node --test "${tests[@]}"
