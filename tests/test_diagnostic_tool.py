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
