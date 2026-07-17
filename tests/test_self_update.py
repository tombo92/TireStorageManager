"""Tests for tsm/self_update.py — version parsing and helpers."""
import ssl
import struct
from unittest.mock import MagicMock, patch

import pytest

from tsm.self_update import (
    MAX_MANUAL_UPLOAD_SIZE,
    MIN_EXE_SIZE,
    SIGNER_THUMBPRINT,
    _find_highest_release,
    _is_frozen,
    _is_valid_pe_exe,
    _nocache_url,
    _ssl_context,
    _ver_tuple,
    _verify_authenticode,
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

    def test_regression_1_9_0_vs_1_10_1(self):
        """Real customer bug: 1.9.0 -> 1.10.1 was not detected as an
        available update. A naive string comparison ("1.9.0" > "1.10.1")
        would wrongly say the older version is newer — tuple comparison
        must get this right."""
        assert _ver_tuple("1.10.1") > _ver_tuple("1.9.0")
        assert not _ver_tuple("1.9.0") > _ver_tuple("1.10.1")

    @pytest.mark.parametrize("older,newer", [
        ("1.9.0", "1.10.0"),
        ("1.9.9", "1.10.0"),
        ("1.9.0", "1.10.1"),
        ("0.9.0", "0.10.0"),
        ("2.9.9", "2.10.0"),
        ("1.10.0", "1.10.1"),
        ("1.10.9", "1.11.0"),
    ])
    def test_minor_version_rollover_regression(self, older, newer):
        """Guards against lexicographic-style comparison bugs whenever
        a minor/patch version rolls over a single digit (9 -> 10)."""
        assert _ver_tuple(newer) > _ver_tuple(older)


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


# ──────────────────────────────────────────────────────────────────────
# _fetch_latest_release — direct HTTP-layer tests (urlopen mocked)
# ──────────────────────────────────────────────────────────────────────
def _mock_response(body: bytes):
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = body
    return resp


class TestFetchLatestRelease:
    def test_success(self):
        from tsm.self_update import _fetch_latest_release
        body = b'{"tag_name": "v1.10.1", "assets": []}'
        with patch("urllib.request.urlopen",
                   return_value=_mock_response(body)):
            result = _fetch_latest_release()
        assert result["tag_name"] == "v1.10.1"

    def test_404_returns_none(self):
        import urllib.error
        from tsm.self_update import _fetch_latest_release
        err = urllib.error.HTTPError(
            "url", 404, "Not Found", None, None)
        with patch("urllib.request.urlopen", side_effect=err):
            assert _fetch_latest_release() is None

    def test_403_rate_limited_returns_none(self):
        """Unauthenticated GitHub API calls are rate-limited (403) —
        must not raise, just report no release found."""
        import urllib.error
        from tsm.self_update import _fetch_latest_release
        err = urllib.error.HTTPError(
            "url", 403, "rate limit exceeded", None, None)
        with patch("urllib.request.urlopen", side_effect=err):
            assert _fetch_latest_release() is None

    def test_timeout_returns_none(self):
        import socket
        from tsm.self_update import _fetch_latest_release
        with patch("urllib.request.urlopen",
                   side_effect=socket.timeout("timed out")):
            assert _fetch_latest_release() is None

    def test_ssl_error_returns_none(self):
        from tsm.self_update import _fetch_latest_release
        with patch("urllib.request.urlopen",
                   side_effect=ssl.SSLCertVerificationError("bad cert")):
            assert _fetch_latest_release() is None

    def test_malformed_json_returns_none(self):
        from tsm.self_update import _fetch_latest_release
        with patch("urllib.request.urlopen",
                   return_value=_mock_response(b"<html>not json</html>")):
            assert _fetch_latest_release() is None


# ──────────────────────────────────────────────────────────────────────
# _find_exe_asset
# ──────────────────────────────────────────────────────────────────────
class TestFindExeAsset:
    def test_finds_matching_asset(self):
        from tsm.self_update import _find_exe_asset
        release = {"assets": [
            {"name": "TireStorageManager.exe", "browser_download_url": "x"},
        ]}
        asset = _find_exe_asset(release)
        assert asset is not None
        assert asset["name"] == "TireStorageManager.exe"

    def test_case_insensitive_match(self):
        from tsm.self_update import _find_exe_asset
        release = {"assets": [
            {"name": "TIRESTORAGEMANAGER.EXE", "browser_download_url": "x"},
        ]}
        assert _find_exe_asset(release) is not None

    def test_no_matching_asset_returns_none(self):
        from tsm.self_update import _find_exe_asset
        release = {"assets": [
            {"name": "readme.txt"},
            {"name": "TSM-Installer.exe"},
        ]}
        assert _find_exe_asset(release) is None

    def test_empty_assets_returns_none(self):
        from tsm.self_update import _find_exe_asset
        assert _find_exe_asset({"assets": []}) is None

    def test_missing_assets_key_returns_none(self):
        from tsm.self_update import _find_exe_asset
        assert _find_exe_asset({}) is None

    def test_picks_correct_asset_among_several(self):
        from tsm.self_update import _find_exe_asset
        release = {"assets": [
            {"name": "TSM-Installer.exe", "browser_download_url": "a"},
            {"name": "TireStorageManager.exe", "browser_download_url": "b"},
            {"name": "CHANGELOG.md", "browser_download_url": "c"},
        ]}
        asset = _find_exe_asset(release)
        assert asset["browser_download_url"] == "b"


# ──────────────────────────────────────────────────────────────────────
# _fetch_remote_version_via_raw
# ──────────────────────────────────────────────────────────────────────
class TestFetchRemoteVersionViaRaw:
    def test_extracts_version(self):
        from tsm.self_update import _fetch_remote_version_via_raw
        body = b'APP_NAME = "TSM"\nVERSION = "1.10.1"\nOTHER = 1\n'
        with patch("urllib.request.urlopen",
                   return_value=_mock_response(body)):
            assert _fetch_remote_version_via_raw() == "1.10.1"

    def test_no_version_line_returns_none(self):
        from tsm.self_update import _fetch_remote_version_via_raw
        body = b'APP_NAME = "TSM"\n'
        with patch("urllib.request.urlopen",
                   return_value=_mock_response(body)):
            assert _fetch_remote_version_via_raw() is None

    def test_network_error_returns_none(self):
        from tsm.self_update import _fetch_remote_version_via_raw
        with patch("urllib.request.urlopen",
                   side_effect=OSError("no network")):
            assert _fetch_remote_version_via_raw() is None


class TestGetUpdateInfo:
    """Tests for the cached get_update_info() function."""

    def setup_method(self):
        """Reset cache before each test."""
        invalidate_update_cache()

    def test_returns_dict_with_required_keys(self):
        with patch(
            "tsm.self_update._fetch_latest_release", return_value=None
        ), patch(
            "tsm.self_update._fetch_all_releases", return_value=[]
        ):
            info = get_update_info()
        assert isinstance(info, dict)
        for key in ("update_available", "current_version",
                    "remote_version", "release_notes",
                    "release_url", "frozen", "check_error"):
            assert key in info

    def test_no_release_means_no_update(self):
        with patch(
            "tsm.self_update._fetch_latest_release", return_value=None
        ), patch(
            "tsm.self_update._fetch_all_releases", return_value=[]
        ):
            info = get_update_info()
        assert info["update_available"] is False
        assert info["remote_version"] is None

    def test_no_release_sets_check_error(self):
        """When both /latest and the full list fail, surface an error
        instead of silently reporting 'up to date'."""
        with patch(
            "tsm.self_update._fetch_latest_release", return_value=None
        ), patch(
            "tsm.self_update._fetch_all_releases", return_value=[]
        ):
            info = get_update_info()
        assert info["check_error"] is not None
        assert info["update_available"] is False

    def test_error_result_is_not_cached(self):
        """A failed check must not be cached for the full TTL — the next
        call should retry immediately."""
        with patch(
            "tsm.self_update._fetch_latest_release", return_value=None
        ) as mock_fetch, patch(
            "tsm.self_update._fetch_all_releases", return_value=[]
        ):
            get_update_info()
            get_update_info()
        assert mock_fetch.call_count == 2

    def test_fallback_to_releases_list_when_latest_empty(self):
        """If /releases/latest returns nothing (e.g. only pre-releases
        exist), fall back to scanning the full releases list."""
        fake_releases = [
            {"tag_name": "v1.10.1", "draft": False,
             "body": "notes", "html_url": "https://x", "assets": []},
            {"tag_name": "v1.9.0", "draft": False,
             "body": None, "html_url": None, "assets": []},
        ]
        with patch(
            "tsm.self_update._fetch_latest_release", return_value=None
        ), patch(
            "tsm.self_update._fetch_all_releases",
            return_value=fake_releases,
        ):
            info = get_update_info()
        assert info["remote_version"] == "1.10.1"
        assert info["check_error"] is None

    def test_drafts_excluded_from_fallback(self):
        fake_releases = [
            {"tag_name": "v99.0.0", "draft": True,
             "body": None, "html_url": None, "assets": []},
            {"tag_name": "v1.10.1", "draft": False,
             "body": None, "html_url": None, "assets": []},
        ]
        with patch(
            "tsm.self_update._fetch_latest_release", return_value=None
        ), patch(
            "tsm.self_update._fetch_all_releases",
            return_value=fake_releases,
        ):
            info = get_update_info()
        assert info["remote_version"] == "1.10.1"

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
        ), patch(
            "tsm.self_update._fetch_all_releases", return_value=[]
        ):
            info = get_update_info()
        assert info["frozen"] is _is_frozen()


