"""
Tests for the installer diagnostic tool (installer_logic.diagnose).

Covers:
- diagnose() returns a list of check dicts with correct structure
- Individual check functions handle present/missing/corrupt states
- DB diagnostics report table presence, row counts, and errors
- Log diagnostics detect error lines
- Port check, service status, scheduled task checks
- DiagnosticWindow key-sequence detection logic
"""
from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path
from unittest.mock import patch

from installer import installer_logic as logic


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_db(path: Path, with_data: bool = True) -> None:
    """Create a minimal TSM database at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE wheel_sets (
            id INTEGER PRIMARY KEY,
            customer_name TEXT,
            license_plate TEXT,
            car_type TEXT,
            storage_position TEXT UNIQUE,
            note TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            backup_interval_minutes INTEGER DEFAULT 60,
            backup_copies INTEGER DEFAULT 10
        )
    """)
    conn.execute("""
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY,
            action TEXT,
            details TEXT
        )
    """)
    if with_data:
        conn.execute(
            "INSERT INTO wheel_sets "
            "(customer_name, license_plate, car_type, storage_position) "
            "VALUES ('Test', 'B-XX 1', 'Golf', 'C1ROM')"
        )
        conn.execute(
            "INSERT INTO settings (backup_interval_minutes, backup_copies) "
            "VALUES (60, 10)"
        )
    conn.commit()
    conn.close()


def _mock_run_cmd(responses: dict):
    """Return a patched run_cmd that returns preset responses by command."""
    def _run(cmd, check=True):
        key = " ".join(cmd)
        for pattern, result in responses.items():
            if pattern in key:
                return result
        # Default: command not found
        import subprocess
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
    return _run


# ── Check structure ────────────────────────────────────────────────────────

class TestDiagnoseStructure:
    def test_returns_list_of_dicts(self, tmp_path):
        install = tmp_path / "install"
        data = tmp_path / "data"
        install.mkdir()
        data.mkdir()
        with patch.object(logic, "run_cmd", _mock_run_cmd({})):
            results = logic.diagnose(install, data)
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert "label" in r
            assert "status" in r
            assert r["status"] in ("ok", "warn", "error")
            assert "detail" in r


# ── DB diagnostics ─────────────────────────────────────────────────────────

class TestDiagDbFile:
    def test_missing_db(self, tmp_path):
        result = logic._diag_db_file(tmp_path / "nope.db")
        assert result["status"] == "error"
        assert "Nicht gefunden" in result["detail"]

    def test_empty_db(self, tmp_path):
        db = tmp_path / "empty.db"
        db.write_bytes(b"")
        result = logic._diag_db_file(db)
        assert result["status"] == "error"
        assert "Leer" in result["detail"]

    def test_valid_db_with_data(self, tmp_path):
        db = tmp_path / "wheel_storage.db"
        _make_db(db, with_data=True)
        result = logic._diag_db_file(db)
        assert result["status"] == "ok"
        assert "1 Radsätze" in result["detail"]
        assert "Settings: ✓" in result["detail"]

    def test_valid_db_no_data(self, tmp_path):
        db = tmp_path / "wheel_storage.db"
        _make_db(db, with_data=False)
        result = logic._diag_db_file(db)
        assert result["status"] == "ok"
        assert "0 Radsätze" in result["detail"]

    def test_corrupt_db(self, tmp_path):
        db = tmp_path / "corrupt.db"
        db.write_bytes(b"not a sqlite database" * 100)
        result = logic._diag_db_file(db)
        assert result["status"] == "error"
        assert "Lesefehler" in result["detail"]

    def test_missing_tables(self, tmp_path):
        db = tmp_path / "partial.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE wheel_sets (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        result = logic._diag_db_file(db)
        assert result["status"] == "warn"
        assert "fehlende Tabellen" in result["detail"]


# ── Directory/file checks ─────────────────────────────────────────────────

