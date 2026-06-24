"""Click CLI entry point — wires all components together."""

from __future__ import annotations

import signal
import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from geospoof.state import StateStore

from geospoof.console import (
    console,
    print_ddi_mounted,
    print_device_connected,
    print_error,
    print_gps_cleared,
    print_gps_set,
    print_local_proxy,
    print_locations_table,
    print_orphan_recovered,
    print_orphan_recovery,
    print_proxy_starting,
    print_resolve,
    print_summary,
    print_summary_gps_only,
    print_summary_proxy_only,
    print_upstream_proxy,
    print_usb_network_active,
    print_usb_network_starting,
    print_usb_network_stopped,
    print_warning,
    print_wifi_disabled,
    print_wifi_disabling,
    print_wifi_restored,
)
from geospoof.location import PRESETS, resolve


class _GeoSpoofGroup(click.Group):
    """Custom group that treats unknown subcommands as location arguments."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # If the first arg looks like a known subcommand, let Click handle it.
        # Otherwise, insert the 'spoof' subcommand so the location arg routes there.
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["spoof"] + args
        return super().parse_args(ctx, args)


@click.group(cls=_GeoSpoofGroup)
def cli() -> None:
    """geospoof — One-command location + IP spoofing for iOS testing.

    \b
    Note: iOS 17+ requires tunneld running in another terminal:
        sudo python3 -m pymobiledevice3 remote tunneld

    \b
    Examples:
        sudo geospoof zurich
        sudo geospoof "47.3769,8.5417"
        sudo geospoof paris --proxy-port 9090
        sudo geospoof zurich --no-proxy
        sudo geospoof zurich --no-proxy --keep-wifi
        sudo geospoof zurich --vpn wg-CH-1031.conf
        geospoof zurich --no-gps
        geospoof locations
        geospoof resolve zurich
    """


@cli.command(hidden=True)
@click.argument("location")
@click.option("--no-proxy", is_flag=True, help="GPS only, skip proxy setup.")
@click.option("--no-gps", is_flag=True, help="Proxy only, skip GPS spoofing.")
@click.option("--keep-wifi", is_flag=True, help="Don't disable iPhone WiFi (old behavior).")
@click.option("--proxy-port", default=8888, type=int, help="Local proxy port.", show_default=True)
@click.option(
    "--vpn",
    "vpn_conf",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="WireGuard .conf for IP egress (replaces the HTTP proxy).",
)
@click.option("--debug", is_flag=True, help="Show debug output (subprocess calls, return codes).")
def spoof(
    location: str,
    no_proxy: bool,
    no_gps: bool,
    keep_wifi: bool,
    proxy_port: int,
    vpn_conf: str | None,
    debug: bool,
) -> None:
    """Spoof location (default command — invoked when you pass a location)."""
    from geospoof.log import setup as setup_logging
    from geospoof.state import StateStore

    setup_logging(debug)

    # Resolve location
    try:
        profile = resolve(location)
    except ValueError as exc:
        print_error(str(exc))
        sys.exit(1)

    print_resolve(profile)

    # ── Egress mode: VPN replaces the HTTP proxy ──────────────────────
    # --vpn provides the IP-spoofing egress, so the local proxy is skipped.
    use_proxy = not no_proxy and vpn_conf is None

    # ── Validate flag combination ─────────────────────────────────────
    if no_gps and not use_proxy and vpn_conf is None:
        print_error("--no-gps with no proxy and no --vpn leaves nothing to do.")
        sys.exit(1)

    # ── Orphan recovery ───────────────────────────────────────────────
    state = StateStore()
    if state.has_orphans():
        print_orphan_recovery()
        _recover_orphans(state)
        print_orphan_recovered()

    device = None
    proxy_server = None
    sharing = None
    vpn = None
    wifi_was_disabled = False
    usb_iface = None
    tearing_down = False

    # ── Early signal handlers ─────────────────────────────────────────
    def _cleanup(signum: int = 0, frame: object = None) -> None:
        nonlocal tearing_down
        if tearing_down:
            return
        tearing_down = True
        console.print("\n  Shutting down...", style="dim")
        if proxy_server:
            proxy_server.stop()
            console.print("    → Proxy stopped [green]✓[/green]")
        _teardown(state, sharing, device, wifi_was_disabled, vpn)
        console.print()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        # ── GPS setup ──────────────────────────────────────────────────────
        if not no_gps:
            device = _setup_gps(profile, state)

        # ── WiFi isolation + USB Internet ─────────────────────────────────
        if device and not keep_wifi:
            sharing, usb_iface, wifi_was_disabled = _isolate_wifi(device, state)

        # ── Egress: VPN tunnel or HTTP proxy ───────────────────────────────
        if vpn_conf is not None:
            vpn = _setup_vpn(vpn_conf, state)
        elif use_proxy:
            proxy_server = _setup_proxy(profile, proxy_port)
    except KeyboardInterrupt:
        _cleanup()
    except (RuntimeError, OSError) as exc:
        print_error(str(exc))
        _cleanup()

    # ── Summary ────────────────────────────────────────────────────────
    if not no_gps and proxy_server is not None:
        print_summary(profile, proxy_port, wifi_isolated=wifi_was_disabled, usb_iface=usb_iface)
    elif proxy_server is not None:
        print_summary_proxy_only(profile, proxy_port)
    elif not no_gps:
        print_summary_gps_only(profile, wifi_isolated=wifi_was_disabled, usb_iface=usb_iface)
    if vpn is not None:
        console.print("  [bold]VPN:[/bold] egress via WireGuard — IP spoofed [green]✓[/green]\n")

    # ── Wait for Ctrl+C ───────────────────────────────────────────────
    # Block main thread
    try:
        signal.pause()
    except AttributeError:
        import time
        while True:
            time.sleep(3600)


def _setup_gps(profile, state):
    """Connect to the iPhone and set GPS. Exits the process on failure."""
    from geospoof.device import iOSDevice

    device = iOSDevice()
    try:
        info = device.connect()
        print_device_connected(info.name, info.ios_version)
        print_ddi_mounted()
        device.set_location(profile.latitude, profile.longitude)
        print_gps_set(profile.latitude, profile.longitude)
    except (ConnectionError, PermissionError) as exc:
        print_error(str(exc))
        state.close()
        sys.exit(1)
    except Exception as exc:
        print_error(f"Failed to set GPS: {exc}")
        state.close()
        sys.exit(1)
    return device


def _isolate_wifi(device, state):
    """Disable iPhone WiFi and start USB Internet Sharing.

    Returns (sharing, usb_iface, wifi_was_disabled). On a sharing failure the
    WiFi is re-enabled so the iPhone isn't left without connectivity.
    """
    sharing = None
    usb_iface = None
    wifi_was_disabled = False

    # Disable WiFi
    try:
        print_wifi_disabling()
        state.record("wifi", "wifi_was_enabled", "true")
        device.disable_wifi()
        wifi_was_disabled = True
        print_wifi_disabled()
    except Exception as exc:
        print_warning(f"Could not disable WiFi: {exc}")
        state.clear("wifi")

    # Start Internet Sharing over USB
    try:
        from geospoof.network import InternetSharing

        print_usb_network_starting()
        sharing = InternetSharing(state)
        usb_iface, source_iface = sharing.start()
        print_usb_network_active(usb_iface, source_iface)
    except Exception as exc:
        print_warning(f"Could not start USB Internet Sharing: {exc}")
        sharing = None
        if wifi_was_disabled:
            try:
                device.enable_wifi()
                wifi_was_disabled = False
                state.clear("wifi")
                print_warning("WiFi re-enabled since USB Internet Sharing failed.")
            except Exception:
                print_warning("Could not re-enable WiFi — toggle it manually on the iPhone.")

    return sharing, usb_iface, wifi_was_disabled


def _setup_vpn(conf_path: str, state):
    """Bring up a WireGuard tunnel as the IP egress."""
    from pathlib import Path

    from geospoof.console import print_vpn_active, print_vpn_starting
    from geospoof.vpn import WireGuardVPN

    print_vpn_starting(Path(conf_path).name)
    vpn = WireGuardVPN(conf_path, state)
    vpn.up()
    print_vpn_active()
    return vpn


def _setup_proxy(profile, proxy_port: int):
    """Fetch a verified geo-proxy and start the local forwarding server."""
    from geospoof.proxy_provider import default_provider
    from geospoof.proxy_server import LocalProxyServer

    print_proxy_starting(profile.country_code)

    provider = default_provider()
    upstream = provider.get_proxy(profile.country_code)

    print_upstream_proxy(upstream.host, upstream.port, upstream.country)

    proxy_server = LocalProxyServer(upstream, port=proxy_port)
    proxy_server.start()

    print_local_proxy(proxy_port)
    return proxy_server


def _teardown(state, sharing, device, wifi_was_disabled: bool, vpn=None) -> None:
    """Tear down VPN, re-enable WiFi, stop Internet Sharing, clear GPS, close DB.

    WiFi is re-enabled while Internet Sharing is still running so the USB
    multiplexed link remains stable for the lockdown/RSD call.
    """
    # 1. Re-enable WiFi FIRST (USB link still stable)
    if wifi_was_disabled and device:
        try:
            device.enable_wifi()
            print_wifi_restored()
        except Exception:
            print_warning("Could not re-enable WiFi — toggle it manually on the iPhone.")
        state.clear("wifi")

    # 2. Bring down the VPN tunnel (restores normal egress before sharing stops)
    if vpn:
        from geospoof.console import print_vpn_stopped
        try:
            vpn.down()
            print_vpn_stopped()
        except Exception:
            print_warning("Could not bring down VPN — run 'wg-quick down <conf>' manually.")

    # 4. Stop Internet Sharing
    if sharing:
        try:
            sharing.stop()
            print_usb_network_stopped()
        except Exception:
            print_warning("Could not stop Internet Sharing — check System Preferences.")

    # 5. Clear GPS
    if device:
        try:
            device.clear_location()
            print_gps_cleared()
        except Exception:
            print_warning("Could not reset GPS — restart the iPhone to clear.")

    state.clear_all()
    state.close()


def _recover_orphans(state: StateStore) -> None:
    """Clean up leftover state from a previous crashed run."""
    from geospoof.network import InternetSharing
    from geospoof.vpn import recover as recover_vpn

    # Bring down a VPN tunnel left up by a previous run
    recover_vpn(state)

    # Stop Internet Sharing if we started it
    if state.get("internet_sharing", "started_by_us"):
        try:
            sharing = InternetSharing(state)
            sharing.stop()
        except Exception:
            pass

    # Re-enable WiFi if we disabled it
    if state.get("wifi", "wifi_was_enabled"):
        try:
            from geospoof.device import iOSDevice
            dev = iOSDevice()
            dev.connect()
            dev.enable_wifi()
        except Exception:
            pass  # device may not be connected anymore
        state.clear("wifi")

    state.clear_all()


@cli.command()
def locations() -> None:
    """List all available preset locations."""
    print_locations_table(PRESETS)


@cli.command("resolve")
@click.argument("query")
def resolve_cmd(query: str) -> None:
    """Resolve a location query and show details (no device needed)."""
    try:
        profile = resolve(query)
    except ValueError as exc:
        print_error(str(exc))
        sys.exit(1)

    console.print(f"\n  [bold]{profile.name}[/bold]")
    console.print(f"  Coordinates:  {profile.latitude}, {profile.longitude}")
    console.print(f"  Country:      {profile.country_code}")
    console.print(f"  Timezone:     {profile.timezone}")
    console.print(f"  Language:     {profile.language}")
    console.print(f"  Accept-Lang:  {profile.accept_language}")
    console.print()