# ──────────────────────────────────────────────────────────────────────
# _find_highest_release
# ──────────────────────────────────────────────────────────────────────
class TestFindHighestRelease:
    def test_empty_list_returns_none(self):
        assert _find_highest_release([]) is None

    def test_picks_highest_semver_not_first_in_list(self):
        """GitHub's list is ordered by creation date, not semver — a
        hotfix tagged v1.9.1 could be created after v1.10.0. We must
        pick the numerically highest tag, not the first one."""
        releases = [
            {"tag_name": "v1.9.1", "draft": False},
            {"tag_name": "v1.10.1", "draft": False},
            {"tag_name": "v1.10.0", "draft": False},
        ]
        result = _find_highest_release(releases)
        assert result["tag_name"] == "v1.10.1"

    def test_skips_drafts(self):
        releases = [
            {"tag_name": "v5.0.0", "draft": True},
            {"tag_name": "v1.0.0", "draft": False},
        ]
        result = _find_highest_release(releases)
        assert result["tag_name"] == "v1.0.0"

    def test_all_drafts_returns_none(self):
        releases = [
            {"tag_name": "v5.0.0", "draft": True},
            {"tag_name": "v6.0.0", "draft": True},
        ]
        assert _find_highest_release(releases) is None

    def test_malformed_tag_treated_as_zero(self):
        releases = [
            {"tag_name": "not-a-version", "draft": False},
            {"tag_name": "v1.0.0", "draft": False},
        ]
        result = _find_highest_release(releases)
        assert result["tag_name"] == "v1.0.0"

    def test_missing_draft_key_defaults_to_included(self):
        """Real GitHub payloads always include 'draft', but the code
        should not crash if it's absent."""
        releases = [{"tag_name": "v1.0.0"}]
        result = _find_highest_release(releases)
        assert result["tag_name"] == "v1.0.0"


