"""Tests for the SQLite state store — uses a tmp dir, never touches ~/.geospoof."""

from __future__ import annotations

import pytest

from geospoof.state import StateStore


@pytest.fixture()
def store(tmp_path):
    s = StateStore(state_dir=tmp_path / "geospoof")
    yield s
    s.close()


def test_record_and_get(store):
    store.record("wifi", "wifi_was_enabled", "true")
    assert store.get("wifi", "wifi_was_enabled") == "true"


def test_get_returns_latest(store):
    store.record("wifi", "k", "old")
    store.record("wifi", "k", "new")
    assert store.get("wifi", "k") == "new"


def test_get_missing_returns_none(store):
    assert store.get("wifi", "missing") is None


def test_get_all(store):
    store.record("nat_plist", "a", "1")
    store.record("nat_plist", "b", "2")
    assert store.get_all("nat_plist") == [("a", "1"), ("b", "2")]


def test_clear_category(store):
    store.record("wifi", "k", "v")
    store.record("nat_plist", "k", "v")
    store.clear("wifi")
    assert store.get("wifi", "k") is None
    assert store.get("nat_plist", "k") == "v"


def test_has_orphans_and_clear_all(store):
    assert not store.has_orphans()
    store.record("wifi", "k", "v")
    assert store.has_orphans()
    store.clear_all()
    assert not store.has_orphans()


def test_backup_and_restore_file(store, tmp_path):
    original = tmp_path / "config.plist"
    original.write_text("original")

    store.backup_file(original, "nat_plist")
    assert store.get("nat_plist", "backup_path")

    # Mutate the original, then restore from backup
    original.write_text("mutated")
    assert store.restore_file("nat_plist") is True
    assert original.read_text() == "original"
    # category cleared after restore
    assert store.get("nat_plist", "backup_path") is None


def test_restore_file_no_backup(store):
    assert store.restore_file("nat_plist") is False