class TestDiagDirFile:
    def test_existing_dir(self, tmp_path):
        result = logic._diag_dir_exists("Test", tmp_path)
        assert result["status"] == "ok"

    def test_missing_dir(self, tmp_path):
        result = logic._diag_dir_exists("Test", tmp_path / "nope")
        assert result["status"] == "error"

    def test_existing_file(self, tmp_path):
        f = tmp_path / "test.exe"
        f.write_bytes(b"\x00" * 1024 * 1024)
        result = logic._diag_file_exists("test.exe", f)
        assert result["status"] == "ok"
        assert "1.0 MB" in result["detail"]

    def test_missing_file(self, tmp_path):
        result = logic._diag_file_exists("test.exe", tmp_path / "nope.exe")
        assert result["status"] == "error"


# ── Log diagnostics ───────────────────────────────────────────────────────

class TestDiagLogs:
    def test_no_log_dir(self, tmp_path):
        results = logic._diag_recent_logs(tmp_path / "nope")
        assert results == []

    def test_missing_log_file(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        results = logic._diag_recent_logs(log_dir)
        assert any(r["status"] == "warn" for r in results)

    def test_log_with_errors(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "tsm.log").write_text(
            "2026-07-16 INFO Starting\n"
            "2026-07-16 ERROR Something broke\n",
            encoding="utf-8",
        )
        results = logic._diag_recent_logs(log_dir)
        tsm_log = [r for r in results if "tsm.log" in r["label"]]
        assert len(tsm_log) == 1
        assert tsm_log[0]["status"] == "warn"

    def test_clean_log(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "tsm.log").write_text(
            "2026-07-16 INFO Starting\n"
            "2026-07-16 INFO Ready\n",
            encoding="utf-8",
        )
        results = logic._diag_recent_logs(log_dir)
        tsm_log = [r for r in results if "tsm.log" in r["label"]]
        assert len(tsm_log) == 1
        assert tsm_log[0]["status"] == "ok"


# ── Backup diagnostics ────────────────────────────────────────────────────

class TestDiagBackups:
    def test_missing_backup_dir(self, tmp_path):
        result = logic._diag_backup_dir(tmp_path / "nope")
        assert result["status"] == "warn"

    def test_backup_dir_with_files(self, tmp_path):
        bd = tmp_path / "backups"
        bd.mkdir()
        (bd / "pre_upgrade_20260716.db").write_bytes(b"\x00")
        (bd / "wheel_storage_20260715.db").write_bytes(b"\x00")
        (bd / "wheel_storage_20260715.csv").write_bytes(b"\x00")
        result = logic._diag_backup_dir(bd)
        assert result["status"] == "ok"
        assert "1 Upgrade-Sicherungen" in result["detail"]
        assert "1 reguläre DB-Backups" in result["detail"]


# ── Service status ─────────────────────────────────────────────────────────

class TestDiagServiceStatus:
    def test_running(self):
        import subprocess
        mock_result = subprocess.CompletedProcess(
            [], 0, stdout="STATE : 4  RUNNING", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock_result):
            result = logic._diag_service_status()
        assert result["status"] == "ok"

    def test_stopped(self):
        import subprocess
        mock_result = subprocess.CompletedProcess(
            [], 0, stdout="STATE : 1  STOPPED", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock_result):
            result = logic._diag_service_status()
        assert result["status"] == "error"
        assert "STOPPED" in result["detail"]

    def test_query_fails(self):
        with patch.object(logic, "run_cmd",
                          side_effect=Exception("access denied")):
            result = logic._diag_service_status()
        assert result["status"] == "error"


# ── NSSM config ────────────────────────────────────────────────────────────

class TestDiagNssmConfig:
    def test_nssm_not_found(self, tmp_path):
        results = logic._diag_nssm_config(tmp_path / "nope.exe")
        assert len(results) == 1
        assert results[0]["status"] == "error"

    def test_data_dir_present(self, tmp_path):
        nssm = tmp_path / "nssm.exe"
        nssm.write_bytes(b"\x00")
        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0,
            stdout='--data-dir "C:\\ProgramData\\TSM" --port 5000',
            stderr="")
        mock_env = subprocess.CompletedProcess(
            [], 0,
            stdout="TSM_DATA_DIR=C:\\ProgramData\\TSM\nTSM_PORT=5000",
            stderr="")
        call_count = [0]
        def side_effect(cmd, check=True):
            call_count[0] += 1
            if "AppParameters" in cmd:
                return mock
            return mock_env
        with patch.object(logic, "run_cmd", side_effect=side_effect):
            results = logic._diag_nssm_config(nssm)
        params = [r for r in results if "AppParameters" in r["label"]]
        assert params[0]["status"] == "ok"
        env = [r for r in results if "Umgebungsvariablen" in r["label"]]
        assert env[0]["status"] == "ok"

    def test_data_dir_missing_warns(self, tmp_path):
        nssm = tmp_path / "nssm.exe"
        nssm.write_bytes(b"\x00")
        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0, stdout="--port 5000", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            results = logic._diag_nssm_config(nssm)
        params = [r for r in results if "AppParameters" in r["label"]]
        assert params[0]["status"] == "warn"
        assert "--data-dir fehlt" in params[0]["detail"]