# ──────────────────────────────────────────────────────────────────────
# _fetch_all_releases
# ──────────────────────────────────────────────────────────────────────
class TestFetchAllReleases:
    def test_success_returns_list(self):
        from tsm.self_update import _fetch_all_releases
        fake_body = b'[{"tag_name": "v1.0.0"}]'
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = fake_body
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_all_releases()
        assert result == [{"tag_name": "v1.0.0"}]

    def test_network_error_returns_empty_list(self):
        from tsm.self_update import _fetch_all_releases
        with patch("urllib.request.urlopen",
                   side_effect=OSError("no network")):
            result = _fetch_all_releases()
        assert result == []

    def test_malformed_json_returns_empty_list(self):
        from tsm.self_update import _fetch_all_releases
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"not json"
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_all_releases()
        assert result == []


# ──────────────────────────────────────────────────────────────────────
# _is_valid_pe_exe — structural validation edge cases
# ──────────────────────────────────────────────────────────────────────
def _write_fake_pe(path, e_lfanew=64, pe_sig=b"PE\x00\x00", pad_after=100):
    """Write a minimal file with a valid-looking MZ header + PE
    signature at the given offset."""
    header = bytearray(64)
    header[0:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, e_lfanew)
    data = bytes(header)
    if e_lfanew > len(data):
        data += b"\x00" * (e_lfanew - len(data))
    data += pe_sig
    data += b"\x00" * pad_after
    path.write_bytes(data)
    return path


