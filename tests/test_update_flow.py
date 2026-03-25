"""
Tests for the full check_for_update() flow and its helper functions:
_download_asset, _swap_exe, _restart_service, _cleanup_old_exe.

All network calls and subprocess launches are mocked — no real GitHub
traffic, no real file swaps, no real service restarts.
"""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from tsm.self_update import (
    _cleanup_old_exe,
    _download_asset,
    _restart_service,
    _swap_exe,
    check_for_update,
    invalidate_update_cache,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _make_exe(path: Path, size: int = 2_000_000) -> Path:
    """Write a fake EXE (just random bytes large enough to pass the
    size sanity check)."""
    path.write_bytes(b"\x00" * size)
    return path


# ──────────────────────────────────────────────────────────────────────
# _download_asset
# ──────────────────────────────────────────────────────────────────────
class TestDownloadAsset:
    def test_success_writes_file(self, tmp_path):
        dest = tmp_path / "app.exe"
        fake_data = b"MZ" + b"\x00" * 100   # minimal PE-like header

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        # First read returns data, second returns empty to stop loop
        mock_resp.read.side_effect = [fake_data, b""]

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _download_asset("https://example.com/app.exe", dest)

        assert result is True
        assert dest.exists()
        assert dest.read_bytes() == fake_data

    def test_network_error_returns_false(self, tmp_path):
        dest = tmp_path / "app.exe"
        with patch("urllib.request.urlopen",
                   side_effect=OSError("no network")):
            result = _download_asset("https://example.com/app.exe", dest)
        assert result is False

    def test_dest_not_created_on_error(self, tmp_path):
        dest = tmp_path / "app.exe"
        with patch("urllib.request.urlopen",
                   side_effect=OSError("no network")):
            _download_asset("https://example.com/app.exe", dest)
        assert not dest.exists()


# ──────────────────────────────────────────────────────────────────────
# _swap_exe
# ──────────────────────────────────────────────────────────────────────
class TestSwapExe:
    def test_successful_swap(self, tmp_path):
        current = _make_exe(tmp_path / "app.exe")
        new_exe = _make_exe(tmp_path / "app.exe.tmp")

        result = _swap_exe(current, new_exe)

        assert result is True
        assert current.exists()            # new file is in place
        assert not new_exe.exists()        # tmp removed
        old = current.with_suffix(".exe.old")
        assert old.exists()                # original renamed to .old

    def test_old_leftover_removed_first(self, tmp_path):
        current = _make_exe(tmp_path / "app.exe")
        new_exe = _make_exe(tmp_path / "app.exe.tmp")
        old = current.with_suffix(".exe.old")
        # Simulate leftover from previous update
        old.write_bytes(b"stale")

        result = _swap_exe(current, new_exe)

        assert result is True
        # The .old file should be the old current, not the stale one
        assert old.read_bytes() == b"\x00" * 2_000_000

    def test_rollback_on_second_rename_fail(self, tmp_path):
        """If moving new_exe into place fails, the original is restored."""
        current = _make_exe(tmp_path / "app.exe")
        new_exe = _make_exe(tmp_path / "app.exe.tmp")
        original_content = current.read_bytes()

        call_count = {"n": 0}
        real_rename = os.rename

        def patched_rename(src, dst):
            call_count["n"] += 1
            if call_count["n"] == 2:       # second rename = placing new exe
                raise OSError("locked")
            real_rename(src, dst)

        with patch("os.rename", side_effect=patched_rename):
            result = _swap_exe(current, new_exe)

        assert result is False
        # Original should be rolled back
        assert current.exists()
        assert current.read_bytes() == original_content

    def test_first_rename_fails_returns_false(self, tmp_path):
        current = _make_exe(tmp_path / "app.exe")
        new_exe = _make_exe(tmp_path / "app.exe.tmp")

        with patch("os.rename", side_effect=OSError("locked")):
            result = _swap_exe(current, new_exe)

        assert result is False


# ──────────────────────────────────────────────────────────────────────
# _restart_service
# ──────────────────────────────────────────────────────────────────────
class TestRestartService:
    def test_popen_called(self):
        with patch("subprocess.Popen") as mock_popen:
            _restart_service()
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert "sc.exe stop" in cmd
        assert "sc.exe start" in cmd

    def test_popen_exception_is_caught(self):
        with patch("subprocess.Popen",
                   side_effect=OSError("access denied")):
            # Must not raise
            _restart_service()


# ──────────────────────────────────────────────────────────────────────
# _cleanup_old_exe
# ──────────────────────────────────────────────────────────────────────
class TestCleanupOldExe:
    def test_removes_old_file(self, tmp_path):
        fake_exe = tmp_path / "app.exe"
        fake_exe.write_bytes(b"new")
        old = fake_exe.with_suffix(".exe.old")
        old.write_bytes(b"old")

        with patch("tsm.self_update._current_exe", return_value=fake_exe):
            _cleanup_old_exe()

        assert not old.exists()

    def test_no_old_file_is_noop(self, tmp_path):
        fake_exe = tmp_path / "app.exe"
        fake_exe.write_bytes(b"new")
        with patch("tsm.self_update._current_exe", return_value=fake_exe):
            _cleanup_old_exe()   # should not raise

    def test_locked_old_file_silently_ignored(self, tmp_path):
        fake_exe = tmp_path / "app.exe"
        fake_exe.write_bytes(b"new")
        old = fake_exe.with_suffix(".exe.old")
        old.write_bytes(b"old")

        with patch("tsm.self_update._current_exe", return_value=fake_exe), \
             patch.object(Path, "unlink", side_effect=OSError("locked")):
            _cleanup_old_exe()   # must not raise


# ──────────────────────────────────────────────────────────────────────
# check_for_update — full integration (all I/O mocked)
# ──────────────────────────────────────────────────────────────────────
class TestCheckForUpdate:
    """
    Tests for the full check_for_update() orchestration.
    All network, filesystem, and subprocess calls are mocked.
    """

    def setup_method(self):
        invalidate_update_cache()

    # ── Not frozen → skip ──────────────────────────────────────────────
    def test_not_frozen_returns_false(self):
        with patch("tsm.self_update._is_frozen", return_value=False):
            assert check_for_update() is False

    # ── Already up to date ─────────────────────────────────────────────
    def test_already_up_to_date(self):
        from config import VERSION
        fake_release = {
            "tag_name": f"v{VERSION}",
            "assets": [],
            "body": None,
            "html_url": None,
        }
        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._fetch_latest_release",
                   return_value=fake_release), \
             patch("tsm.self_update._fetch_remote_version_via_raw",
                   return_value=VERSION), \
             patch("tsm.self_update._cleanup_old_exe"):
            result = check_for_update()
        assert result is False

    # ── No release found, no raw fallback ─────────────────────────────
    def test_no_release_no_raw_returns_false(self):
        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._fetch_latest_release",
                   return_value=None), \
             patch("tsm.self_update._fetch_remote_version_via_raw",
                   return_value=None), \
             patch("tsm.self_update._cleanup_old_exe"):
            assert check_for_update() is False

    # ── Update available but no EXE asset ─────────────────────────────
    def test_update_available_no_asset_returns_false(self):
        fake_release = {
            "tag_name": "v99.0.0",
            "assets": [],          # no downloadable EXE
            "body": None,
            "html_url": None,
        }
        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._fetch_latest_release",
                   return_value=fake_release), \
             patch("tsm.self_update._fetch_remote_version_via_raw",
                   return_value="99.0.0"), \
             patch("tsm.self_update._cleanup_old_exe"):
            assert check_for_update() is False

    # ── Download fails ─────────────────────────────────────────────────
    def test_download_failure_returns_false(self, tmp_path):
        fake_asset = {
            "name": "TireStorageManager.exe",
            "browser_download_url": "https://example.com/app.exe",
            "size": 5_000_000,
        }
        fake_release = {
            "tag_name": "v99.0.0",
            "assets": [fake_asset],
            "body": None,
            "html_url": None,
        }
        fake_exe = tmp_path / "TireStorageManager.exe"
        _make_exe(fake_exe)

        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._fetch_latest_release",
                   return_value=fake_release), \
             patch("tsm.self_update._fetch_remote_version_via_raw",
                   return_value="99.0.0"), \
             patch("tsm.self_update._cleanup_old_exe"), \
             patch("tsm.self_update._current_exe",
                   return_value=fake_exe), \
             patch("tsm.self_update._download_asset",
                   return_value=False):
            assert check_for_update() is False

    # ── Downloaded file too small ──────────────────────────────────────
    def test_download_too_small_returns_false(self, tmp_path):
        fake_asset = {
            "name": "TireStorageManager.exe",
            "browser_download_url": "https://example.com/app.exe",
            "size": 100,
        }
        fake_release = {
            "tag_name": "v99.0.0",
            "assets": [fake_asset],
            "body": None,
            "html_url": None,
        }
        fake_exe = tmp_path / "TireStorageManager.exe"
        _make_exe(fake_exe)

        def fake_download(url, dest):
            dest.write_bytes(b"\x00" * 500)   # <1 MB
            return True

        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._fetch_latest_release",
                   return_value=fake_release), \
             patch("tsm.self_update._fetch_remote_version_via_raw",
                   return_value="99.0.0"), \
             patch("tsm.self_update._cleanup_old_exe"), \
             patch("tsm.self_update._current_exe",
                   return_value=fake_exe), \
             patch("tsm.self_update._download_asset",
                   side_effect=fake_download):
            assert check_for_update() is False

    # ── Swap fails ─────────────────────────────────────────────────────
    def test_swap_failure_returns_false(self, tmp_path):
        fake_asset = {
            "name": "TireStorageManager.exe",
            "browser_download_url": "https://example.com/app.exe",
            "size": 5_000_000,
        }
        fake_release = {
            "tag_name": "v99.0.0",
            "assets": [fake_asset],
            "body": None,
            "html_url": None,
        }
        fake_exe = tmp_path / "TireStorageManager.exe"
        _make_exe(fake_exe)

        def fake_download(url, dest):
            _make_exe(dest)
            return True

        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._fetch_latest_release",
                   return_value=fake_release), \
             patch("tsm.self_update._fetch_remote_version_via_raw",
                   return_value="99.0.0"), \
             patch("tsm.self_update._cleanup_old_exe"), \
             patch("tsm.self_update._current_exe",
                   return_value=fake_exe), \
             patch("tsm.self_update._download_asset",
                   side_effect=fake_download), \
             patch("tsm.self_update._swap_exe", return_value=False):
            assert check_for_update() is False

    # ── Happy path ─────────────────────────────────────────────────────
    def test_happy_path_returns_true_and_restarts(self, tmp_path):
        fake_asset = {
            "name": "TireStorageManager.exe",
            "browser_download_url": "https://example.com/app.exe",
            "size": 5_000_000,
        }
        fake_release = {
            "tag_name": "v99.0.0",
            "assets": [fake_asset],
            "body": "### Added\n- Everything",
            "html_url": "https://github.com/example/releases/99",
        }
        fake_exe = tmp_path / "TireStorageManager.exe"
        _make_exe(fake_exe)

        def fake_download(url, dest):
            _make_exe(dest)
            return True

        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._fetch_latest_release",
                   return_value=fake_release), \
             patch("tsm.self_update._fetch_remote_version_via_raw",
                   return_value="99.0.0"), \
             patch("tsm.self_update._cleanup_old_exe"), \
             patch("tsm.self_update._current_exe",
                   return_value=fake_exe), \
             patch("tsm.self_update._download_asset",
                   side_effect=fake_download), \
             patch("tsm.self_update._swap_exe",
                   return_value=True) as mock_swap, \
             patch("tsm.self_update._restart_service") as mock_restart:
            result = check_for_update()

        assert result is True
        mock_swap.assert_called_once()
        mock_restart.assert_called_once()

    # ── Unexpected exception is caught ────────────────────────────────
    def test_exception_in_download_returns_false(self, tmp_path):
        fake_asset = {
            "name": "TireStorageManager.exe",
            "browser_download_url": "https://example.com/app.exe",
            "size": 5_000_000,
        }
        fake_release = {
            "tag_name": "v99.0.0",
            "assets": [fake_asset],
            "body": None,
            "html_url": None,
        }
        fake_exe = tmp_path / "TireStorageManager.exe"
        _make_exe(fake_exe)

        with patch("tsm.self_update._is_frozen", return_value=True), \
             patch("tsm.self_update._fetch_latest_release",
                   return_value=fake_release), \
             patch("tsm.self_update._fetch_remote_version_via_raw",
                   return_value="99.0.0"), \
             patch("tsm.self_update._cleanup_old_exe"), \
             patch("tsm.self_update._current_exe",
                   return_value=fake_exe), \
             patch("tsm.self_update._download_asset",
                   side_effect=RuntimeError("disk full")):
            assert check_for_update() is False
