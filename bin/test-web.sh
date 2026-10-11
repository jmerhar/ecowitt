#!/usr/bin/env bash
# Type-check the dashboard's pages and run their tests with coverage.
#
# Called by `make test-web`, by bin/coverage.sh and by CI. node_modules must already be there:
# CI installs it with `npm ci`, and `make web-install` does locally (through whatever registry
# this machine's npm is configured with, without touching the lockfile).
set -euo pipefail

cd "$(dirname "$0")/../dashboard/web"
if [ ! -d node_modules ]; then
  echo "dashboard/web/node_modules is missing; run 'make web-install'." >&2
  exit 1
fi
npx svelte-check --tsconfig ./tsconfig.json --fail-on-warnings
npx vitest run --coverage "$@"
