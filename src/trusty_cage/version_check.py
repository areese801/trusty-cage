"""
Check for newer versions of trusty-cage on PyPI.

Runs non-blocking on startup — network failures are silently ignored.
Image staleness is handled by build_if_needed() in the create/attach flows.
"""

import json
import urllib.request

from rich import print as rprint

from trusty_cage import __version__


PYPI_URL = "https://pypi.org/pypi/trusty-cage/json"
PYPI_TIMEOUT = 3  # seconds — don't slow down startup


def _fetch_latest_version() -> str | None:
    """
    Fetch the latest version from PyPI. Returns None on any failure.
    """
    try:
        req = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=PYPI_TIMEOUT) as resp:
            data = json.loads(resp.read())
            return data.get("info", {}).get("version")
    except Exception:
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    """
    Parse a version string like "0.8.3" into a tuple (0, 8, 3) for comparison.
    """
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def check_for_updates() -> None:
    """
    Check for a newer version on PyPI.
    Prints a warning if a newer version is available. Silently returns on failure.
    """
    latest = _fetch_latest_version()
    if latest and _parse_version(latest) > _parse_version(__version__):
        rprint(
            f"[bold yellow]Update available:[/bold yellow] "
            f"trusty-cage {__version__} -> {latest} "
            f"[dim](pip install --upgrade trusty-cage)[/dim]"
        )