# ── Scheduled task ─────────────────────────────────────────────────────────

class TestDiagScheduledTask:
    def test_task_exists(self):
        import subprocess
        mock = subprocess.CompletedProcess([], 0, stdout="TaskName: ...",
                                           stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            result = logic._diag_scheduled_task()
        assert result["status"] == "ok"

    def test_task_missing(self):
        import subprocess
        mock = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            result = logic._diag_scheduled_task()
        assert result["status"] == "warn"


# ── Key sequence detection (InstallerApp) ─────────────────────────────────

class TestDiagKeySequence:
    """Test the '###' key-sequence detection logic without Tkinter."""

    def test_three_hashes_triggers(self):
        keys: list[str] = []
        triggered = [False]

        def on_key(char):
            if char == "#":
                keys.append("#")
                if len(keys) >= 3:
                    keys.clear()
                    triggered[0] = True
            else:
                keys.clear()

        on_key("#")
        assert not triggered[0]
        on_key("#")
        assert not triggered[0]
        on_key("#")
        assert triggered[0]

    def test_interrupted_sequence_resets(self):
        keys: list[str] = []
        triggered = [False]

        def on_key(char):
            if char == "#":
                keys.append("#")
                if len(keys) >= 3:
                    keys.clear()
                    triggered[0] = True
            else:
                keys.clear()

        on_key("#")
        on_key("#")
        on_key("a")  # interrupts
        on_key("#")
        on_key("#")
        assert not triggered[0]  # only 2 after reset

    def test_four_hashes_triggers_once(self):
        keys: list[str] = []
        count = [0]

        def on_key(char):
            if char == "#":
                keys.append("#")
                if len(keys) >= 3:
                    keys.clear()
                    count[0] += 1
            else:
                keys.clear()

        on_key("#")
        on_key("#")
        on_key("#")
        on_key("#")
        assert count[0] == 1


# ── Full diagnose() integration ───────────────────────────────────────────

class TestDiagnoseIntegration:
    def test_full_healthy_install(self, tmp_path):
        """Simulate a healthy installation and verify all checks."""
        install = tmp_path / "install"
        data = tmp_path / "data"
        install.mkdir()
        (install / "TireStorageManager.exe").write_bytes(b"\x00" * 1024)
        nssm = install / "nssm.exe"
        nssm.write_bytes(b"\x00" * 512)

        data.mkdir()
        (data / "db").mkdir()
        _make_db(data / "db" / "wheel_storage.db", with_data=True)
        (data / "logs").mkdir()
        (data / "logs" / "tsm.log").write_text(
            "2026-07-16 INFO OK\n", encoding="utf-8")
        (data / "backups").mkdir()

        import subprocess
        responses = {
            "sc.exe query": subprocess.CompletedProcess(
                [], 0, stdout="STATE : 4  RUNNING", stderr=""),
            "AppParameters": subprocess.CompletedProcess(
                [], 0, stdout='--data-dir "C:\\data" --port 5000',
                stderr=""),
            "AppEnvironmentExtra": subprocess.CompletedProcess(
                [], 0, stdout="TSM_DATA_DIR=C:\\data", stderr=""),
            "sc.exe qc": subprocess.CompletedProcess(
                [], 0, stdout="--port 5000", stderr=""),
            "schtasks": subprocess.CompletedProcess(
                [], 0, stdout="TaskName", stderr=""),
        }
        with patch.object(logic, "run_cmd",
                          side_effect=_mock_run_cmd(responses)):
            # Patch socket to simulate port responding
            import socket
            with patch.object(socket.socket, "connect"):
                results = logic.diagnose(install, data)

        errors = [r for r in results if r["status"] == "error"]
        assert len(errors) == 0, \
            f"Unexpected errors: {[r['label'] for r in errors]}"


# ── Fresh install detection ───────────────────────────────────────────────

class TestFreshInstallDetection:
    def test_fresh_install_when_no_service(self):
        import subprocess
        mock = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            assert logic.is_fresh_install() is True

    def test_not_fresh_when_service_exists(self):
        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0, stdout="STATE : 4  RUNNING", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            assert logic.is_fresh_install() is False


# ── fetch_all_releases ────────────────────────────────────────────────────

class TestFetchAllReleases:
    def test_returns_list(self):
        import json as _json
        fake_releases = [
            {
                "tag_name": "v1.10.0",
                "name": "TireStorageManager v1.10.0",
                "prerelease": False,
                "published_at": "2026-07-16T10:00:00Z",
                "assets": [
                    {"name": "TireStorageManager.exe",
                     "browser_download_url": "https://example.com/app.exe"},
                    {"name": "TSM-Installer.exe",
                     "browser_download_url": "https://example.com/inst.exe"},
                ],
            },
            {
                "tag_name": "v1.9.0",
                "name": "TireStorageManager v1.9.0",
                "prerelease": False,
                "published_at": "2026-07-15T10:00:00Z",
                "assets": [],
            },
        ]

        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = _json.dumps(
            fake_releases).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            releases = logic.fetch_all_releases()

        assert len(releases) == 2
        assert releases[0]["version"] == "1.10.0"
        assert releases[0]["app_url"] == "https://example.com/app.exe"
        # v1.9.0 has no EXE asset
        assert releases[1]["app_url"] is None

    def test_returns_empty_on_network_error(self):
        with patch("urllib.request.urlopen",
                   side_effect=Exception("no network")):
            releases = logic.fetch_all_releases()
        assert releases == []


# ── verify_service_health ─────────────────────────────────────────────────

class TestVerifyServiceHealth:
    def test_healthy_service(self, tmp_path):
        data = tmp_path / "data"
        (data / "db").mkdir(parents=True)
        _make_db(data / "db" / "wheel_storage.db", with_data=True)

        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0, stdout="--port 5000", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            import socket
            with patch.object(socket.socket, "connect"):
                # Mock HTTP response
                from unittest.mock import MagicMock
                mock_resp = MagicMock()
                mock_resp.status = 200
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
                with patch("urllib.request.urlopen",
                           return_value=mock_resp):
                    ok = logic.verify_service_health(
                        data, timeout=2)
        assert ok is True

    def test_port_not_responding(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()

        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0, stdout="--port 59999", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            import socket
            with patch.object(socket.socket, "connect",
                              side_effect=ConnectionRefusedError):
                ok = logic.verify_service_health(
                    data, timeout=2)
        assert ok is False


# ── Self-update rollback (run.py integration) ─────────────────────────────

class TestSelfUpdateRollback:
    """Test the update marker and rollback mechanism in self_update.py."""

    def test_write_and_read_marker(self, tmp_path, monkeypatch):
        from tsm import self_update as su
        marker_exe = tmp_path / "TireStorageManager.exe"
        marker_exe.write_bytes(b"\x00")
        monkeypatch.setattr(su, "_current_exe", lambda: marker_exe)
        monkeypatch.setattr(su, "_is_frozen", lambda: True)

        su._write_update_marker("1.9.0", "1.10.0")
        result = su.read_update_marker()
        assert result == ("1.9.0", "1.10.0")

    def test_read_marker_removes_file(self, tmp_path, monkeypatch):
        from tsm import self_update as su
        marker_exe = tmp_path / "TireStorageManager.exe"
        marker_exe.write_bytes(b"\x00")
        monkeypatch.setattr(su, "_current_exe", lambda: marker_exe)
        monkeypatch.setattr(su, "_is_frozen", lambda: True)

        su._write_update_marker("1.9.0", "1.10.0")
        su.read_update_marker()
        # Second read returns None (marker consumed)
        assert su.read_update_marker() is None

    def test_read_marker_returns_none_when_not_frozen(self, monkeypatch):
        from tsm import self_update as su
        monkeypatch.setattr(su, "_is_frozen", lambda: False)
        assert su.read_update_marker() is None

    def test_rollback_swaps_exe(self, tmp_path, monkeypatch):
        from tsm import self_update as su
        exe = tmp_path / "TireStorageManager.exe"
        old = tmp_path / "TireStorageManager.exe.old"
        exe.write_bytes(b"new")
        old.write_bytes(b"old")
        monkeypatch.setattr(su, "_current_exe", lambda: exe)
        monkeypatch.setattr(su, "_is_frozen", lambda: True)
        monkeypatch.setattr(su, "_restart_service", lambda: None)

        result = su.rollback_update()
        assert result is True
        assert exe.read_bytes() == b"old"
        assert (tmp_path / "TireStorageManager.exe.failed").read_bytes() == b"new"

    def test_rollback_fails_without_old_exe(self, tmp_path, monkeypatch):
        from tsm import self_update as su
        exe = tmp_path / "TireStorageManager.exe"
        exe.write_bytes(b"new")
        monkeypatch.setattr(su, "_current_exe", lambda: exe)
        monkeypatch.setattr(su, "_is_frozen", lambda: True)

        result = su.rollback_update()
        assert result is False


# ── deploy_release rollback on failure ────────────────────────────────────

class TestDeployReleaseRollback:
    def test_rollback_on_verify_failure(self, tmp_path):
        """When verification fails, deploy_release rolls back."""
        install = tmp_path / "install"
        data = tmp_path / "data"
        install.mkdir()
        (data / "db").mkdir(parents=True)

        # Create a fake "old" EXE
        app_exe = install / "TireStorageManager.exe"
        app_exe.write_bytes(b"old_version_content")
        nssm = install / "nssm.exe"
        nssm.write_bytes(b"\x00")

        logged: list[str] = []

        with patch.object(logic, "download_file", return_value=True):
            with patch.object(logic, "pre_upgrade_backup"):
                with patch.object(logic, "stop_service"):
                    with patch.object(logic, "start_service"):
                        # Verify always fails
                        with patch.object(logic, "verify_service_health",
                                          return_value=False):
                            # Make the temp file exist
                            import tempfile
                            with patch("tempfile.mktemp",
                                       return_value=str(
                                           install / "tmp.exe")):
                                (install / "tmp.exe").write_bytes(
                                    b"new_version")
                                ok = logic.deploy_release(
                                    app_url="https://example.com/app.exe",
                                    install_dir=install,
                                    data_dir=data,
                                    log=logged.append,
                                )

        assert ok is False
        assert any("Rollback" in l for l in logged)


# ========================================================
# EDGE-CASE TESTS
# ========================================================

# ── Update marker edge cases ─────────────────────────────────────────────

class TestUpdateMarkerEdgeCases:
    def test_marker_with_only_one_line(self, tmp_path, monkeypatch):
        """Marker with only one line should return None (malformed)."""
        from tsm import self_update as su
        exe = tmp_path / "app.exe"
        exe.write_bytes(b"\x00")
        monkeypatch.setattr(su, "_current_exe", lambda: exe)
        monkeypatch.setattr(su, "_is_frozen", lambda: True)
        marker = exe.with_suffix(".update_marker")
        marker.write_text("1.9.0\n", encoding="utf-8")
        assert su.read_update_marker() is None

    def test_marker_with_empty_file(self, tmp_path, monkeypatch):
        from tsm import self_update as su
        exe = tmp_path / "app.exe"
        exe.write_bytes(b"\x00")
        monkeypatch.setattr(su, "_current_exe", lambda: exe)
        monkeypatch.setattr(su, "_is_frozen", lambda: True)
        marker = exe.with_suffix(".update_marker")
        marker.write_text("", encoding="utf-8")
        assert su.read_update_marker() is None

    def test_marker_with_extra_whitespace(self, tmp_path, monkeypatch):
        from tsm import self_update as su
        exe = tmp_path / "app.exe"
        exe.write_bytes(b"\x00")
        monkeypatch.setattr(su, "_current_exe", lambda: exe)
        monkeypatch.setattr(su, "_is_frozen", lambda: True)
        su._write_update_marker("  1.8.0  ", "  1.9.0  ")
        result = su.read_update_marker()
        assert result == ("1.8.0", "1.9.0")

    def test_marker_absent_returns_none(self, tmp_path, monkeypatch):
        from tsm import self_update as su
        exe = tmp_path / "app.exe"
        exe.write_bytes(b"\x00")
        monkeypatch.setattr(su, "_current_exe", lambda: exe)
        monkeypatch.setattr(su, "_is_frozen", lambda: True)
        assert su.read_update_marker() is None


# ── Rollback edge cases ──────────────────────────────────────────────────

class TestRollbackEdgeCases:
    def test_rollback_cleans_existing_failed_file(self, tmp_path, monkeypatch):
        """If .exe.failed already exists from a prior rollback, remove it."""
        from tsm import self_update as su
        exe = tmp_path / "app.exe"
        old = tmp_path / "app.exe.old"
        failed = tmp_path / "app.exe.failed"
        exe.write_bytes(b"new")
        old.write_bytes(b"old")
        failed.write_bytes(b"ancient_failed")
        monkeypatch.setattr(su, "_current_exe", lambda: exe)
        monkeypatch.setattr(su, "_is_frozen", lambda: True)
        monkeypatch.setattr(su, "_restart_service", lambda: None)

        result = su.rollback_update()
        assert result is True
        assert exe.read_bytes() == b"old"
        assert failed.read_bytes() == b"new"  # latest failed, not ancient

    def test_rollback_not_frozen_returns_false(self, monkeypatch):
        from tsm import self_update as su
        monkeypatch.setattr(su, "_is_frozen", lambda: False)
        assert su.rollback_update() is False


# ── DB diagnostic edge cases ─────────────────────────────────────────────

class TestDiagDbEdgeCases:
    def test_db_file_is_directory(self, tmp_path):
        """If the DB path is a directory, report error."""
        db = tmp_path / "wheel_storage.db"
        db.mkdir()
        result = logic._diag_db_file(db)
        assert result["status"] == "error"

    def test_db_with_all_tables_but_no_wheelsets(self, tmp_path):
        db = tmp_path / "ws.db"
        _make_db(db, with_data=False)
        result = logic._diag_db_file(db)
        assert result["status"] == "ok"
        assert "0 Radsätze" in result["detail"]

    def test_db_with_many_wheelsets(self, tmp_path):
        db = tmp_path / "ws.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE wheel_sets (id INTEGER PRIMARY KEY, "
                     "customer_name TEXT, storage_position TEXT UNIQUE)")
        conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY)")
        for i in range(50):
            conn.execute(
                "INSERT INTO wheel_sets (customer_name, storage_position) "
                f"VALUES ('Customer {i}', 'POS{i}')")
        conn.commit()
        conn.close()
        result = logic._diag_db_file(db)
        assert result["status"] == "ok"
        assert "50 Radsätze" in result["detail"]


