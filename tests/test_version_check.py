"""
Tests for version check module.
"""

import json

from trusty_cage.version_check import (
    _fetch_latest_version,
    _parse_version,
    check_for_updates,
)


class TestParseVersion:
    def test_standard_version(self):
        assert _parse_version("0.8.3") == (0, 8, 3)

    def test_major_version(self):
        assert _parse_version("1.0.0") == (1, 0, 0)

    def test_invalid_version(self):
        assert _parse_version("bad") == (0,)

    def test_none_version(self):
        assert _parse_version(None) == (0,)


class TestFetchLatestVersion:
    def test_returns_version_on_success(self, mocker):
        mock_response = mocker.MagicMock()
        mock_response.read.return_value = json.dumps(
            {"info": {"version": "0.9.0"}}
        ).encode()
        mock_response.__enter__ = mocker.MagicMock(return_value=mock_response)
        mock_response.__exit__ = mocker.MagicMock(return_value=False)
        mocker.patch(
            "trusty_cage.version_check.urllib.request.urlopen",
            return_value=mock_response,
        )
        assert _fetch_latest_version() == "0.9.0"

    def test_returns_none_on_failure(self, mocker):
        mocker.patch(
            "trusty_cage.version_check.urllib.request.urlopen",
            side_effect=Exception("network error"),
        )
        assert _fetch_latest_version() is None


class TestCheckForUpdates:
    def test_shows_update_when_outdated(self, mocker, capsys):
        mocker.patch("trusty_cage.version_check.__version__", "0.7.0")
        mocker.patch(
            "trusty_cage.version_check._fetch_latest_version", return_value="0.8.3"
        )
        mocker.patch("trusty_cage.version_check.needs_rebuild", return_value=False)
        check_for_updates()
        output = capsys.readouterr().out
        assert "0.8.3" in output
        assert "Update available" in output

    def test_shows_rebuild_when_image_stale(self, mocker, capsys):
        mocker.patch(
            "trusty_cage.version_check._fetch_latest_version", return_value="0.8.3"
        )
        mocker.patch("trusty_cage.version_check.needs_rebuild", return_value=True)
        check_for_updates()
        output = capsys.readouterr().out
        assert "rebuild-image" in output

    def test_silent_when_current(self, mocker, capsys):
        mocker.patch(
            "trusty_cage.version_check._fetch_latest_version", return_value="0.8.3"
        )
        mocker.patch("trusty_cage.version_check.needs_rebuild", return_value=False)
        check_for_updates()
        output = capsys.readouterr().out
        assert output == ""

    def test_silent_on_network_failure(self, mocker, capsys):
        mocker.patch(
            "trusty_cage.version_check._fetch_latest_version", return_value=None
        )
        mocker.patch("trusty_cage.version_check.needs_rebuild", return_value=False)
        check_for_updates()
        output = capsys.readouterr().out
        assert output == ""
