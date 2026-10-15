#!/usr/bin/env bash
# Serve the dashboard from the working copy: the API on :2553, restarted on a change to its code
# or core's, and the page on :5173 with hot reload, which hands /api and /setup to the API.
#
#   bin/dashboard-dev.sh [SERVER]
#
# With SERVER, InfluxDB on that host's loopback (port INFLUX_PORT, 8181) is forwarded to the same
# port here over ssh for as long as the dashboard runs, so setup's database address is
# http://127.0.0.1:8181. An ssh connection already open to SERVER (ControlMaster) carries the
# forward; otherwise a connection of its own does. Without SERVER the API reads whatever
# data-dashboard/dashboard.yaml names.
#
# The first run has no dashboard.yaml: finish setup at http://localhost:5173/setup. Either
# server stopping, or a signal, stops the other and removes the forward.
# Environment: INFLUX_PORT, and SSH, PYTHON and VITE, which name the commands run.
set -euo pipefail

cd "$(dirname "$0")/.."
server="${1:-}"
port="${INFLUX_PORT:-8181}"
ssh="${SSH:-ssh}"
python="${PYTHON:-.venv/bin/python}"
vite="${VITE:-$PWD/dashboard/web/node_modules/.bin/vite}"
forward="$port:127.0.0.1:$port"
tunnel_pid=""
api_pid=""
web_pid=""
shared=false

if [ ! -x "$vite" ]; then
  echo "dashboard/web/node_modules is missing; run 'make web-install'." >&2
  exit 1
fi

# Stop both servers, then remove the forward, whichever way it was made.
cleanup() {
  local pid
  for pid in $api_pid $web_pid; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in $api_pid $web_pid; do
    wait "$pid" 2>/dev/null || true
  done
  if [ "$shared" = true ]; then
    "$ssh" -O cancel -L "$forward" "$server" 2>/dev/null || true
  elif [ -n "$tunnel_pid" ]; then
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
  fi
}
# Runs on any exit, a signal's included. The servers run in the background, where a
# non-interactive shell leaves them ignoring Ctrl-C, so this is what stops them.
trap cleanup EXIT

if [ -n "$server" ]; then
  if "$ssh" -O check "$server" 2>/dev/null; then
    shared=true
    # ssh reports a failure when the port is already forwarded, which still works.
    "$ssh" -O forward -L "$forward" "$server" \
      || echo "ssh did not confirm the forward of port $port; it may already exist" >&2
  else
    "$ssh" -N -o ExitOnForwardFailure=yes -o ControlMaster=no -o ControlPath=none \
      -L "$forward" "$server" &
    tunnel_pid=$!
  fi
  echo "InfluxDB on $server is at http://127.0.0.1:$port" >&2
else
  echo "No SERVER: the API uses the database dashboard.yaml names; nothing is forwarded." >&2
fi

DATA_DIR=data-dashboard LOG_LEVEL=DEBUG "$python" -m uvicorn \
  ecowitt.dashboard.serve:from_environment --factory \
  --reload --reload-dir dashboard/api/src --reload-dir core/src \
  --host 127.0.0.1 --port 2553 --log-level debug --no-server-header &
api_pid=$!
# Vite would otherwise clear the terminal as it starts, and with it the API's log and the above.
(cd dashboard/web && exec "$vite" --clearScreen false) &
web_pid=$!

# Whichever stops first ends the script with its status.
wait -n "$api_pid" "$web_pid"