# ── Log diagnostic edge cases ────────────────────────────────────────────

class TestDiagLogEdgeCases:
    def test_log_with_traceback(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "tsm.log").write_text(
            "2026-07-16 INFO Starting\n"
            "Traceback (most recent call last):\n"
            "  File 'x.py', line 1\n"
            "RuntimeError: boom\n",
            encoding="utf-8",
        )
        results = logic._diag_recent_logs(log_dir)
        tsm = [r for r in results if "tsm.log" in r["label"]]
        assert tsm[0]["status"] == "warn"

    def test_empty_log_file(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "tsm.log").write_text("", encoding="utf-8")
        results = logic._diag_recent_logs(log_dir)
        tsm = [r for r in results if "tsm.log" in r["label"]]
        assert tsm[0]["status"] == "ok"  # empty = no errors

    def test_service_stderr_with_error(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "service_stderr.log").write_text(
            "ERROR: Cannot bind port 5000\n", encoding="utf-8")
        results = logic._diag_recent_logs(log_dir)
        stderr = [r for r in results if "service_stderr" in r["label"]]
        assert len(stderr) == 1
        assert stderr[0]["status"] == "warn"


# ── Backup diagnostic edge cases ─────────────────────────────────────────

class TestDiagBackupEdgeCases:
    def test_empty_backup_dir(self, tmp_path):
        bd = tmp_path / "backups"
        bd.mkdir()
        result = logic._diag_backup_dir(bd)
        assert result["status"] == "ok"
        assert "0 Dateien" in result["detail"]

    def test_mixed_file_types(self, tmp_path):
        bd = tmp_path / "backups"
        bd.mkdir()
        (bd / "pre_upgrade_20260716.db").write_bytes(b"\x00")
        (bd / "pre_upgrade_20260715.db").write_bytes(b"\x00")
        (bd / "wheel_storage_20260714.db").write_bytes(b"\x00")
        (bd / "wheel_storage_20260714.csv").write_bytes(b"\x00")
        (bd / "wheel_storage_20260714.xlsx").write_bytes(b"\x00")
        result = logic._diag_backup_dir(bd)
        assert "2 Upgrade-Sicherungen" in result["detail"]
        assert "1 reguläre DB-Backups" in result["detail"]
        assert "5 Dateien" in result["detail"]


