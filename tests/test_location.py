"""Tests for location resolution — offline, no device needed."""

from __future__ import annotations

import pytest

from geospoof.location import (
    PRESETS,
    LocationProfile,
    _language_for_country,
    resolve,
)


def test_resolve_preset_exact():
    profile = resolve("zurich")
    assert profile is PRESETS["zurich"]
    assert profile.country_code == "CH"


def test_resolve_preset_case_insensitive():
    assert resolve("  ZURICH ") is PRESETS["zurich"]


def test_resolve_coordinates():
    profile = resolve("47.3769,8.5417")
    assert isinstance(profile, LocationProfile)
    assert profile.latitude == pytest.approx(47.3769)
    assert profile.longitude == pytest.approx(8.5417)
    # timezone derived from coords
    assert profile.timezone != ""


def test_resolve_coordinates_with_spaces():
    profile = resolve("47.3769, 8.5417")
    assert profile.latitude == pytest.approx(47.3769)


@pytest.mark.parametrize("bad", ["91,0", "-91,0", "0,181", "0,-181"])
def test_resolve_coordinates_out_of_range(bad):
    with pytest.raises(ValueError, match="out of range"):
        resolve(bad)


def test_resolve_geonames_city():
    # A major city not in PRESETS should resolve via geonamescache.
    profile = resolve("Madrid")
    assert profile.country_code == "ES"


def test_resolve_unknown_raises():
    with pytest.raises(ValueError, match="Could not resolve"):
        resolve("zzz-not-a-place-zzz")


def test_language_for_country_known():
    tag, accept = _language_for_country("FR")
    assert tag.endswith("-FR")
    assert "q=0.9" in accept


def test_language_for_country_fallback():
    tag, accept = _language_for_country("XX")
    assert tag == "en-XX"
    assert accept.startswith("en-XX")