class TestIsValidPeExe:
    def test_valid_pe_header_accepted(self, tmp_path):
        f = _write_fake_pe(tmp_path / "app.exe")
        assert _is_valid_pe_exe(f) is True

    def test_missing_file_rejected(self, tmp_path):
        assert _is_valid_pe_exe(tmp_path / "nope.exe") is False

    def test_empty_file_rejected(self, tmp_path):
        f = tmp_path / "empty.exe"
        f.write_bytes(b"")
        assert _is_valid_pe_exe(f) is False

    def test_truncated_header_rejected(self, tmp_path):
        f = tmp_path / "short.exe"
        f.write_bytes(b"MZ\x00\x00")   # way less than 64 bytes
        assert _is_valid_pe_exe(f) is False

    def test_wrong_magic_bytes_rejected(self, tmp_path):
        f = tmp_path / "notexe.exe"
        f.write_bytes(b"PK" + b"\x00" * 100)   # ZIP magic, not MZ
        assert _is_valid_pe_exe(f) is False

    def test_plain_text_file_rejected(self, tmp_path):
        f = tmp_path / "readme.exe"
        f.write_text("This is not an executable, just renamed.")
        assert _is_valid_pe_exe(f) is False

    def test_missing_pe_signature_rejected(self, tmp_path):
        f = _write_fake_pe(tmp_path / "bad.exe", pe_sig=b"XX\x00\x00")
        assert _is_valid_pe_exe(f) is False

    def test_negative_e_lfanew_rejected(self, tmp_path):
        header = bytearray(64)
        header[0:2] = b"MZ"
        struct.pack_into("<i", header, 0x3C, -1)
        f = tmp_path / "neg.exe"
        f.write_bytes(bytes(header))
        assert _is_valid_pe_exe(f) is False

    def test_absurd_e_lfanew_rejected(self, tmp_path):
        """A huge offset (e.g. from a corrupted/malicious file) must be
        rejected rather than seeking far into (or past) the file."""
        f = _write_fake_pe(tmp_path / "huge.exe", e_lfanew=100_000_000)
        assert _is_valid_pe_exe(f) is False

    def test_zero_e_lfanew_rejected(self, tmp_path):
        header = bytearray(64)
        header[0:2] = b"MZ"
        struct.pack_into("<I", header, 0x3C, 0)
        f = tmp_path / "zero.exe"
        f.write_bytes(bytes(header))
        assert _is_valid_pe_exe(f) is False

    def test_pe_signature_beyond_eof_rejected(self, tmp_path):
        """e_lfanew points past the end of the (short) file."""
        header = bytearray(64)
        header[0:2] = b"MZ"
        struct.pack_into("<I", header, 0x3C, 1000)
        f = tmp_path / "shortpe.exe"
        f.write_bytes(bytes(header))   # file ends long before offset 1000
        assert _is_valid_pe_exe(f) is False

    def test_directory_instead_of_file_rejected(self, tmp_path):
        d = tmp_path / "adir.exe"
        d.mkdir()
        assert _is_valid_pe_exe(d) is False


