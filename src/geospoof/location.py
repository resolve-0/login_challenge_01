"""Location profiles, presets, and resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass

import geonamescache
from babel.languages import get_official_languages
from timezonefinder import TimezoneFinder


@dataclass(frozen=True)
class LocationProfile:
    name: str
    latitude: float
    longitude: float
    country_code: str
    timezone: str
    language: str
    accept_language: str


# ── Preset cities ──────────────────────────────────────────────────────────

PRESETS: dict[str, LocationProfile] = {
    "zurich": LocationProfile(
        "Zurich, Switzerland", 47.3769, 8.5417, "CH",
        "Europe/Zurich", "de-CH", "de-CH,de;q=0.9,en;q=0.5",
    ),
    "paris": LocationProfile(
        "Paris, France", 48.8566, 2.3522, "FR",
        "Europe/Paris", "fr-FR", "fr-FR,fr;q=0.9,en;q=0.5",
    ),
    "tokyo": LocationProfile(
        "Tokyo, Japan", 35.6762, 139.6503, "JP",
        "Asia/Tokyo", "ja-JP", "ja-JP,ja;q=0.9,en;q=0.5",
    ),
    "new-york": LocationProfile(
        "New York, USA", 40.7128, -74.0060, "US",
        "America/New_York", "en-US", "en-US,en;q=0.9",
    ),
    "london": LocationProfile(
        "London, United Kingdom", 51.5074, -0.1278, "GB",
        "Europe/London", "en-GB", "en-GB,en;q=0.9",
    ),
    "berlin": LocationProfile(
        "Berlin, Germany", 52.5200, 13.4050, "DE",
        "Europe/Berlin", "de-DE", "de-DE,de;q=0.9,en;q=0.5",
    ),
    "mumbai": LocationProfile(
        "Mumbai, India", 19.0760, 72.8777, "IN",
        "Asia/Kolkata", "hi-IN", "hi-IN,hi;q=0.9,en-IN;q=0.7,en;q=0.5",
    ),
    "sydney": LocationProfile(
        "Sydney, Australia", -33.8688, 151.2093, "AU",
        "Australia/Sydney", "en-AU", "en-AU,en;q=0.9",
    ),
    "sao-paulo": LocationProfile(
        "São Paulo, Brazil", -23.5505, -46.6333, "BR",
        "America/Sao_Paulo", "pt-BR", "pt-BR,pt;q=0.9,en;q=0.5",
    ),
    "dubai": LocationProfile(
        "Dubai, UAE", 25.2048, 55.2708, "AE",
        "Asia/Dubai", "ar-AE", "ar-AE,ar;q=0.9,en;q=0.5",
    ),
    "singapore": LocationProfile(
        "Singapore", 1.3521, 103.8198, "SG",
        "Asia/Singapore", "en-SG", "en-SG,en;q=0.9,zh;q=0.5",
    ),
    "toronto": LocationProfile(
        "Toronto, Canada", 43.6532, -79.3832, "CA",
        "America/Toronto", "en-CA", "en-CA,en;q=0.9,fr;q=0.5",
    ),
}


# ── Resolution ─────────────────────────────────────────────────────────────

_COORD_RE = re.compile(
    r"^(?P<lat>-?\d+(?:\.\d+)?)\s*,\s*(?P<lng>-?\d+(?:\.\d+)?)$"
)

_tf = TimezoneFinder()


def _language_for_country(country_code: str) -> tuple[str, str]:
    """Return (language tag, accept-language header) for a country."""
    try:
        langs = get_official_languages(country_code)
        lang = langs[0] if langs else "en"
        tag = f"{lang}-{country_code}"
        accept = f"{tag},{lang};q=0.9,en;q=0.5"
        return tag, accept
    except Exception:
        return f"en-{country_code}", f"en-{country_code},en;q=0.9"


def _profile_from_coords(
    lat: float, lng: float, name: str | None = None, country_code: str | None = None,
) -> LocationProfile:
    """Build a LocationProfile from raw coordinates."""
    tz = _tf.timezone_at(lat=lat, lng=lng) or "UTC"
    cc = country_code or "XX"
    lang, accept = _language_for_country(cc)
    display = name or f"({lat}, {lng})"
    return LocationProfile(display, lat, lng, cc, tz, lang, accept)


def _search_geonamescache(query: str) -> LocationProfile | None:
    """Search the geonamescache database for a matching city."""
    gc = geonamescache.GeonamesCache()
    cities = gc.get_cities()
    countries = gc.get_countries()
    q = query.lower()

    best = None
    best_pop = 0

    for city in cities.values():
        if city["name"].lower() == q:
            pop = city.get("population", 0)
            if pop > best_pop:
                best = city
                best_pop = pop
                continue

        alt = city.get("alternatenames", [])
        alt_names = [a.lower() for a in alt] if isinstance(alt, list) else [str(alt).lower()]
        if q in alt_names:
            pop = city.get("population", 0)
            if pop > best_pop:
                best = city
                best_pop = pop

    if best is None:
        return None

    cc = best["countrycode"]
    country_name = countries.get(cc, {}).get("name", cc)
    display = f"{best['name']}, {country_name}"
    lat = best["latitude"]
    lng = best["longitude"]
    return _profile_from_coords(lat, lng, name=display, country_code=cc)


def resolve(query: str) -> LocationProfile:
    """Resolve a query to a LocationProfile.

    Resolution order:
    1. Exact preset match
    2. "lat,lng" coordinate pair
    3. geonamescache city search
    """
    # 1. Preset lookup
    key = query.lower().strip()
    if key in PRESETS:
        return PRESETS[key]

    # 2. Coordinate pair
    m = _COORD_RE.match(query.strip())
    if m:
        lat, lng = float(m["lat"]), float(m["lng"])
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise ValueError(
                f"Coordinates out of range: ({lat}, {lng}).\n"
                f"Latitude must be [-90, 90], longitude [-180, 180]."
            )
        return _profile_from_coords(lat, lng)

    # 3. Geonamescache search
    profile = _search_geonamescache(query)
    if profile is not None:
        return profile

    raise ValueError(
        f"Could not resolve location: {query!r}\n"
        f"Try a preset name, 'lat,lng' coordinates, or a major city name.\n"
        f"Run 'geospoof locations' to see available presets."
    )