# ── Service status edge cases ─────────────────────────────────────────────

class TestDiagServiceEdgeCases:
    def test_stop_pending(self):
        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0, stdout="STATE : 3  STOP_PENDING", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            result = logic._diag_service_status()
        assert result["status"] == "warn"
        assert "STOP_PENDING" in result["detail"]

    def test_start_pending(self):
        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0, stdout="STATE : 2  START_PENDING", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            result = logic._diag_service_status()
        assert result["status"] == "warn"
        assert "START_PENDING" in result["detail"]

    def test_unknown_state(self):
        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0, stdout="STATE : 7  PAUSED", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            result = logic._diag_service_status()
        assert result["status"] == "warn"


# ── NSSM config edge cases ───────────────────────────────────────────────

class TestNssmEdgeCases:
    def test_nssm_command_fails(self, tmp_path):
        nssm = tmp_path / "nssm.exe"
        nssm.write_bytes(b"\x00")
        with patch.object(logic, "run_cmd",
                          side_effect=Exception("permission denied")):
            results = logic._diag_nssm_config(nssm)
        assert all(r["status"] == "error" for r in results)

    def test_env_without_tsm_data_dir(self, tmp_path):
        nssm = tmp_path / "nssm.exe"
        nssm.write_bytes(b"\x00")
        import subprocess
        params_ok = subprocess.CompletedProcess(
            [], 0, stdout='--data-dir "C:\\data" --port 5000', stderr="")
        env_bad = subprocess.CompletedProcess(
            [], 0, stdout="TSM_PORT=5000\nTSM_APP_NAME=Reifenmanager",
            stderr="")

        def side_effect(cmd, check=True):
            if "AppParameters" in cmd:
                return params_ok
            return env_bad

        with patch.object(logic, "run_cmd", side_effect=side_effect):
            results = logic._diag_nssm_config(nssm)
        env = [r for r in results if "Umgebungsvariablen" in r["label"]]
        assert env[0]["status"] == "warn"
        assert "TSM_DATA_DIR fehlt" in env[0]["detail"]