# ──────────────────────────────────────────────────────────────────────
# apply_manual_update — manual/offline update upload flow
# ──────────────────────────────────────────────────────────────────────
class TestApplyManualUpdate:
    def _make_exe(self, path, size=2_000_000):
        _write_fake_pe(path, pad_after=size)
        return path

    def test_not_frozen_rejected(self, tmp_path):
        from tsm.self_update import apply_manual_update
        f = self._make_exe(tmp_path / "upload.exe")
        with patch("tsm.self_update._is_frozen", return_value=False):
            ok, reason = apply_manual_update(f)
        assert ok is False
        assert reason == "not_frozen"

    def test_missing_file_rejected(self, tmp_path):
        from tsm.self_update import apply_manual_update
        with patch("tsm.self_update._is_frozen", return_value=True):
            ok, reason = apply_manual_update(tmp_path / "ghost.exe")
        assert ok is False
        assert reason == "missing_file"

    def test_too_small_rejected(self, tmp_path):
        from tsm.self_update import apply_manual_update
        f = tmp_path / "tiny.exe"
        f.write_bytes(b"MZ" + b"\x00" * 50)   # < MIN_EXE_SIZE
        with patch("tsm.self_update._is_frozen", return_value=True):
            ok, reason = apply_manual_update(f)
        assert ok is False
        assert reason == "too_small"

    def test_too_large_rejected(self, tmp_path):
        from tsm.self_update import apply_manual_update
        f = tmp_path / "huge.exe"
        # Sparse file: seek past the size ceiling and write one byte,
        # so the file *reports* as oversized without allocating real
        # disk space for the whole 300 MB.
        with open(f, "wb") as fh:
            fh.seek(MAX_MANUAL_UPLOAD_SIZE)
            fh.write(b"\x00")
        with patch("tsm.self_update._is_frozen", return_value=True):
            ok, reason = apply_manual_update(f)
        assert ok is False
        assert reason == "too_large"

    def test_invalid_pe_rejected(self, tmp_path):
        from tsm.self_update import apply_manual_update
        f = tmp_path / "fake.exe"
        # Big enough to pass size check, but not a real PE file
        f.write_bytes(b"NOTMZ" + b"\x00" * MIN_EXE_SIZE)
        with patch("tsm.self_update._is_frozen", return_value=True):
            ok, reason = apply_manual_update(f)
        assert ok is False
        assert reason == "invalid_pe"

    def test_unsigned_exe_rejected_when_thumbprint_set(self, tmp_path):
        """When SIGNER_THUMBPRINT is configured, an unsigned (or
        wrongly-signed) EXE must be rejected before reaching the
        swap step."""
        from tsm.self_update import apply_manual_update
        f = self._make_exe(tmp_path / "upload.exe")
        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._verify_authenticode",
                   return_value=(False, "unsigned")):
            ok, reason = apply_manual_update(f)
        assert ok is False
        assert reason == "unsigned"

    def test_signed_exe_passes_verification(self, tmp_path):
        """When _verify_authenticode returns (True, ""), the flow
        continues to swap."""
        from tsm.self_update import apply_manual_update
        f = self._make_exe(tmp_path / "upload.exe")
        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._verify_authenticode",
                   return_value=(True, "")), \
             patch("tsm.self_update._swap_exe",
                   return_value=True) as mock_swap, \
             patch("tsm.self_update._current_exe",
                   return_value=tmp_path / "current.exe"), \
             patch("tsm.self_update._write_update_marker"), \
             patch("tsm.self_update._restart_service"):
            ok, reason = apply_manual_update(f)
        assert ok is True
        mock_swap.assert_called_once()

    def test_swap_failure_propagates(self, tmp_path):
        from tsm.self_update import apply_manual_update
        f = self._make_exe(tmp_path / "upload.exe")
        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._verify_authenticode",
                   return_value=(True, "")), \
             patch("tsm.self_update._swap_exe", return_value=False):
            ok, reason = apply_manual_update(f)
        assert ok is False
        assert reason == "swap_failed"

    def test_happy_path_swaps_and_restarts(self, tmp_path):
        from tsm.self_update import apply_manual_update
        current = tmp_path / "TireStorageManager.exe"
        current.write_bytes(b"old exe content")
        upload = self._make_exe(tmp_path / "upload.exe")

        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._verify_authenticode",
                   return_value=(True, "")), \
             patch("tsm.self_update._current_exe", return_value=current), \
             patch("tsm.self_update._swap_exe",
                   return_value=True) as mock_swap, \
             patch("tsm.self_update._write_update_marker") as mock_marker, \
             patch("tsm.self_update._restart_service") as mock_restart:
            ok, reason = apply_manual_update(upload, version_label="1.10.1")

        assert ok is True
        assert reason == "ok"
        mock_swap.assert_called_once_with(current, upload)
        mock_marker.assert_called_once()
        # Label passed through to the marker
        assert mock_marker.call_args[0][1] == "1.10.1"
        mock_restart.assert_called_once()

    def test_blank_label_defaults_to_manual(self, tmp_path):
        from tsm.self_update import apply_manual_update
        current = tmp_path / "TireStorageManager.exe"
        current.write_bytes(b"old")
        upload = self._make_exe(tmp_path / "upload.exe")

        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._verify_authenticode",
                   return_value=(True, "")), \
             patch("tsm.self_update._current_exe", return_value=current), \
             patch("tsm.self_update._swap_exe", return_value=True), \
             patch("tsm.self_update._write_update_marker") as mock_marker, \
             patch("tsm.self_update._restart_service"):
            apply_manual_update(upload, version_label="   ")

        assert mock_marker.call_args[0][1] == "manual"

    def test_upload_not_consumed_on_failure(self, tmp_path):
        """apply_manual_update() must not delete the uploaded file
        itself when validation fails — the caller (route) owns
        cleanup in that case."""
        from tsm.self_update import apply_manual_update
        f = tmp_path / "tiny.exe"
        f.write_bytes(b"MZ" + b"\x00" * 50)
        with patch("tsm.self_update._is_frozen", return_value=True):
            apply_manual_update(f)
        assert f.exists()


