"""Rich terminal output helpers."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from geospoof.location import LocationProfile

console = Console()


def print_resolve(profile: LocationProfile) -> None:
    """Print resolved location details."""
    console.print("\n  Resolving...", style="dim")
    console.print(
        f"    → [bold]{profile.name}[/bold] "
        f"({profile.latitude}, {profile.longitude}) | "
        f"TZ: {profile.timezone} | Lang: {profile.language}"
    )


def print_device_connected(device_name: str, ios_version: str) -> None:
    console.print("\n  Setting iPhone GPS...", style="dim")
    console.print(f"    → Connected to {device_name} (iOS {ios_version})")


def print_ddi_mounted() -> None:
    console.print("    → Developer image mounted")


def print_gps_set(lat: float, lng: float) -> None:
    console.print(f"    → GPS set to ({lat}, {lng}) [green]✓[/green]")


def print_gps_cleared() -> None:
    console.print("    → GPS reset to real location [green]✓[/green]")


def print_proxy_starting(country_code: str) -> None:
    console.print(f"\n  Starting proxy ({country_code})...", style="dim")


def print_upstream_proxy(host: str, port: int, country: str) -> None:
    console.print(f"    → Upstream proxy: {host}:{port} ({country})")


def print_local_proxy(port: int) -> None:
    console.print(f"    → Local proxy listening on 0.0.0.0:{port} [green]✓[/green]")


def _get_local_ip() -> str:
    """Get the machine's LAN IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def print_summary(
    profile: LocationProfile,
    proxy_port: int | None,
    wifi_isolated: bool = False,
    usb_iface: str | None = None,
) -> None:
    """Print the final summary box."""
    lines = [
        f"[bold]Location:[/bold] {profile.name}",
        f"[bold]iPhone GPS:[/bold] ({profile.latitude}, {profile.longitude}) [green]✓[/green]",
    ]
    if wifi_isolated:
        net_label = f"USB ({usb_iface})" if usb_iface else "USB"
        lines.append(f"[bold]WiFi:[/bold]       disabled — internet via {net_label} [green]✓[/green]")
    if proxy_port is not None:
        # When WiFi is isolated the iPhone is on the USB sharing subnet;
        # it can only reach the Mac at the gateway (192.168.2.1), not the
        # Mac's WiFi LAN IP.
        proxy_ip = "192.168.2.1" if wifi_isolated else _get_local_ip()
        lines.append(f"[bold]Proxy:[/bold]      http://{proxy_ip}:{proxy_port}")
        lines.append("")
        if wifi_isolated:
            lines.append("[dim]iPhone setup: Settings → Cellular → Cellular Data Options → Proxy → Manual[/dim]")
        else:
            lines.append("[dim]iPhone setup: Settings → Wi-Fi → Proxy → Manual[/dim]")
        lines.append(f"  Server: {proxy_ip}   Port: {proxy_port}")

    panel = Panel(
        "\n".join(lines),
        border_style="bright_cyan",
        padding=(1, 2),
    )
    console.print("\n")
    console.print(panel)
    console.print("  Press [bold]Ctrl+C[/bold] to stop and reset.\n")


def print_summary_proxy_only(profile: LocationProfile, proxy_port: int) -> None:
    """Print summary when running in proxy-only mode."""
    local_ip = _get_local_ip()
    lines = [
        f"[bold]Location:[/bold] {profile.name}",
        f"[bold]Proxy:[/bold]      http://{local_ip}:{proxy_port}",
        "",
        "[dim]iPhone setup: Settings → Wi-Fi → Proxy → Manual[/dim]",
        f"  Server: {local_ip}   Port: {proxy_port}",
    ]
    panel = Panel(
        "\n".join(lines),
        border_style="bright_cyan",
        padding=(1, 2),
    )
    console.print("\n")
    console.print(panel)
    console.print("  Press [bold]Ctrl+C[/bold] to stop.\n")


def print_summary_gps_only(
    profile: LocationProfile,
    wifi_isolated: bool = False,
    usb_iface: str | None = None,
) -> None:
    """Print summary when running in GPS-only mode."""
    lines = [
        f"[bold]Location:[/bold] {profile.name}",
        f"[bold]iPhone GPS:[/bold] ({profile.latitude}, {profile.longitude}) [green]✓[/green]",
    ]
    if wifi_isolated:
        net_label = f"USB ({usb_iface})" if usb_iface else "USB"
        lines.append(f"[bold]WiFi:[/bold]       disabled — internet via {net_label} [green]✓[/green]")
    panel = Panel(
        "\n".join(lines),
        border_style="bright_cyan",
        padding=(1, 2),
    )
    console.print("\n")
    console.print(panel)
    console.print("  Press [bold]Ctrl+C[/bold] to stop and reset GPS.\n")


def print_locations_table(presets: dict[str, LocationProfile]) -> None:
    """Print a table of all preset locations."""
    table = Table(title="Available Location Presets", border_style="bright_cyan")
    table.add_column("Name", style="bold")
    table.add_column("Location")
    table.add_column("Coordinates", style="dim")
    table.add_column("Country", justify="center")
    table.add_column("Timezone", style="dim")

    for key, p in sorted(presets.items()):
        table.add_row(key, p.name, f"{p.latitude}, {p.longitude}", p.country_code, p.timezone)

    console.print(table)


def print_orphan_recovery() -> None:
    console.print("\n  [yellow]Recovering from previous crash...[/yellow]", style="dim")


def print_orphan_recovered() -> None:
    console.print("    → Previous state cleaned up [green]✓[/green]")


def print_wifi_disabling() -> None:
    console.print("\n  Disabling iPhone WiFi...", style="dim")


def print_wifi_disabled() -> None:
    console.print("    → WiFi disabled on iPhone [green]✓[/green]")


def print_wifi_restored() -> None:
    console.print("    → WiFi re-enabled on iPhone [green]✓[/green]")


def print_usb_network_starting() -> None:
    console.print("\n  Starting USB Internet Sharing...", style="dim")


def print_usb_network_active(iface: str, source: str) -> None:
    console.print(f"    → Sharing {source} → {iface} (USB) [green]✓[/green]")


def print_usb_network_stopped() -> None:
    console.print("    → Internet Sharing stopped [green]✓[/green]")


def print_vpn_starting(conf_name: str) -> None:
    console.print(f"\n  Starting WireGuard VPN ({conf_name})...", style="dim")


def print_vpn_active() -> None:
    console.print("    → VPN tunnel up — egress via WireGuard [green]✓[/green]")


def print_vpn_stopped() -> None:
    console.print("    → VPN tunnel down [green]✓[/green]")


def print_error(message: str) -> None:
    console.print(f"\n  [red bold]Error:[/red bold] {message}")


def print_warning(message: str) -> None:
    console.print(f"\n  [yellow bold]Warning:[/yellow bold] {message}")