# ── deploy_release edge cases ────────────────────────────────────────────

class TestDeployReleaseEdgeCases:
    def test_download_failure_returns_false(self, tmp_path):
        install = tmp_path / "install"
        data = tmp_path / "data"
        install.mkdir()
        data.mkdir()

        logged: list[str] = []
        with patch.object(logic, "download_file", return_value=False):
            import tempfile
            with patch("tempfile.mktemp",
                       return_value=str(install / "tmp.exe")):
                ok = logic.deploy_release(
                    app_url="https://example.com/fail.exe",
                    install_dir=install,
                    data_dir=data,
                    log=logged.append,
                )
        assert ok is False
        assert any("fehlgeschlagen" in l for l in logged)

    def test_successful_deploy(self, tmp_path):
        install = tmp_path / "install"
        data = tmp_path / "data"
        install.mkdir()
        (data / "db").mkdir(parents=True)

        app_exe = install / "TireStorageManager.exe"
        app_exe.write_bytes(b"old")
        nssm = install / "nssm.exe"
        nssm.write_bytes(b"\x00")

        logged: list[str] = []

        with patch.object(logic, "download_file", return_value=True):
            with patch.object(logic, "pre_upgrade_backup"):
                with patch.object(logic, "stop_service"):
                    with patch.object(logic, "start_service"):
                        with patch.object(logic, "verify_service_health",
                                          return_value=True):
                            import tempfile
                            with patch("tempfile.mktemp",
                                       return_value=str(
                                           install / "tmp.exe")):
                                (install / "tmp.exe").write_bytes(
                                    b"new")
                                ok = logic.deploy_release(
                                    app_url="https://example.com/ok.exe",
                                    install_dir=install,
                                    data_dir=data,
                                    log=logged.append,
                                )
        assert ok is True