# ──────────────────────────────────────────────────────────────────────
# _verify_authenticode — Authenticode signature verification
# ──────────────────────────────────────────────────────────────────────
class TestVerifyAuthenticode:
    """Tests for _verify_authenticode().

    All tests mock subprocess.run to avoid needing a real signed EXE
    and PowerShell — the function's contract is tested, not the OS
    toolchain.
    """

    FAKE_THUMBPRINT = "AABBCCDD1234567890AABBCCDD1234567890AABB"

    def test_skipped_when_no_thumbprint(self, tmp_path):
        """When SIGNER_THUMBPRINT is empty, all files pass."""
        f = tmp_path / "any.exe"
        f.write_bytes(b"anything")
        with patch("tsm.self_update.SIGNER_THUMBPRINT", ""):
            ok, reason = _verify_authenticode(f)
        assert ok is True
        assert reason == ""

    def test_skipped_on_non_windows(self, tmp_path):
        f = tmp_path / "any.exe"
        f.write_bytes(b"anything")
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys:
            mock_sys.platform = "linux"
            ok, reason = _verify_authenticode(f)
        assert ok is True

    def test_valid_signature_matching_thumbprint(self, tmp_path):
        f = tmp_path / "signed.exe"
        f.write_bytes(b"PE data")
        mock_result = MagicMock()
        mock_result.stdout = f"Valid|{self.FAKE_THUMBPRINT}\n"
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys, \
             patch("subprocess.run", return_value=mock_result):
            mock_sys.platform = "win32"
            ok, reason = _verify_authenticode(f)
        assert ok is True
        assert reason == ""

    def test_valid_signature_wrong_thumbprint(self, tmp_path):
        f = tmp_path / "signed.exe"
        f.write_bytes(b"PE data")
        mock_result = MagicMock()
        mock_result.stdout = "Valid|0000000000000000000000000000000000000000\n"
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys, \
             patch("subprocess.run", return_value=mock_result):
            mock_sys.platform = "win32"
            ok, reason = _verify_authenticode(f)
        assert ok is False
        assert reason == "unsigned"

    def test_not_signed_status(self, tmp_path):
        """File exists but has no signature at all."""
        f = tmp_path / "unsigned.exe"
        f.write_bytes(b"PE data")
        mock_result = MagicMock()
        mock_result.stdout = "NotSigned|\n"
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys, \
             patch("subprocess.run", return_value=mock_result):
            mock_sys.platform = "win32"
            ok, reason = _verify_authenticode(f)
        assert ok is False
        assert reason == "unsigned"

    def test_hash_mismatch_status(self, tmp_path):
        """Signature present but file was tampered with."""
        f = tmp_path / "tampered.exe"
        f.write_bytes(b"PE data")
        mock_result = MagicMock()
        mock_result.stdout = f"HashMismatch|{self.FAKE_THUMBPRINT}\n"
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys, \
             patch("subprocess.run", return_value=mock_result):
            mock_sys.platform = "win32"
            ok, reason = _verify_authenticode(f)
        assert ok is False
        assert reason == "unsigned"

    def test_unexpected_output_format(self, tmp_path):
        """PowerShell returns something we can't parse."""
        f = tmp_path / "weird.exe"
        f.write_bytes(b"PE data")
        mock_result = MagicMock()
        mock_result.stdout = "something unexpected\n"
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys, \
             patch("subprocess.run", return_value=mock_result):
            mock_sys.platform = "win32"
            ok, reason = _verify_authenticode(f)
        assert ok is False
        assert reason == "unsigned"

    def test_powershell_timeout(self, tmp_path):
        import subprocess as sp
        f = tmp_path / "slow.exe"
        f.write_bytes(b"PE data")
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys, \
             patch("subprocess.run",
                   side_effect=sp.TimeoutExpired("powershell", 30)):
            mock_sys.platform = "win32"
            ok, reason = _verify_authenticode(f)
        assert ok is False
        assert reason == "unsigned"

    def test_powershell_not_found(self, tmp_path):
        f = tmp_path / "no_ps.exe"
        f.write_bytes(b"PE data")
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys, \
             patch("subprocess.run",
                   side_effect=FileNotFoundError("powershell")):
            mock_sys.platform = "win32"
            ok, reason = _verify_authenticode(f)
        assert ok is False
        assert reason == "unsigned"

    def test_thumbprint_comparison_case_insensitive(self, tmp_path):
        """CI output may have lowercase hex; env var may be uppercase."""
        f = tmp_path / "signed.exe"
        f.write_bytes(b"PE data")
        lower_thumb = self.FAKE_THUMBPRINT.lower()
        mock_result = MagicMock()
        mock_result.stdout = f"Valid|{lower_thumb}\n"
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys, \
             patch("subprocess.run", return_value=mock_result):
            mock_sys.platform = "win32"
            ok, reason = _verify_authenticode(f)
        assert ok is True

    def test_empty_thumbprint_from_ps_rejected(self, tmp_path):
        """Signature status is 'Valid' but no thumbprint — should
        not happen in practice, but guard against it."""
        f = tmp_path / "odd.exe"
        f.write_bytes(b"PE data")
        mock_result = MagicMock()
        mock_result.stdout = "Valid|\n"
        with patch("tsm.self_update.SIGNER_THUMBPRINT", self.FAKE_THUMBPRINT), \
             patch("tsm.self_update.sys") as mock_sys, \
             patch("subprocess.run", return_value=mock_result):
            mock_sys.platform = "win32"
            ok, reason = _verify_authenticode(f)
        assert ok is False
        assert reason == "unsigned"
