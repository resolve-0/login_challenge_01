"""Tests for the WireGuard VPN egress — subprocess and wg-quick are stubbed."""

from __future__ import annotations

import subprocess

import pytest

from geospoof import vpn as vpn_mod
from geospoof.state import StateStore
from geospoof.vpn import WireGuardVPN, recover


@pytest.fixture()
def state(tmp_path):
    s = StateStore(state_dir=tmp_path / "geospoof")
    yield s
    s.close()


@pytest.fixture()
def conf(tmp_path):
    p = tmp_path / "wg-CH-1031.conf"
    p.write_text("[Interface]\n")
    return p


def _result(rc=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout="", stderr=stderr)


def test_up_records_state_and_runs(monkeypatch, state, conf):
    calls = []
    monkeypatch.setattr(vpn_mod.shutil, "which", lambda _: "/usr/bin/wg-quick")
    monkeypatch.setattr(
        vpn_mod.subprocess, "run", lambda *a, **k: calls.append(a) or _result(0)
    )

    WireGuardVPN(conf, state).up()

    assert state.get("vpn", "started_by_us") == "true"
    assert state.get("vpn", "conf_path") == str(conf.resolve())
    assert calls  # wg-quick up invoked


def test_up_missing_binary_raises(monkeypatch, state, conf):
    monkeypatch.setattr(vpn_mod.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="wg-quick not found"):
        WireGuardVPN(conf, state).up()


def test_up_missing_conf_raises(monkeypatch, state, tmp_path):
    monkeypatch.setattr(vpn_mod.shutil, "which", lambda _: "/usr/bin/wg-quick")
    with pytest.raises(RuntimeError, match="config not found"):
        WireGuardVPN(tmp_path / "nope.conf", state).up()


def test_up_failure_clears_state(monkeypatch, state, conf):
    monkeypatch.setattr(vpn_mod.shutil, "which", lambda _: "/usr/bin/wg-quick")
    monkeypatch.setattr(vpn_mod.subprocess, "run", lambda *a, **k: _result(1, "boom"))
    with pytest.raises(RuntimeError, match="Failed to bring up"):
        WireGuardVPN(conf, state).up()
    assert state.get("vpn", "started_by_us") is None


def test_down_clears_state(monkeypatch, state, conf):
    state.record("vpn", "started_by_us", "true")
    state.record("vpn", "conf_path", str(conf))
    monkeypatch.setattr(vpn_mod.subprocess, "run", lambda *a, **k: _result(0))
    WireGuardVPN(conf, state).down()
    assert state.get("vpn", "started_by_us") is None


def test_recover_brings_down_orphan(monkeypatch, state, conf):
    state.record("vpn", "started_by_us", "true")
    state.record("vpn", "conf_path", str(conf))
    calls = []
    monkeypatch.setattr(vpn_mod.shutil, "which", lambda _: "/usr/bin/wg-quick")
    monkeypatch.setattr(
        vpn_mod.subprocess, "run", lambda *a, **k: calls.append(a) or _result(0)
    )
    recover(state)
    assert calls  # wg-quick down invoked
    assert state.get("vpn", "started_by_us") is None


def test_recover_noop_when_nothing_started(monkeypatch, state):
    called = []
    monkeypatch.setattr(vpn_mod.subprocess, "run", lambda *a, **k: called.append(1))
    recover(state)
    assert not called