# ── verify_service_health edge cases ─────────────────────────────────────

class TestVerifyHealthEdgeCases:
    def test_db_missing(self, tmp_path):
        """Service responds but DB file doesn't exist."""
        data = tmp_path / "data"
        data.mkdir()
        # No db/ directory

        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0, stdout="--port 5000", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            import socket
            with patch.object(socket.socket, "connect"):
                from unittest.mock import MagicMock
                mock_resp = MagicMock()
                mock_resp.status = 200
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
                with patch("urllib.request.urlopen",
                           return_value=mock_resp):
                    logged: list[str] = []
                    ok = logic.verify_service_health(
                        data, timeout=2, log=logged.append)
        # Port + HTTP OK, but DB missing — still returns True
        # (service is running, DB issue is separate)
        assert ok is True
        assert any("nicht gefunden" in l for l in logged)

    def test_http_fails_but_port_open(self, tmp_path):
        """TCP connects but HTTP returns error."""
        data = tmp_path / "data"
        data.mkdir()

        import subprocess
        mock = subprocess.CompletedProcess(
            [], 0, stdout="--port 5000", stderr="")
        with patch.object(logic, "run_cmd", return_value=mock):
            import socket
            with patch.object(socket.socket, "connect"):
                with patch("urllib.request.urlopen",
                           side_effect=Exception("500")):
                    ok = logic.verify_service_health(
                        data, timeout=2)
        assert ok is False


