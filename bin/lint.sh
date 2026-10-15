#!/usr/bin/env bash
# Every check that needs nothing but a clone.
#
# All of them run before the target fails: stopping at the first hides the rest, and the point
# of a sweep is to see the whole picture in one pass.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
status=0

run() {
  printf '\n\033[1m--- %s ---\033[0m\n' "$1"
  shift
  "$@" || status=1
}

run "shellcheck" shellcheck bin/*.sh
run "ruff" env RUFF=.venv/bin/ruff bin/ci-ruff.sh
run "lockfile registry" bin/check-lockfile.sh
run "versions agree" bin/version.py check
run "compose files parse" bin/check-compose.sh

exit "$status"
