"""Pluggable proxy providers for geo-targeted proxies."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urlparse

import requests


@dataclass(frozen=True)
class ProxyInfo:
    host: str
    port: int
    protocol: str  # "http" — the only scheme the local proxy server can chain to
    country: str
    country_code: str

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"


# URLs used to confirm a candidate proxy actually relays traffic.
DEFAULT_VERIFY_URLS = ("http://httpbin.org/ip", "http://icanhazip.com")


def _verify_proxy(proxy: ProxyInfo, verify_urls: tuple[str, ...], timeout: float) -> bool:
    """Quick check that the proxy is alive using multiple verification URLs."""
    for url in verify_urls:
        try:
            resp = requests.get(
                url,
                proxies={"http": proxy.url, "https": proxy.url},
                timeout=timeout,
            )
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            continue
    return False


class ProxyProvider(ABC):
    """Base class for proxy providers."""

    @abstractmethod
    def get_proxy(self, country_code: str) -> ProxyInfo:
        """Get a working proxy for the given country code.

        Raises:
            RuntimeError: If no proxy could be found.
        """


class ChainedProxyProvider(ProxyProvider):
    """Tries each provider in order until one yields a verified proxy."""

    def __init__(self, providers: list[ProxyProvider]) -> None:
        if not providers:
            raise ValueError("ChainedProxyProvider needs at least one provider.")
        self._providers = providers

    def get_proxy(self, country_code: str) -> ProxyInfo:
        errors: list[str] = []
        for provider in self._providers:
            try:
                return provider.get_proxy(country_code)
            except RuntimeError as exc:
                errors.append(f"{type(provider).__name__}: {exc}")
        raise RuntimeError(
            "No proxy provider could supply a working proxy for "
            f"{country_code.upper()}:\n  " + "\n  ".join(errors)
        )


class PaidProxyProvider(ProxyProvider):
    """Uses a fixed upstream proxy from the GEOSPOOF_PROXY_URL env var.

    Lets a user drop in a reliable (e.g. paid) HTTP proxy without code changes.
    Format: ``http://[user:pass@]host:port``. If the var is unset, this provider
    raises so a ChainedProxyProvider falls through to the next one.
    """

    ENV_VAR = "GEOSPOOF_PROXY_URL"

    def __init__(self, env_var: str | None = None) -> None:
        self._env_var = env_var or self.ENV_VAR

    def get_proxy(self, country_code: str) -> ProxyInfo:
        raw = os.environ.get(self._env_var, "").strip()
        if not raw:
            raise RuntimeError(f"{self._env_var} not set.")

        parsed = urlparse(raw)
        if parsed.scheme != "http" or not parsed.hostname or not parsed.port:
            raise RuntimeError(
                f"{self._env_var} must be 'http://host:port' (got {raw!r})."
            )

        return ProxyInfo(
            host=parsed.hostname,
            port=parsed.port,
            protocol="http",
            country=country_code.upper(),
            country_code=country_code.upper(),
        )


class FreeProxyProvider(ProxyProvider):
    """Fetches geo-targeted HTTP proxies from the ProxyScrape API."""

    API_URL = "https://api.proxyscrape.com/v4/free-proxy-list/get"

    def __init__(
        self,
        candidate_cap: int = 20,
        verify_timeout: float = 8.0,
        verify_urls: tuple[str, ...] = DEFAULT_VERIFY_URLS,
        max_verify_workers: int = 8,
    ) -> None:
        self.candidate_cap = candidate_cap
        self.verify_timeout = verify_timeout
        self.verify_urls = verify_urls
        self.max_verify_workers = max_verify_workers

    def get_proxy(self, country_code: str) -> ProxyInfo:
        cc = country_code.upper()

        try:
            resp = requests.get(
                self.API_URL,
                params={
                    "request": "display_proxies",
                    "country": cc,
                    "protocol": "http",
                    "proxy_format": "protocolipport",
                    "format": "json",
                    "timeout": "5000",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"Failed to fetch proxy list for {cc}: {exc}") from exc

        candidates = self._parse_candidates(data, cc)
        if not candidates:
            raise RuntimeError(
                f"No free proxies available for country {cc}.\n"
                f"Try again later or set GEOSPOOF_PROXY_URL to a paid proxy."
            )

        verified = self._first_verified(candidates)
        if verified is not None:
            return verified

        raise RuntimeError(
            f"Found proxies for {cc} but none responded.\n"
            f"Free proxies can be unreliable — try again or set GEOSPOOF_PROXY_URL."
        )

    def _parse_candidates(self, data: dict, cc: str) -> list[ProxyInfo]:
        candidates: list[ProxyInfo] = []
        for entry in data.get("proxies", [])[: self.candidate_cap]:
            host = entry.get("ip")
            port = entry.get("port")
            if not host or not port:
                continue
            country = entry.get("ip_data", {}).get("countryName", cc)
            candidates.append(
                ProxyInfo(
                    host=host,
                    port=int(port),
                    protocol="http",
                    country=country,
                    country_code=cc,
                )
            )
        return candidates

    def _first_verified(self, candidates: list[ProxyInfo]) -> ProxyInfo | None:
        """Verify candidates concurrently, return the first one that responds."""
        workers = min(self.max_verify_workers, len(candidates))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _verify_proxy, proxy, self.verify_urls, self.verify_timeout
                ): proxy
                for proxy in candidates
            }
            for future in as_completed(futures):
                if future.result():
                    return futures[future]
        return None


def default_provider() -> ProxyProvider:
    """The provider chain the CLI uses: paid env override, then free list."""
    return ChainedProxyProvider([PaidProxyProvider(), FreeProxyProvider()])