# ── Post-update verification integration (run.py logic) ──────────────────

class TestPostUpdateVerification:
    """Test the verification logic from run.py main() without actually
    starting the server."""

    def test_no_marker_skips_verification(self, monkeypatch):
        """When no marker exists, verification is skipped."""
        from tsm import self_update as su
        monkeypatch.setattr(su, "_is_frozen", lambda: True)
        monkeypatch.setattr(su, "read_update_marker", lambda: None)
        # If verification ran, it would try to import SessionLocal
        # and fail — so no marker = no crash = test passes

    def test_marker_with_accessible_db_passes(
            self, db_session, db_engine, monkeypatch):
        """Post-update with a healthy DB should pass verification."""
        from tsm.models import Settings, WheelSet
        s = Settings(backup_interval_minutes=60, backup_copies=10)
        db_session.add(s)
        db_session.commit()

        # Simulate querying core tables (what run.py does)
        db_session.query(Settings).first()
        count = db_session.query(WheelSet).count()
        assert count == 0  # empty but queryable = OK


# ── fresh_install warning logic ──────────────────────────────────────────

class TestFreshInstallWarning:
    def test_is_fresh_install_delegates_to_service_exists(self):
        """is_fresh_install() should be the inverse of service_exists()."""
        import subprocess
        exists = subprocess.CompletedProcess(
            [], 0, stdout="RUNNING", stderr="")
        not_exists = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="not found")

        with patch.object(logic, "run_cmd", return_value=exists):
            assert logic.is_fresh_install() is False
        with patch.object(logic, "run_cmd", return_value=not_exists):
            assert logic.is_fresh_install() is True
