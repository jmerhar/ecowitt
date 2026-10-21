#!/usr/bin/env bash
# Run the Bruno collection's dashboard requests (bruno/dashboard and bruno/dashboard-site), with
# their assertions, against the real API over the tests' example station
# (dashboard/api/tests/fixture_server.py). The admin requests need a running collector and are
# left out.
#
# Called by `make test-bruno` and by CI. Needs Node, for the pinned Bruno CLI, and the Python
# projects (`make install`, or PYTHON set to an interpreter that has them).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
python="${PYTHON:-$root/.venv/bin/python}"
port="${BRUNO_PORT:-2597}"
cli="@usebruno/cli@4.2.0"

# The API alone is exercised, so the pages it would serve are an empty directory.
web="$(mktemp -d)"
(cd "$root/dashboard/api" && exec "$python" -m tests.fixture_server "$web" "$port") &
server=$!
trap 'kill "$server" 2>/dev/null || true; rm -rf "$web"' EXIT

for attempt in $(seq 1 120); do
  curl -fs -o /dev/null "http://127.0.0.1:$port/healthz" && break
  if [ "$attempt" -eq 120 ]; then
    echo "The fixture server did not answer on port $port." >&2
    exit 1
  fi
  sleep 0.5
done

cd "$root/bruno"
# The CLI is pinned but its dependencies resolve afresh; like the page's installs
# (dashboard/web/.npmrc), take nothing published in the last two weeks.
npx --yes --min-release-age=14 "$cli" run dashboard dashboard-site -r --env local --env-var "dashboard_url=http://127.0.0.1:$port"
