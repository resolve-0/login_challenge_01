"""iPhone GPS control via pymobiledevice3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation


@dataclass
class DeviceInfo:
    name: str
    ios_version: str


class iOSDevice:
    """Manages connection to an iOS device and GPS simulation."""

    def __init__(self) -> None:
        self._lockdown: Any = None
        self._rsd: Any = None     # already-connected RSD from tunneld (iOS 17+)
        self._ios_version: str = ""
        self._device_name: str = ""
        self._dvt: Any = None              # held-open DVT session — see set_location
        self._location_sim: Any = None     # LocationSimulation bound to _dvt

    def _is_ios17_plus(self) -> bool:
        return int(self._ios_version.split(".")[0]) >= 17

    def connect(self) -> DeviceInfo:
        """Connect to iPhone via USB, detect iOS version, mount DDI.

        Returns device info for display purposes.
        """
        # 1. USB lockdown connection
        try:
            self._lockdown = create_using_usbmux(autopair=True)
        except Exception as exc:
            raise ConnectionError(
                "Could not connect to iPhone via USB.\n"
                "Make sure:\n"
                "  - iPhone is connected via USB cable\n"
                "  - You've trusted this computer on the iPhone\n"
                "  - Developer Mode is enabled (Settings → Privacy → Developer Mode)"
            ) from exc

        self._ios_version = self._lockdown.product_version
        self._device_name = self._lockdown.display_name

        if self._is_ios17_plus():
            # iOS 17+ — DDI is handled by tunneld, skip auto_mount
            self._connect_tunneld()
        else:
            # iOS <17 — mount developer disk image the traditional way
            try:
                import asyncio

                from pymobiledevice3.services.mobile_image_mounter import auto_mount
                from pymobiledevice3.utils import get_asyncio_loop
                loop = get_asyncio_loop()
                loop.run_until_complete(
                    asyncio.wait_for(auto_mount(self._lockdown), timeout=15)
                )
            except Exception as exc:
                structlog.get_logger().warning("ddi_mount_failed", error=str(exc))

        return DeviceInfo(name=self._device_name, ios_version=self._ios_version)

    def _connect_tunneld(self) -> None:
        """Connect to tunneld daemon to get an RSD for iOS 17+ devices."""
        from pymobiledevice3.tunneld.api import get_tunneld_devices

        try:
            devices = get_tunneld_devices()
        except Exception as exc:
            raise ConnectionError(
                "Could not connect to tunneld.\n"
                "iOS 17+ requires the tunneld daemon running in another terminal:\n\n"
                "  sudo python3 -m pymobiledevice3 remote tunneld\n"
            ) from exc

        if not devices:
            raise ConnectionError(
                "tunneld is running but no devices found.\n"
                "Make sure iPhone is connected and trusted."
            )

        if len(devices) > 1:
            structlog.get_logger().warning("multiple_devices", count=len(devices))

        self._rsd = devices[0]  # already connected by tunneld

    @property
    def service_provider(self):
        """Return the correct service provider for the connected device."""
        if self._is_ios17_plus() and self._rsd is not None:
            return self._rsd
        return self._lockdown

    def set_location(self, lat: float, lng: float) -> None:
        """Set GPS coordinates on the device.

        iOS keeps the simulated fix only while the DVT instruments connection
        stays open (the same way Xcode's *Simulate Location* holds the channel).
        So the session is opened once and held until clear_location() — closing
        it would make CoreLocation revert to the real GPS fix immediately.
        """
        if self._dvt is None:
            self._dvt = DvtSecureSocketProxyService(lockdown=self.service_provider)
            self._dvt.perform_handshake()
            self._location_sim = LocationSimulation(self._dvt)
        self._location_sim.set(lat, lng)

    def clear_location(self) -> None:
        """Reset GPS to the real location and close the held DVT session."""
        try:
            if self._location_sim is not None:
                self._location_sim.clear()
        finally:
            if self._dvt is not None:
                try:
                    self._dvt.close()
                except Exception:
                    pass
            self._dvt = None
            self._location_sim = None

    def disable_wifi(self) -> None:
        """Turn off WiFi on the connected iPhone."""
        from pymobiledevice3.services.mobile_config import MobileConfigService
        MobileConfigService(lockdown=self.service_provider).set_wifi_power_state(False)

    def enable_wifi(self) -> None:
        """Turn on WiFi on the connected iPhone.

        Retries once with a fresh connection if the first attempt fails
        (lockdown/RSD can go stale after WiFi toggle on iOS 17+).
        """
        from pymobiledevice3.services.mobile_config import MobileConfigService
        try:
            MobileConfigService(lockdown=self.service_provider).set_wifi_power_state(True)
        except Exception:
            self._refresh_connection()
            MobileConfigService(lockdown=self.service_provider).set_wifi_power_state(True)

    def _refresh_connection(self) -> None:
        """Re-establish USB lockdown (and tunneld for iOS 17+)."""
        self._lockdown = create_using_usbmux(autopair=True)
        self._ios_version = self._lockdown.product_version
        if self._is_ios17_plus():
            self._connect_tunneld()
