"""Tests for tsm/self_update.py — version parsing and helpers."""
import ssl
from unittest.mock import MagicMock, patch

from tsm.self_update import (
    _is_frozen,
    _nocache_url,
    _ssl_context,
    _ver_tuple,
    get_update_info,
    invalidate_update_cache,
)


class TestVerTuple:
    def test_basic_semver(self):
        assert _ver_tuple("1.2.3") == (1, 2, 3)

    def test_with_v_prefix(self):
        assert _ver_tuple("v1.2.3") == (1, 2, 3)

    def test_pre_release(self):
        assert _ver_tuple("1.2.3-beta") == (1, 2, 3)

    def test_empty_string(self):
        assert _ver_tuple("") == (0, 0, 0)

    def test_nonsense(self):
        assert _ver_tuple("abc") == (0, 0, 0)

    def test_comparison(self):
        assert _ver_tuple("1.3.0") > _ver_tuple("1.2.9")
        assert _ver_tuple("2.0.0") > _ver_tuple("1.99.99")
        assert _ver_tuple("1.2.0") == _ver_tuple("1.2.0")


class TestNoCacheUrl:
    def test_adds_ts_param(self):
        url = _nocache_url("https://example.com/api")
        assert "?ts=" in url

    def test_existing_query(self):
        url = _nocache_url("https://example.com/api?foo=bar")
        assert "&ts=" in url


class TestIsFrozen:
    def test_not_frozen_in_test(self):
        # Tests run from source, not PyInstaller
        assert _is_frozen() is False


class TestSslContext:
    def test_returns_ssl_context(self):
        ctx = _ssl_context()
        assert isinstance(ctx, ssl.SSLContext)

    def test_certificate_verification_enabled(self):
        """Verification must never be disabled — the fix only widens the trust
        store, it does not skip validation."""
        ctx = _ssl_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_load_default_certs_called_on_windows(self):
        ctx_mock = MagicMock(spec=ssl.SSLContext)
        with patch("ssl.create_default_context", return_value=ctx_mock), \
             patch("tsm.self_update.sys") as mock_sys:
            mock_sys.platform = "win32"
            result = _ssl_context()
        ctx_mock.load_default_certs.assert_called_once_with(ssl.Purpose.SERVER_AUTH)
        assert result is ctx_mock

    def test_load_default_certs_not_called_on_linux(self):
        ctx_mock = MagicMock(spec=ssl.SSLContext)
        with patch("ssl.create_default_context", return_value=ctx_mock), \
             patch("tsm.self_update.sys") as mock_sys:
            mock_sys.platform = "linux"
            _ssl_context()
        ctx_mock.load_default_certs.assert_not_called()


class TestGetUpdateInfo:
    """Tests for the cached get_update_info() function."""

    def setup_method(self):
        """Reset cache before each test."""
        invalidate_update_cache()

    def test_returns_dict_with_required_keys(self):
        with patch(
            "tsm.self_update._fetch_latest_release", return_value=None
        ):
            info = get_update_info()
        assert isinstance(info, dict)
        for key in ("update_available", "current_version",
                    "remote_version", "release_notes",
                    "release_url", "frozen"):
            assert key in info

    def test_no_release_means_no_update(self):
        with patch(
            "tsm.self_update._fetch_latest_release", return_value=None
        ):
            info = get_update_info()
        assert info["update_available"] is False
        assert info["remote_version"] is None

    def test_newer_release_detected(self):
        fake_release = {
            "tag_name": "v99.0.0",
            "body": "## What's new\n- Big change",
            "html_url": "https://github.com/example/releases/99",
            "assets": [],
        }
        with patch(
            "tsm.self_update._fetch_latest_release",
            return_value=fake_release,
        ):
            info = get_update_info()
        assert info["update_available"] is True
        assert info["remote_version"] == "99.0.0"
        assert info["release_notes"] == "## What's new\n- Big change"
        assert info["release_url"] is not None

    def test_same_version_no_update(self):
        from config import VERSION
        fake_release = {
            "tag_name": f"v{VERSION}",
            "body": None,
            "html_url": "https://example.com",
            "assets": [],
        }
        with patch(
            "tsm.self_update._fetch_latest_release",
            return_value=fake_release,
        ):
            info = get_update_info()
        assert info["update_available"] is False

    def test_cache_returns_same_result(self):
        """Second call within TTL returns cached result."""
        fake_release = {
            "tag_name": "v99.0.0",
            "body": "notes",
            "html_url": "https://example.com",
            "assets": [],
        }
        with patch(
            "tsm.self_update._fetch_latest_release",
            return_value=fake_release,
        ) as mock_fetch:
            info1 = get_update_info()
            info2 = get_update_info()
        # Should only have fetched once (second is cached)
        assert mock_fetch.call_count == 1
        assert info1 == info2

    def test_invalidate_cache_forces_refresh(self):
        fake_release = {
            "tag_name": "v99.0.0",
            "body": None,
            "html_url": None,
            "assets": [],
        }
        with patch(
            "tsm.self_update._fetch_latest_release",
            return_value=fake_release,
        ) as mock_fetch:
            get_update_info()
            invalidate_update_cache()
            get_update_info()
        assert mock_fetch.call_count == 2

    def test_fetch_exception_returns_safe_defaults(self):
        with patch(
            "tsm.self_update._fetch_latest_release",
            side_effect=Exception("network error"),
        ):
            info = get_update_info()
        assert info["update_available"] is False

    def test_frozen_flag_matches_is_frozen(self):
        with patch(
            "tsm.self_update._fetch_latest_release", return_value=None
        ):
            info = get_update_info()
        assert info["frozen"] is _is_frozen()
