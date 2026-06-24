"""Tests for the CLI surface — offline subcommands and flag validation."""

from __future__ import annotations

from click.testing import CliRunner

from geospoof.cli import cli


def test_locations_lists_presets():
    result = CliRunner().invoke(cli, ["locations"])
    assert result.exit_code == 0
    assert "Zurich" in result.output


def test_resolve_subcommand():
    result = CliRunner().invoke(cli, ["resolve", "zurich"])
    assert result.exit_code == 0
    assert "47.3769" in result.output


def test_resolve_unknown_exits_1():
    result = CliRunner().invoke(cli, ["resolve", "zzz-not-a-place-zzz"])
    assert result.exit_code == 1
    assert "Could not resolve" in result.output


def test_bare_location_routes_to_spoof_and_validates_flags():
    # --no-gps + --no-proxy leaves nothing to do → exit 1, no device touched.
    result = CliRunner().invoke(cli, ["zurich", "--no-gps", "--no-proxy"])
    assert result.exit_code == 1
    assert "nothing to do" in result.output


def test_unresolvable_spoof_location_exits_1():
    result = CliRunner().invoke(cli, ["zzz-not-a-place-zzz", "--no-proxy"])
    assert result.exit_code == 1
    assert "Could not resolve" in result.output


def test_vpn_missing_conf_file_exits_2():
    # click validates --vpn path exists; a missing file is a usage error.
    result = CliRunner().invoke(cli, ["zurich", "--vpn", "/no/such/file.conf"])
    assert result.exit_code == 2
    assert "does not exist" in result.output
