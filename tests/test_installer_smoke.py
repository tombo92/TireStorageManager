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


# ══════════════════════════════════════════════════════════════════════
# installer_i18n — help content catalogue
# ══════════════════════════════════════════════════════════════════════
from installer.installer_i18n import (
    DEFAULT_LANG,
    HELP_SECTIONS,
    LANG_LABELS,
    SUPPORTED_LANGS,
    get_full_help_text,
    get_help_sections,
    resolve_lang,
)


class TestInstallerI18nResolve:
    def test_resolves_known_lang(self):
        assert resolve_lang("de") == "de"
        assert resolve_lang("en") == "en"

    def test_falls_back_for_unknown(self):
        assert resolve_lang("fr") == DEFAULT_LANG
        assert resolve_lang(None) == DEFAULT_LANG
        assert resolve_lang("") == DEFAULT_LANG


class TestInstallerI18nConstants:
    def test_supported_langs_non_empty(self):
        assert len(SUPPORTED_LANGS) >= 2
        assert "de" in SUPPORTED_LANGS
        assert "en" in SUPPORTED_LANGS

    def test_lang_labels_cover_all_supported(self):
        for lang in SUPPORTED_LANGS:
            assert lang in LANG_LABELS

    def test_help_sections_non_empty(self):
        assert len(HELP_SECTIONS) >= 3

    def test_every_section_has_both_languages(self):
        for section in HELP_SECTIONS:
            for lang in SUPPORTED_LANGS:
                assert lang in section["title"], (
                    f"section '{section['id']}' missing title for {lang}"
                )
            for item in section["items"]:
                for lang in SUPPORTED_LANGS:
                    assert lang in item["title"], (
                        f"item missing title for {lang}"
                    )
                    assert lang in item["body"], (
                        f"item missing body for {lang}"
                    )


class TestGetHelpSections:
    def test_returns_list_for_de(self):
        result = get_help_sections("de")
        assert isinstance(result, list)
        assert len(result) >= 3
        assert all("heading" in s and "items" in s for s in result)

    def test_returns_list_for_en(self):
        result = get_help_sections("en")
        assert isinstance(result, list)
        assert len(result) >= 3

    def test_de_and_en_differ(self):
        de = get_help_sections("de")
        en = get_help_sections("en")
        # At least one heading must differ
        assert any(
            d["heading"] != e["heading"] for d, e in zip(de, en)
        )

    def test_unknown_lang_falls_back_to_de(self):
        result = get_help_sections("xx")
        de = get_help_sections("de")
        assert result == de

    def test_each_section_has_id(self):
        for section in get_help_sections("de"):
            assert "id" in section
            assert isinstance(section["id"], str)


class TestGetFullHelpText:
    def test_returns_non_empty_string_de(self):
        text = get_full_help_text("de")
        assert isinstance(text, str)
        assert len(text) > 200

    def test_returns_non_empty_string_en(self):
        text = get_full_help_text("en")
        assert isinstance(text, str)
        assert len(text) > 200

    def test_contains_section_headings(self):
        text = get_full_help_text("en")
        assert "INPUT FIELDS" in text
        assert "INSTALLATION STEPS" in text
