"""Tests for proxy providers — network calls are monkeypatched out."""

from __future__ import annotations

import pytest

from geospoof import proxy_provider as pp
from geospoof.proxy_provider import (
    ChainedProxyProvider,
    FreeProxyProvider,
    PaidProxyProvider,
    ProxyInfo,
    ProxyProvider,
)


def _list_response(entries):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"proxies": entries}

    return _Resp()


def _entry(ip, port, country="Switzerland"):
    return {"ip": ip, "port": port, "ip_data": {"countryName": country}}


def test_free_provider_empty_list_raises(monkeypatch):
    monkeypatch.setattr(pp.requests, "get", lambda *a, **k: _list_response([]))
    with pytest.raises(RuntimeError, match="No free proxies"):
        FreeProxyProvider().get_proxy("CH")


def test_free_provider_skips_bad_entries_and_verifies(monkeypatch):
    entries = [
        {"ip": None, "port": 80},          # bad
        _entry("1.2.3.4", 8080),           # good
    ]
    monkeypatch.setattr(pp.requests, "get", lambda *a, **k: _list_response(entries))
    # only 1.2.3.4 verifies
    monkeypatch.setattr(
        pp, "_verify_proxy", lambda proxy, urls, timeout: proxy.host == "1.2.3.4"
    )
    proxy = FreeProxyProvider().get_proxy("CH")
    assert proxy.host == "1.2.3.4"
    assert proxy.port == 8080
    assert proxy.protocol == "http"


def test_free_provider_none_verify_raises(monkeypatch):
    monkeypatch.setattr(
        pp.requests, "get", lambda *a, **k: _list_response([_entry("1.1.1.1", 80)])
    )
    monkeypatch.setattr(pp, "_verify_proxy", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="none responded"):
        FreeProxyProvider().get_proxy("CH")


def test_free_provider_respects_candidate_cap(monkeypatch):
    seen = []

    def fake_verify(proxy, urls, timeout):
        seen.append(proxy.host)
        return False

    entries = [_entry(f"10.0.0.{i}", 80) for i in range(50)]
    monkeypatch.setattr(pp.requests, "get", lambda *a, **k: _list_response(entries))
    monkeypatch.setattr(pp, "_verify_proxy", fake_verify)
    with pytest.raises(RuntimeError):
        FreeProxyProvider(candidate_cap=3).get_proxy("CH")
    assert len(seen) == 3


def test_paid_provider_unset_raises(monkeypatch):
    monkeypatch.delenv("GEOSPOOF_PROXY_URL", raising=False)
    with pytest.raises(RuntimeError, match="not set"):
        PaidProxyProvider().get_proxy("CH")


def test_paid_provider_parses_env(monkeypatch):
    monkeypatch.setenv("GEOSPOOF_PROXY_URL", "http://1.2.3.4:8080")
    proxy = PaidProxyProvider().get_proxy("ch")
    assert proxy.host == "1.2.3.4"
    assert proxy.port == 8080
    assert proxy.country_code == "CH"


def test_paid_provider_rejects_bad_url(monkeypatch):
    monkeypatch.setenv("GEOSPOOF_PROXY_URL", "socks5://1.2.3.4:1080")
    with pytest.raises(RuntimeError, match="http://host:port"):
        PaidProxyProvider().get_proxy("CH")


class _Static(ProxyProvider):
    def __init__(self, proxy=None, error=None):
        self._proxy = proxy
        self._error = error

    def get_proxy(self, country_code):
        if self._error:
            raise RuntimeError(self._error)
        return self._proxy


def test_chain_falls_through_to_next():
    good = ProxyInfo("9.9.9.9", 80, "http", "CH", "CH")
    chain = ChainedProxyProvider([_Static(error="boom"), _Static(proxy=good)])
    assert chain.get_proxy("CH") is good


def test_chain_all_fail_raises():
    chain = ChainedProxyProvider([_Static(error="a"), _Static(error="b")])
    with pytest.raises(RuntimeError, match="No proxy provider"):
        chain.get_proxy("CH")


def test_chain_requires_providers():
    with pytest.raises(ValueError):
        ChainedProxyProvider([])
