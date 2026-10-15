"""bin/dashboard-dev.sh: the dashboard's API and page from the working copy, with a server's
InfluxDB forwarded for exactly as long as they run."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "bin" / "dashboard-dev.sh"

#: Logs its arguments; `-O check` succeeds only with FAKE_MASTER set, and `-N` stays up, as a
#: tunnel does, after writing its process id.
FAKE_SSH = """#!/usr/bin/env bash
echo "$*" >> "$LOG"
if [ "$1 $2" = "-O check" ]; then [ -n "${FAKE_MASTER:-}" ]; exit; fi
if [ "$1" = "-N" ]; then echo $$ > "$TUNNEL_PID"; exec sleep 300; fi
"""

#: Logs how the API is started and keeps running, as it does, after writing its process id; with
#: FAKE_EXIT it exits with that status instead, once the page (and with WAIT_TUNNEL the tunnel)
#: is up.
FAKE_PYTHON = """#!/usr/bin/env bash
echo "python $* DATA_DIR=$DATA_DIR LOG_LEVEL=$LOG_LEVEL" >> "$LOG"
if [ -n "${FAKE_EXIT:-}" ]; then
  while [ ! -s "$WEB_PID" ]; do sleep 0.05; done
  if [ -n "${WAIT_TUNNEL:-}" ]; then while [ ! -s "$TUNNEL_PID" ]; do sleep 0.05; done; fi
  exit "$FAKE_EXIT"
fi
echo $$ > "$API_PID"; exec sleep 300
"""

#: The page's server: logs where it was started and keeps running; with FAKE_WEB_EXIT it exits
#: with that status once the API is up.
FAKE_VITE = """#!/usr/bin/env bash
echo "vite $* in $(basename "$PWD")" >> "$LOG"
echo $$ > "$WEB_PID"
if [ -n "${FAKE_WEB_EXIT:-}" ]; then
  while [ ! -s "$API_PID" ]; do sleep 0.05; done
  exit "$FAKE_WEB_EXIT"
fi
exec sleep 300
"""

API = (
    "python -m uvicorn ecowitt.dashboard.serve:from_environment --factory"
    " --reload --reload-dir dashboard/api/src --reload-dir core/src"
    " --host 127.0.0.1 --port 2553 --log-level debug --no-server-header"
    " DATA_DIR=data-dashboard LOG_LEVEL=DEBUG"
)

#: How the page's server is started: in dashboard/web, leaving the terminal as it is.
WEB = "vite --clearScreen false in web"


def environment(tmp_path: Path, **env: str) -> dict[str, str]:
    """The stand-ins written to `tmp_path`, and the environment that makes the script run them."""
    for name, body in (("ssh", FAKE_SSH), ("python", FAKE_PYTHON), ("vite", FAKE_VITE)):
        path = tmp_path / name
        path.write_text(body)
        path.chmod(0o755)
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "WAIT_"))},
        "SSH": str(tmp_path / "ssh"),
        "PYTHON": str(tmp_path / "python"),
        "VITE": str(tmp_path / "vite"),
        "LOG": str(tmp_path / "log"),
        "TUNNEL_PID": str(tmp_path / "tunnel.pid"),
        "API_PID": str(tmp_path / "api.pid"),
        "WEB_PID": str(tmp_path / "web.pid"),
        **env,
    }


def calls(tmp_path: Path) -> list[str]:
    """The commands the stand-ins logged, in order."""
    log = tmp_path / "log"
    return log.read_text().splitlines() if log.exists() else []


def pid(tmp_path: Path, name: str) -> int:
    """The process id a stand-in wrote, waiting for it to start."""
    path = tmp_path / f"{name}.pid"
    deadline = time.monotonic() + 10
    while not path.exists() or not path.read_text().strip():
        assert time.monotonic() < deadline, f"{name} never started"
        time.sleep(0.05)
    return int(path.read_text())


def assert_stopped(*pids: int) -> None:
    """Fail if any of the processes is still running, killing it rather than leaving it."""
    survivors = []
    for p in pids:
        try:
            os.kill(p, 0)
        except ProcessLookupError:
            continue
        survivors.append(p)
        os.kill(p, signal.SIGKILL)
    assert not survivors, f"outlived the script: {survivors}"


def run(tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run the script to its end with the stand-ins."""
    return subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=environment(tmp_path, **env),
    )


def signalled(tmp_path: Path, signum: int, *args: str, **env: str) -> list[int]:
    """Start the script, send it `signum` once everything is up, and return what it started."""
    script = subprocess.Popen(  # noqa: S603
        [str(SCRIPT), *args],
        env=environment(tmp_path, **env),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        pids = [pid(tmp_path, "api"), pid(tmp_path, "web")]
        if args and "FAKE_MASTER" not in env:
            pids.append(pid(tmp_path, "tunnel"))
        script.send_signal(signum)
        script.wait(timeout=10)
    finally:
        script.kill()
    return pids


def test_without_a_server_it_serves_the_api_and_the_page(tmp_path: Path) -> None:
    started = signalled(tmp_path, signal.SIGINT)

    assert sorted(calls(tmp_path)) == sorted([API, WEB])
    assert_stopped(*started)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_an_open_connection_carries_the_forward_and_a_signal_ends_everything(
    tmp_path: Path, signum: signal.Signals
) -> None:
    started = signalled(tmp_path, signum, "db.example.test", FAKE_MASTER="1", INFLUX_PORT="9999")

    logged = calls(tmp_path)
    assert logged[:2] == [
        "-O check db.example.test",
        "-O forward -L 9999:127.0.0.1:9999 db.example.test",
    ]
    assert sorted(logged[2:4]) == sorted([API, WEB])
    assert logged[4:] == ["-O cancel -L 9999:127.0.0.1:9999 db.example.test"]
    assert_stopped(*started)


def test_a_tunnel_of_its_own_is_stopped_with_the_servers(tmp_path: Path) -> None:
    started = signalled(tmp_path, signal.SIGTERM, "db.example.test")

    assert any(
        c.startswith("-N ") and c.endswith("-L 8181:127.0.0.1:8181 db.example.test")
        for c in calls(tmp_path)
    )
    assert not any("-O cancel" in c for c in calls(tmp_path))
    assert_stopped(*started)


def test_the_api_failing_stops_the_page_and_the_tunnel(tmp_path: Path) -> None:
    result = run(tmp_path, "db.example.test", FAKE_EXIT="3", WAIT_TUNNEL="1")

    assert result.returncode == 3
    assert_stopped(pid(tmp_path, "web"), pid(tmp_path, "tunnel"))


def test_the_page_failing_stops_the_api(tmp_path: Path) -> None:
    result = run(tmp_path, FAKE_WEB_EXIT="4")

    assert result.returncode == 4
    assert_stopped(pid(tmp_path, "api"))


def test_without_a_server_it_says_nothing_is_forwarded(tmp_path: Path) -> None:
    result = run(tmp_path, FAKE_WEB_EXIT="0")

    assert "nothing is forwarded" in result.stderr
    (tmp_path / "forwarded").mkdir()
    forwarded = run(tmp_path / "forwarded", "db.example.test", FAKE_MASTER="1", FAKE_WEB_EXIT="0")
    assert "nothing is forwarded" not in forwarded.stderr


def test_without_the_pages_dependencies_nothing_starts(tmp_path: Path) -> None:
    result = run(tmp_path, "db.example.test", VITE=str(tmp_path / "missing"))

    assert result.returncode == 1
    assert "make web-install" in result.stderr
    assert calls(tmp_path) == []
