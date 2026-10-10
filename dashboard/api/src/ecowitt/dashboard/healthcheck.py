"""The container's health probe: exits non-zero unless /healthz answers 200.

A dashboard waiting for setup is healthy -- it is serving the setup page -- so the probe checks
only that the process answers, not that it is configured.
"""

import sys
import urllib.error
import urllib.request

from ecowitt.dashboard.settings import Settings

TIMEOUT_SECONDS = 5


def main(settings: Settings | None = None) -> int:
    """Report whether the application is serving."""
    port = (settings or Settings()).port
    try:
        with urllib.request.urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/healthz", timeout=TIMEOUT_SECONDS
        ) as response:
            if response.status == 200:
                return 0
            print(f"unhealthy: HTTP {response.status}", file=sys.stderr)
    except urllib.error.HTTPError as exc:
        with exc:
            print(f"unhealthy: HTTP {exc.code}", file=sys.stderr)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"unhealthy: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
