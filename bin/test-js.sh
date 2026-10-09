#!/usr/bin/env bash
# Run the tests for the scripts the admin pages load, with coverage.
#
# Node's own test runner and its own coverage, with no packages to install: the scripts are small
# and tested against stand-ins for the DOM and the browser APIs rather than a real browser.
# Coverage of backend/src/ecowitt/static is written as lcov to backend/coverage-js/lcov.info and
# converted to the istanbul files coverage.toml names. Called by `make test-js`, bin/coverage.sh
# and CI, so all three run the same thing.
set -euo pipefail

cd "$(dirname "$0")/.."

for tool in node python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "$tool is not installed; it is needed for the page script tests." >&2
    exit 1
  fi
done

# Files rather than the directory: Node before 23 treats a directory argument as a module to
# load, and fails with MODULE_NOT_FOUND instead of running the tests in it.
shopt -s nullglob
tests=(backend/tests/js/*.test.js)
if [ "${#tests[@]}" -eq 0 ]; then
  echo "no page script tests found in backend/tests/js" >&2
  exit 1
fi

out=backend/coverage-js
rm -rf "$out"
mkdir -p "$out"
node --test --experimental-test-coverage \
  --test-coverage-include='backend/src/ecowitt/static/**' \
  --test-reporter=spec --test-reporter-destination=stdout \
  --test-reporter=lcov --test-reporter-destination="$out/lcov.info" \
  "${tests[@]}"
python3 bin/lcov-to-istanbul.py "$out/lcov.info" "$out"
