"""macOS Internet Sharing automation — shares Mac internet to iPhone via USB."""

from __future__ import annotations

import plistlib
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import structlog

from geospoof.state import StateStore

log = structlog.get_logger()

_NAT_PLIST = Path("/Library/Preferences/SystemConfiguration/com.apple.nat.plist")
_SHARING_DAEMON = "/System/Library/LaunchDaemons/com.apple.NetworkSharing.plist"
_SHARING_SERVICE = "system/com.apple.NetworkSharing"


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a command, logging the invocation and result at debug level."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("timeout", 10)
    result = subprocess.run(cmd, **kwargs)
    log.debug(
        "subprocess",
        cmd=" ".join(cmd),
        rc=result.returncode,
        stderr=(result.stderr or "").strip() if hasattr(result, "stderr") else "",
    )
    return result


def _pid_alive(pid: str) -> bool:
    """Check whether a PID is still running."""
    return _run(["kill", "-0", pid]).returncode == 0


class InternetSharing:
    """Manages macOS Internet Sharing so the iPhone gets internet over USB."""

    def __init__(self, state: StateStore) -> None:
        self._state = state
        self._iphone_iface: str | None = None
        self._source_iface: str | None = None

    # ── Detection ─────────────────────────────────────────────────────

    @staticmethod
    def detect_iphone_interface() -> str | None:
        """Find the iPhone USB network interface via ioreg (AppleUSBNCMData).

        Filters by Apple vendor ID (1452) to avoid non-iPhone USB adapters,
        and prefers the interface with the highest IOLinkSpeed.

        Returns the BSD interface name (e.g. 'en8') or None.
        """
        try:
            out = subprocess.run(
                ["ioreg", "-w", "0", "-r", "-c", "AppleUSBNCMData"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        # Split into per-device blocks at each AppleUSBNCMData entry so
        # child objects (like +-o en8 <class IOEthernetInterface) stay
        # grouped with their parent.
        best = None
        best_speed = -1
        for block in re.split(r'(?=\+-o\s+AppleUSBNCMData\s)', out.stdout):
            vendor_m = re.search(r'"idVendor"\s*=\s*(\d+)', block)
            if not vendor_m or int(vendor_m.group(1)) != 1452:
                continue  # not Apple
            # Interface name appears as a child object: +-o en8 <class IOEthernetInterface
            name_m = re.search(r'\+-o\s+(en\d+)\s+<class IOEthernetInterface', block)
            if not name_m:
                continue
            speed_m = re.search(r'"IOLinkSpeed"\s*=\s*(\d+)', block)
            speed = int(speed_m.group(1)) if speed_m else 0
            if speed > best_speed:
                best = name_m.group(1)
                best_speed = speed
        return best

    @staticmethod
    def detect_internet_source() -> str | None:
        """Detect the Mac's default internet interface (e.g. 'en0').

        Parses `route -n get default` for the 'interface:' line.
        """
        try:
            out = subprocess.run(
                ["route", "-n", "get", "default"],
                capture_output=True, text=True, timeout=5,
            )
            match = re.search(r"interface:\s*(\S+)", out.stdout)
            return match.group(1) if match else None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    # ── Start / Stop ──────────────────────────────────────────────────

    def start(self) -> tuple[str, str]:
        """Enable Internet Sharing from the Mac to the iPhone over USB.

        Returns (iphone_interface, source_interface).
        Raises RuntimeError if detection or start fails.
        """
        # After WiFi toggle the USB NCM interface can momentarily disappear.
        # Retry detection a few times with a short delay.
        for attempt in range(5):
            self._iphone_iface = self.detect_iphone_interface()
            if self._iphone_iface:
                break
            log.debug("iphone_detect_retry", attempt=attempt)
            time.sleep(2)
        if not self._iphone_iface:
            raise RuntimeError(
                "Could not detect iPhone USB network interface.\n"
                "Make sure the iPhone is connected via USB and shows up in ifconfig."
            )

        self._source_iface = self.detect_internet_source()
        if not self._source_iface:
            raise RuntimeError(
                "Could not detect default internet interface on this Mac.\n"
                "Make sure the Mac has an active internet connection."
            )

        log.debug("interfaces", iphone=self._iphone_iface, source=self._source_iface)

        # ── Kill existing daemon robustly ──────────────────────────────
        # 1. Grab old PID before we try anything
        old_pid_result = _run(["pgrep", "InternetSharing"])
        old_pid = old_pid_result.stdout.strip() if old_pid_result.returncode == 0 else None
        log.debug("old_daemon", pid=old_pid)

        # 2. Try launchctl bootout
        _run(["launchctl", "bootout", _SHARING_SERVICE])
        time.sleep(1)

        # 3. Fallback: if daemon is still running, force-kill by name
        #    (avoids PID recycling race with the stale old_pid)
        pgrep_check = _run(["pgrep", "InternetSharing"])
        if pgrep_check.returncode == 0:
            log.debug("bootout_ineffective, falling back to pkill -9", old_pid=old_pid)
            _run(["pkill", "-9", "InternetSharing"])
            time.sleep(2)

        # Back up existing NAT plist (if any)
        if _NAT_PLIST.exists():
            self._state.backup_file(_NAT_PLIST, "nat_plist")
        else:
            self._state.record("nat_plist", "had_original", "false")

        # Write our NAT config
        nat_config = {
            "NAT": {
                "Enabled": 1,
                "PrimaryInterface": self._source_iface,
                "SharingDevices": [self._iphone_iface],
                "SharingNetworkNumberStart": "192.168.2.0",
                "SharingNetworkNumberEnd": "192.168.2.254",
                "SharingNetworkMask": "255.255.255.0",
            }
        }
        with open(_NAT_PLIST, "wb") as f:
            plistlib.dump(nat_config, f)

        # Record that we started sharing
        self._state.record("internet_sharing", "started_by_us", "true")

        # Re-register the service (may fail if already registered — that's OK)
        _run(["launchctl", "bootstrap", "system", _SHARING_DAEMON])

        # Force-start the daemon so it reads our NAT config
        _run(["launchctl", "kickstart", "-kp", _SHARING_SERVICE])

        # Poll for readiness — daemon needs time to start bootpd and assign IP
        for i in range(15):
            time.sleep(1)
            bootpd = _run(["pgrep", "bootpd"])
            ifout = _run(["ifconfig", self._iphone_iface], timeout=5)
            has_bootpd = bootpd.returncode == 0
            has_ip = "inet " in (ifout.stdout or "") and "169.254" not in (ifout.stdout or "")
            log.debug("readiness_poll", iteration=i, bootpd=has_bootpd, has_ip=has_ip)
            if has_bootpd and has_ip:
                break
        else:
            raise RuntimeError(
                "Internet Sharing did not become ready within 15 seconds.\n"
                "bootpd or IP assignment on the USB interface did not appear."
            )

        return self._iphone_iface, self._source_iface

    def stop(self) -> None:
        """Stop Internet Sharing and restore original NAT plist."""
        # Stop and deregister the sharing daemon
        try:
            _run(["launchctl", "bootout", _SHARING_SERVICE])
            time.sleep(1)

            # Fallback: if daemon is still running, force-kill it
            pgrep = _run(["pgrep", "InternetSharing"])
            if pgrep.returncode == 0:
                log.debug("bootout_ineffective_on_stop, falling back to pkill")
                _run(["pkill", "-9", "InternetSharing"])
                time.sleep(1)

            # Re-register for on-demand use (doesn't start the daemon)
            _run(["launchctl", "bootstrap", "system", _SHARING_DAEMON])
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Restore original NAT plist or remove ours
        if not self._state.restore_file("nat_plist"):
            # No backup existed — check if we created the plist from scratch
            had_original = self._state.get("nat_plist", "had_original")
            if had_original == "false" and _NAT_PLIST.exists():
                _NAT_PLIST.unlink()
            self._state.clear("nat_plist")

        # Clear sharing records
        self._state.clear("internet_sharing")
