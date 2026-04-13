#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Smoke tests for installer/TSMInstaller.py utility functions.

Tests only the headless-testable parts (no Tkinter, no display required)
so they run on Linux CI runners.  The GUI classes (InstallerApp,
ProgressWindow, UninstallProgressWindow) are covered indirectly through
installer_logic, which has its own unit tests in test_installer_logic.py.

Triggered in CI when any file under installer/ changes.
"""
from __future__ import annotations

import ctypes as _ctypes
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Stub out Tkinter and Windows-only modules before importing ────────────
# TSMInstaller imports tkinter at module level.  Stub it so the module
# loads on Linux CI runners without a display.
_tk_stub = MagicMock()
sys.modules.setdefault("tkinter", _tk_stub)
sys.modules.setdefault("tkinter.ttk", _tk_stub)
sys.modules.setdefault("tkinter.filedialog", _tk_stub)
sys.modules.setdefault("tkinter.messagebox", _tk_stub)

# winreg only exists on Windows; stub it on Linux.
if "winreg" not in sys.modules:
    sys.modules["winreg"] = MagicMock()

# ctypes is cross-platform but ctypes.windll is Windows-only.
if not hasattr(_ctypes, "windll"):
    _ctypes.windll = MagicMock()

import installer.TSMInstaller as tsm_installer  # noqa: E402


# ══════════════════════════════════════════════════════════════════════
# resource_path
# ══════════════════════════════════════════════════════════════════════
class TestResourcePath:
    def test_returns_path_object(self):
        result = tsm_installer.resource_path(Path("assets/app.ico"))
        assert isinstance(result, Path)

    def test_relative_to_package_root_when_not_frozen(self):
        """When not bundled by PyInstaller, path resolves relative to
        the installer/ package directory."""
        # _MEIPASS is not set in test runs.
        result = tsm_installer.resource_path(Path("payload/nssm.exe"))
        assert result.is_absolute()
        # Must be inside the installer package tree.
        installer_dir = Path(tsm_installer.__file__).resolve().parent
        assert installer_dir in result.parents

    def test_uses_meipass_when_frozen(self, tmp_path: Path):
        """When sys._MEIPASS is set (PyInstaller EXE), the path resolves
        relative to that directory."""
        with patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
            result = tsm_installer.resource_path(Path("payload/nssm.exe"))
        assert result == (tmp_path / "payload" / "nssm.exe").resolve()


# ══════════════════════════════════════════════════════════════════════
# get_primary_ipv4
# ══════════════════════════════════════════════════════════════════════
class TestGetPrimaryIpv4:
    def test_returns_string_or_none(self):
        result = tsm_installer.get_primary_ipv4()
        assert result is None or isinstance(result, str)

    def test_returns_valid_ipv4_format_when_successful(self):
        result = tsm_installer.get_primary_ipv4()
        if result is not None:
            parts = result.split(".")
            assert len(parts) == 4
            assert all(p.isdigit() for p in parts)

    def test_falls_back_to_hostname_when_socket_fails(self):
        """If the UDP trick fails, gethostbyname is used as fallback."""
        hostname_ip = "192.168.0.1"
        with patch("installer.TSMInstaller.socket.socket") as mock_sock_cls:
            mock_sock_cls.side_effect = OSError("no network")
            with patch("installer.TSMInstaller.socket.gethostbyname",
                       return_value=hostname_ip):
                result = tsm_installer.get_primary_ipv4()
        assert result == hostname_ip

    def test_returns_none_when_all_fallbacks_fail(self):
        with patch("installer.TSMInstaller.socket.socket") as mock_sock_cls:
            mock_sock_cls.side_effect = OSError("no network")
            with patch("installer.TSMInstaller.socket.gethostbyname",
                       side_effect=socket.gaierror("no name")):
                result = tsm_installer.get_primary_ipv4()
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# is_prerelease_build
# ══════════════════════════════════════════════════════════════════════
class TestIsPrereleaseBuild:
    def test_false_when_marker_absent(self, tmp_path: Path):
        # No PRERELEASE file in tmp_path — simulate a production payload.
        with patch("installer.TSMInstaller.resource_path",
                   return_value=tmp_path / "payload" / "PRERELEASE"):
            result = tsm_installer.is_prerelease_build()
        assert result is False

    def test_true_when_marker_present(self, tmp_path: Path):
        marker = tmp_path / "payload" / "PRERELEASE"
        marker.parent.mkdir(parents=True)
        marker.touch()
        with patch("installer.TSMInstaller.resource_path",
                   return_value=marker):
            result = tsm_installer.is_prerelease_build()
        assert result is True


# ══════════════════════════════════════════════════════════════════════
# is_admin
# ══════════════════════════════════════════════════════════════════════
class TestIsAdmin:
    def test_returns_bool(self):
        result = tsm_installer.is_admin()
        assert isinstance(result, bool)

    def test_false_when_windll_raises(self):
        with patch.object(
            _ctypes.windll.shell32, "IsUserAnAdmin",
            side_effect=OSError("not windows"),
        ):
            result = tsm_installer.is_admin()
        assert result is False

    def test_reflects_windll_return_value(self):
        with patch.object(
            _ctypes.windll.shell32, "IsUserAnAdmin", return_value=1
        ):
            assert tsm_installer.is_admin() is True

        with patch.object(
            _ctypes.windll.shell32, "IsUserAnAdmin", return_value=0
        ):
            assert tsm_installer.is_admin() is False


# ══════════════════════════════════════════════════════════════════════
# open_url  (no display — just verify it doesn't raise)
# ══════════════════════════════════════════════════════════════════════
class TestOpenUrl:
    def test_does_not_raise_on_success(self):
        with patch.object(
            _ctypes.windll.shell32, "ShellExecuteW", return_value=42
        ):
            tsm_installer.open_url("http://localhost:5000/")

    def test_silently_swallows_exception(self):
        with patch.object(
            _ctypes.windll.shell32, "ShellExecuteW",
            side_effect=OSError("no display"),
        ):
            # Must not raise.
            tsm_installer.open_url("http://localhost:5000/")


# ══════════════════════════════════════════════════════════════════════
# Constants – sanity-check public API surface
# ══════════════════════════════════════════════════════════════════════
class TestInstallerConstants:
    """Guard against accidental renames that break installer_logic coupling."""

    def test_app_name(self):
        assert tsm_installer.APP_NAME == "TireStorageManager"

    def test_service_name(self):
        assert tsm_installer.SERVICE_NAME == "TireStorageManager"

    def test_default_port(self):
        assert isinstance(tsm_installer.DEFAULT_PORT, int)
        assert 1 <= tsm_installer.DEFAULT_PORT <= 65535

    def test_payload_paths_are_path_objects(self):
        assert isinstance(tsm_installer.PAYLOAD_APP, Path)
        assert isinstance(tsm_installer.PAYLOAD_NSSM, Path)
        assert isinstance(tsm_installer.PAYLOAD_SEED_DB, Path)
        assert isinstance(tsm_installer.PAYLOAD_PRERELEASE_MARKER, Path)

    def test_payload_app_name(self):
        assert tsm_installer.PAYLOAD_APP.name == "TireStorageManager.exe"

    def test_payload_nssm_name(self):
        assert tsm_installer.PAYLOAD_NSSM.name == "nssm.exe"

    def test_payload_seed_db_name(self):
        assert tsm_installer.PAYLOAD_SEED_DB.name == "wheel_storage.db"


# ══════════════════════════════════════════════════════════════════════
# _UPDATE_NOTES_STUB_THRESHOLD — sparse release-notes detection
# ══════════════════════════════════════════════════════════════════════
class TestUpdateNotesStubThreshold:
    def test_is_positive_int(self):
        assert isinstance(tsm_installer._UPDATE_NOTES_STUB_THRESHOLD, int)
        assert tsm_installer._UPDATE_NOTES_STUB_THRESHOLD > 0

    def test_short_release_note_is_below_threshold(self):
        """The v1.6.0 stub ('Siehe Commit-Historie …') must be detected."""
        stub = (
            "## TireStorageManager v1.6.0\n\n"
            "Siehe [Commit-Historie](https://github.com/tombo92/"
            "TireStorageManager/commits/master).\n"
        )
        assert len(stub) < tsm_installer._UPDATE_NOTES_STUB_THRESHOLD

    def test_detailed_release_note_is_above_threshold(self):
        detailed = (
            "## What's new\n\n"
            "- Fixed SSL CERTIFICATE_VERIFY_FAILED on corporate networks\n"
            "- Added --ui-dev flag to installer\n"
            "- Improved update banner layout\n"
            "- Added re-install / already-uninstalled guards\n"
            "- Python 3.12 migration, ruff linter, pyproject consolidation\n"
        )
        assert len(detailed) >= tsm_installer._UPDATE_NOTES_STUB_THRESHOLD
