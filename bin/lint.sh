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
run "ruff" sh -c 'cd backend && .venv/bin/ruff check . && .venv/bin/ruff check --config pyproject.toml ../bin/*.py'
run "ruff format" sh -c 'cd backend && .venv/bin/ruff format --check . ../bin/*.py'
run "compose files parse" sh -c '
  docker compose -f docker-compose.yml config -q &&
  docker compose -f docker-compose.yml -f docker-compose.build.yml config -q &&
  docker compose -f docker-compose.yml -f docker-compose.dev.yml config -q'

exit "$status"
