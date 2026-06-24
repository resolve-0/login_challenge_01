"""WireGuard VPN egress — routes the Mac (and any device sharing its internet)
through a geo-targeted WireGuard tunnel via ``wg-quick``.

This is an alternative to the HTTP proxy for the IP-spoofing half: with
``AllowedIPs = 0.0.0.0/0`` the whole machine's traffic exits through the tunnel,
so an iPhone routed over USB Internet Sharing also gets the tunnel's egress IP.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from geospoof.state import StateStore

log = structlog.get_logger()

_CATEGORY = "vpn"


class WireGuardVPN:
    """Brings a WireGuard tunnel up/down via ``wg-quick`` and tracks it in state."""

    def __init__(self, conf_path: str | Path, state: StateStore) -> None:
        self._conf = Path(conf_path).expanduser().resolve()
        self._state = state

    @staticmethod
    def is_available() -> bool:
        """True if ``wg-quick`` is on PATH."""
        return shutil.which("wg-quick") is not None

    def _run(self, action: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["wg-quick", action, str(self._conf)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        log.debug(
            "wg-quick",
            action=action,
            conf=str(self._conf),
            rc=result.returncode,
            stderr=(result.stderr or "").strip(),
        )
        return result

    def up(self) -> None:
        """Bring the tunnel up. Raises RuntimeError on failure."""
        if not self.is_available():
            raise RuntimeError(
                "wg-quick not found. Install WireGuard tools:\n"
                "  brew install wireguard-tools"
            )
        if not self._conf.is_file():
            raise RuntimeError(f"WireGuard config not found: {self._conf}")

        # Record intent BEFORE the call so a crash mid-up is still recoverable.
        self._state.record(_CATEGORY, "conf_path", str(self._conf))
        self._state.record(_CATEGORY, "started_by_us", "true")

        result = self._run("up")
        if result.returncode != 0:
            self._state.clear(_CATEGORY)
            raise RuntimeError(
                f"Failed to bring up WireGuard tunnel:\n{result.stderr.strip()}"
            )

    def down(self) -> None:
        """Bring the tunnel down. Raises RuntimeError on failure."""
        result = self._run("down")
        self._state.clear(_CATEGORY)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to bring down WireGuard tunnel:\n{result.stderr.strip()}"
            )


def recover(state: StateStore) -> None:
    """Bring down a tunnel left up by a previous crashed run."""
    if state.get(_CATEGORY, "started_by_us") != "true":
        return
    conf = state.get(_CATEGORY, "conf_path")
    if conf and shutil.which("wg-quick"):
        try:
            subprocess.run(
                ["wg-quick", "down", conf],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            pass
    state.clear(_CATEGORY)
