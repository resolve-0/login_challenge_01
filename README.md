# geospoof

One-command location + IP spoofing CLI for iOS testing on macOS.

`geospoof` sets your connected iPhone's GPS to any city or coordinate **and** routes
its traffic through a geo-targeted proxy, so apps under test see a consistent location
and IP. Everything is reverted on `Ctrl+C` (and recovered automatically if a run crashes).

## How the GPS spoof works

GPS is set through pymobiledevice3's DVT `LocationSimulation` instrument — the **same
developer-tools channel Xcode uses** under *Devices & Simulators → Simulate Location*.
It affects the whole device, not just one app, and requires no jailbreak. There is no
on-device app that can do this from inside the iOS sandbox, so a Mac-side tool is the
right shape.

## Requirements

- macOS, Python 3.11+
- iPhone connected via USB, trusted, with **Developer Mode** enabled
  (Settings → Privacy & Security → Developer Mode)
- `sudo` for the GPS + Internet Sharing path (proxy-only mode needs no sudo)
- **iOS 17+** also needs the tunneld daemon running in another terminal:

  ```
  sudo python3 -m pymobiledevice3 remote tunneld
  ```

## Install

```bash
pip install -e .
# dev tooling (tests, lint, types):
pip install -e ".[dev]"
```

## Usage

```bash
sudo geospoof zurich                  # GPS + geo-proxy, isolate WiFi over USB
sudo geospoof "47.3769,8.5417"        # raw coordinates
sudo geospoof paris --proxy-port 9090
sudo geospoof zurich --no-proxy       # GPS only
sudo geospoof zurich --vpn wg-CH-1031.conf  # GPS + WireGuard egress
geospoof zurich --no-gps              # proxy only (no device, no sudo)
geospoof locations                    # list preset cities
geospoof resolve zurich               # show resolved location details
```

Flags: `--no-proxy`, `--no-gps`, `--keep-wifi`, `--proxy-port`, `--vpn`, `--debug`.

## IP egress: proxy vs WireGuard VPN

Two ways to spoof the **IP** half (GPS is always set via the DVT channel):

- **HTTP proxy** (default) — `default_provider()` chain; per-app proxy the iPhone points at.
- **WireGuard VPN** (`--vpn <conf>`) — runs `wg-quick up` on the Mac. With
  `AllowedIPs = 0.0.0.0/0` the whole machine's traffic (and any iPhone routed over USB
  Internet Sharing) exits through the tunnel. More reliable than free proxies; needs
  `wg-quick` (`brew install wireguard-tools`) and `sudo`. `--vpn` replaces the proxy.
  The tunnel is brought down on `Ctrl+C` and auto-recovered after a crash.

Neither improves GPS precision — IP geolocation is country/city-level at best; exact
coordinates come only from the simulated GPS. VPN `.conf` files hold private keys —
keep them out of git (`*.conf` is gitignored).

## Proxy reliability

Proxies are resolved through a provider chain (`proxy_provider.default_provider()`):

1. **`PaidProxyProvider`** — if `GEOSPOOF_PROXY_URL=http://[user:pass@]host:port` is set,
   that fixed upstream is used (recommended for reliable runs).
2. **`FreeProxyProvider`** — falls back to the free ProxyScrape list, verifying candidates
   concurrently and returning the first that responds.

The local server only chains to **HTTP** upstreams.

## Development

```bash
pytest            # unit tests — fully offline, no device/network
ruff check src tests
mypy src
```
