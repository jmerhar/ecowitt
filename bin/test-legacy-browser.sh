#!/usr/bin/env bash
# Check that the dashboard's legacy build runs in Chromium 59, the browser of an Android 4.4
# tablet: build the pages, serve them with the API over the tests' example station
# (dashboard/api/tests/fixture_server.py), and load them in dashboard/web/legacy-browser's image.
#
# Called by `make test-legacy-browser` and by CI. Needs Docker, Node, the pages' node_modules
# (`make web-install`) and the Python projects (`make install`, or PYTHON set to an interpreter
# that has them). The browser is a Linux x64 build; elsewhere Docker runs it emulated, slowly.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
web="$root/dashboard/web"
python="${PYTHON:-$root/.venv/bin/python}"
page_port="${LEGACY_PAGE_PORT:-2598}"
devtools_port="${LEGACY_DEVTOOLS_PORT:-9258}"
image=ecowitt-legacy-browser
container="$image-$$"

if [ ! -d "$web/node_modules" ]; then
  echo "dashboard/web/node_modules is missing; run 'make web-install'." >&2
  exit 1
fi

# Polls a URL until it answers, for at most a minute.
wait_for() {
  for _ in $(seq 1 120); do
    curl -fs -o /dev/null "$1" && return 0
    sleep 0.5
  done
  echo "Nothing answered at $1." >&2
  return 1
}

(cd "$web" && npx vite build --logLevel warn)
docker build -q -t "$image" "$web/legacy-browser" >/dev/null

(cd "$root/dashboard/api" && exec "$python" -m tests.fixture_server "$web/dist" "$page_port") &
server=$!
trap 'kill "$server" 2>/dev/null || true; docker rm -f "$container" >/dev/null 2>&1 || true' EXIT
wait_for "http://127.0.0.1:$page_port/healthz"

# Not --rm: a browser that fails to start leaves its log to show. The trap removes it.
docker run -d --name "$container" --add-host=host.docker.internal:host-gateway \
  -p "127.0.0.1:$devtools_port:9222" "$image" >/dev/null
wait_for "http://127.0.0.1:$devtools_port/json/list" || { docker logs "$container" >&2; exit 1; }

node "$web/legacy-browser/check.mjs" "http://127.0.0.1:$devtools_port" "http://host.docker.internal:$page_port/"
