#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for installer.installer_logic  –  install / uninstall steps.

Every OS-level side effect (subprocess, shutil, filesystem) is mocked
so the tests run on any platform (including Linux CI runners).
"""
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from installer import installer_logic as logic


# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────
def _ok(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Return a fake CompletedProcess."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


# ────────────────────────────────────────────────
# ensure_dir
# ────────────────────────────────────────────────
class TestEnsureDir:
    def test_creates_directory(self, tmp_path: Path):
        target = tmp_path / "a" / "b" / "c"
        logic.ensure_dir(target)
        assert target.is_dir()

    def test_idempotent(self, tmp_path: Path):
        target = tmp_path / "x"
        logic.ensure_dir(target)
        logic.ensure_dir(target)  # no error on 2nd call
        assert target.is_dir()


# ────────────────────────────────────────────────
# copy_file
# ────────────────────────────────────────────────
class TestCopyFile:
    def test_copies_file(self, tmp_path: Path):
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dest = tmp_path / "out" / "dest.txt"
        assert logic.copy_file(src, dest) is True
        assert dest.read_text() == "hello"

    def test_returns_false_if_src_missing(self, tmp_path: Path):
        dest = tmp_path / "dest.txt"
        assert logic.copy_file(tmp_path / "nope.txt", dest) is False
        assert not dest.exists()

    def test_no_overwrite_by_default(self, tmp_path: Path):
        src = tmp_path / "src.txt"
        src.write_text("new")
        dest = tmp_path / "dest.txt"
        dest.write_text("old")
        assert logic.copy_file(src, dest, overwrite=False) is True
        assert dest.read_text() == "old"

    def test_overwrite_when_requested(self, tmp_path: Path):
        src = tmp_path / "src.txt"
        src.write_text("new")
        dest = tmp_path / "dest.txt"
        dest.write_text("old")
        assert logic.copy_file(src, dest, overwrite=True) is True
        assert dest.read_text() == "new"


# ────────────────────────────────────────────────
# INSTALL STEPS
# ────────────────────────────────────────────────
class TestCreateDirectories:
    def test_creates_all_dirs(self, tmp_path: Path):
        install = tmp_path / "install"
        data = tmp_path / "data"
        msgs: list[str] = []
        logic.create_directories(install, data, log=msgs.append)
        assert install.is_dir()
        assert (data / "db").is_dir()
        assert (data / "backups").is_dir()
        assert (data / "logs").is_dir()
        assert len(msgs) == 5  # install + data + db + backups + logs


class TestDeployNssm:
    def test_copies_nssm(self, tmp_path: Path):
        src = tmp_path / "payload" / "nssm.exe"
        src.parent.mkdir()
        src.write_bytes(b"\x00")
        install = tmp_path / "install"
        install.mkdir()
        msgs: list[str] = []
        result = logic.deploy_nssm(src, install, log=msgs.append)
        assert result == install / "nssm.exe"
        assert result.exists()
        assert len(msgs) == 1

    def test_raises_on_missing_src(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match="nssm"):
            logic.deploy_nssm(
                tmp_path / "missing.exe", tmp_path / "install")


class TestDeployAppExe:
    def test_copies_app(self, tmp_path: Path):
        src = tmp_path / "payload" / "TireStorageManager.exe"
        src.parent.mkdir()
        src.write_bytes(b"\x00")
        install = tmp_path / "install"
        install.mkdir()
        msgs: list[str] = []
        result = logic.deploy_app_exe(src, install, log=msgs.append)
        assert result == install / "TireStorageManager.exe"
        assert result.exists()

    def test_raises_on_missing_src(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match="TireStorageManager"):
            logic.deploy_app_exe(
                tmp_path / "missing.exe", tmp_path / "install")


class TestSeedDatabase:
    def test_seeds_when_no_db(self, tmp_path: Path):
        seed = tmp_path / "seed.db"
        seed.write_bytes(b"SQLITE")
        data = tmp_path / "data"
        (data / "db").mkdir(parents=True)
        msgs: list[str] = []
        logic.seed_database(seed, data, log=msgs.append)
        assert (data / "db" / "wheel_storage.db").read_bytes() == b"SQLITE"
        assert "Vorlage" in msgs[0]

    def test_skips_when_db_exists(self, tmp_path: Path):
        seed = tmp_path / "seed.db"
        seed.write_bytes(b"NEW")
        data = tmp_path / "data"
        (data / "db").mkdir(parents=True)
        (data / "db" / "wheel_storage.db").write_bytes(b"OLD")
        msgs: list[str] = []
        logic.seed_database(seed, data, log=msgs.append)
        assert (data / "db" / "wheel_storage.db").read_bytes() == b"OLD"
        assert "existiert" in msgs[0]

    def test_no_seed_no_db(self, tmp_path: Path):
        data = tmp_path / "data"
        (data / "db").mkdir(parents=True)
        msgs: list[str] = []
        logic.seed_database(tmp_path / "missing.db", data, log=msgs.append)
        assert "ersten Start" in msgs[0]


class TestAddFirewallRule:
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_success(self, mock_run):
        msgs: list[str] = []
        logic.add_firewall_rule(5000, log=msgs.append)
        mock_run.assert_called_once()
        assert "erstellt" in msgs[0]

    @patch.object(logic, "run_cmd", return_value=_ok(1, stderr="exists"))
    def test_already_exists(self, mock_run):
        msgs: list[str] = []
        logic.add_firewall_rule(5000, log=msgs.append)
        assert "exists" in msgs[0] or "ℹ" in msgs[0]


class TestInstallService:
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_calls_nssm_commands(self, mock_run, tmp_path: Path):
        nssm = tmp_path / "nssm.exe"
        app = tmp_path / "app.exe"
        msgs: list[str] = []
        logic.install_service(
            nssm, app, tmp_path / "data", 5000,
            tmp_path / "install", log=msgs.append)
        # Should call: stop, remove, install, set*7, env
        assert mock_run.call_count >= 10
        assert "installiert" in msgs[0]

    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_secret_key_included_when_provided(self, mock_run, tmp_path):
        """TSM_SECRET_KEY must appear in AppEnvironmentExtra when set.

        The secret key is the only security token that protects Flask
        sessions.  If install_service silently drops it the service
        starts with the default insecure fallback key.
        """
        nssm = tmp_path / "nssm.exe"
        app = tmp_path / "app.exe"
        logic.install_service(
            nssm, app, tmp_path / "data", 5000,
            tmp_path / "install", secret_key="my-secret-key",
        )
        # Find the AppEnvironmentExtra call
        env_calls = [
            call for call in mock_run.call_args_list
            if "AppEnvironmentExtra" in call[0][0]
        ]
        assert len(env_calls) == 1, "AppEnvironmentExtra must be set once"
        env_value: str = env_calls[0][0][0][-1]
        assert "TSM_SECRET_KEY=my-secret-key" in env_value

    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_secret_key_omitted_when_empty(self, mock_run, tmp_path):
        """When no secret key is given, TSM_SECRET_KEY must NOT appear.

        The app then falls back to the default key from config.py.
        Injecting an empty string would override the default with
        an empty value, which breaks Flask session signing.
        """
        nssm = tmp_path / "nssm.exe"
        app = tmp_path / "app.exe"
        logic.install_service(
            nssm, app, tmp_path / "data", 5000,
            tmp_path / "install", secret_key="",
        )
        env_calls = [
            call for call in mock_run.call_args_list
            if "AppEnvironmentExtra" in call[0][0]
        ]
        assert len(env_calls) == 1
        env_value: str = env_calls[0][0][0][-1]
        assert "TSM_SECRET_KEY" not in env_value


class TestStartService:
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_success_via_sc(self, mock_run, tmp_path: Path):
        msgs: list[str] = []
        logic.start_service(tmp_path / "nssm.exe", log=msgs.append)
        # sc.exe was enough
        assert mock_run.call_count == 1
        assert "gestartet" in msgs[0]

    @patch.object(logic, "run_cmd")
    def test_fallback_to_nssm(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [_ok(1), _ok(0)]  # sc fails, nssm ok
        msgs: list[str] = []
        logic.start_service(tmp_path / "nssm.exe", log=msgs.append)
        assert mock_run.call_count == 2
        assert "NSSM" in msgs[0]


class TestCreateUpdateTask:
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_success(self, mock_run):
        msgs: list[str] = []
        logic.create_update_task(log=msgs.append)
        mock_run.assert_called_once()
        assert "Task" in msgs[0]

    @patch.object(logic, "run_cmd", return_value=_ok(1, stderr="fail"))
    def test_failure_logged(self, mock_run):
        msgs: list[str] = []
        logic.create_update_task(log=msgs.append)
        assert "ℹ" in msgs[0]

    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_command_uses_cmd_c_wrapper(self, mock_run):
        """Regression: /TR must be wrapped in cmd /c so the shell
        evaluates the & operator.  Without it sc.exe stop runs but
        sc.exe start never executes, leaving the service down.
        Implementation uses run_cmd (list, no shell=True) to avoid
        double-escaping the /TR value."""
        logic.create_update_task()
        # run_cmd receives a list; the /TR value is the element after "/TR"
        args: list[str] = mock_run.call_args[0][0]
        tr_index = args.index("/TR")
        tr_value: str = args[tr_index + 1]
        # Must delegate to cmd /c so & is evaluated by the shell.
        assert "cmd /c" in tr_value
        # Both stop and start must be present in the correct order.
        assert "sc.exe stop" in tr_value
        assert "sc.exe start" in tr_value
        assert tr_value.index("sc.exe stop") < tr_value.index("sc.exe start")


# ────────────────────────────────────────────────
# VALIDATE SQLITE FILE
# ────────────────────────────────────────────────
def _make_valid_app_db(path: Path) -> None:
    """Create a minimal SQLite file with the required app schema."""
    con = sqlite3.connect(str(path))
    try:
        con.executescript("""
            CREATE TABLE wheel_sets (
                id INTEGER PRIMARY KEY,
                customer_name TEXT NOT NULL,
                license_plate TEXT NOT NULL,
                car_type TEXT NOT NULL,
                storage_position TEXT NOT NULL
            );
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                backup_interval_minutes INTEGER NOT NULL,
                backup_copies INTEGER NOT NULL
            );
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY,
                action TEXT NOT NULL
            );
        """)
        con.commit()
    finally:
        con.close()


class TestValidateSqliteFile:
    def test_valid_sqlite_with_schema(self, tmp_path: Path):
        db = tmp_path / "good.db"
        _make_valid_app_db(db)
        logic.validate_sqlite_file(db)  # must not raise

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="nicht gefunden"):
            logic.validate_sqlite_file(tmp_path / "nope.db")

    def test_too_small_raises(self, tmp_path: Path):
        db = tmp_path / "tiny.db"
        db.write_bytes(b"\x00" * 4)
        with pytest.raises(ValueError, match="zu klein"):
            logic.validate_sqlite_file(db)

    def test_wrong_magic_raises(self, tmp_path: Path):
        db = tmp_path / "bad.db"
        db.write_bytes(b"This is not SQLite!" + b"\x00" * 100)
        with pytest.raises(ValueError, match="Header"):
            logic.validate_sqlite_file(db)

    def test_missing_required_table_raises(self, tmp_path: Path):
        db = tmp_path / "notables.db"
        # Valid SQLite but missing wheel_sets / settings / audit_log
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE other (id INTEGER PRIMARY KEY)")
        con.commit()
        con.close()
        with pytest.raises(ValueError, match="Pflicht-Tabellen"):
            logic.validate_sqlite_file(db)

    def test_missing_required_column_raises(self, tmp_path: Path):
        db = tmp_path / "badcols.db"
        # Has all tables but wheel_sets is missing customer_name
        con = sqlite3.connect(str(db))
        con.executescript("""
            CREATE TABLE wheel_sets (
                id INTEGER PRIMARY KEY,
                license_plate TEXT,
                car_type TEXT,
                storage_position TEXT
            );
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                backup_interval_minutes INTEGER,
                backup_copies INTEGER
            );
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY,
                action TEXT
            );
        """)
        con.commit()
        con.close()
        with pytest.raises(ValueError, match="customer_name"):
            logic.validate_sqlite_file(db)

    def test_extra_columns_accepted(self, tmp_path: Path):
        db = tmp_path / "extra.db"
        # Full required schema plus additional columns (simulates migration)
        con = sqlite3.connect(str(db))
        con.executescript("""
            CREATE TABLE wheel_sets (
                id INTEGER PRIMARY KEY,
                customer_name TEXT NOT NULL,
                license_plate TEXT NOT NULL,
                car_type TEXT NOT NULL,
                storage_position TEXT NOT NULL,
                note TEXT,
                created_at DATETIME,
                updated_at DATETIME
            );
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                backup_interval_minutes INTEGER NOT NULL,
                backup_copies INTEGER NOT NULL,
                dark_mode BOOLEAN,
                auto_update BOOLEAN,
                custom_positions_json TEXT
            );
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY,
                action TEXT NOT NULL,
                wheelset_id INTEGER,
                details TEXT,
                created_at DATETIME
            );
            CREATE TABLE disabled_positions (
                code TEXT PRIMARY KEY,
                reason TEXT
            );
        """)
        con.commit()
        con.close()
        logic.validate_sqlite_file(db)  # must not raise


# ────────────────────────────────────────────────
# RESTORE DATABASE
# ────────────────────────────────────────────────
class TestRestoreDatabase:
    def _make_db(self, path: Path, content: bytes = b"") -> Path:
        """Create a valid app-schema DB, optionally append extra bytes."""
        _make_valid_app_db(path)
        if content:
            with open(path, "ab") as fh:
                fh.write(content)
        return path

    @patch.object(logic, "time")
    @patch.object(logic, "run_shell", return_value=_ok(0, stdout=""))
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_replaces_live_db(
        self, mock_cmd, mock_shell, mock_time, tmp_path: Path,
    ):
        source = self._make_db(tmp_path / "backup.db")
        data_dir = tmp_path / "data"
        (data_dir / "db").mkdir(parents=True)
        self._make_db(data_dir / "db" / "wheel_storage.db")
        install = tmp_path / "install"
        install.mkdir()

        msgs: list[str] = []
        logic.restore_database(source, data_dir, install, log=msgs.append)

        assert (data_dir / "db" / "wheel_storage.db").exists()
        assert any("wiederhergestellt" in m for m in msgs)

    @patch.object(logic, "time")
    @patch.object(logic, "run_shell", return_value=_ok(0, stdout=""))
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_creates_backup_of_old_db(
        self, mock_cmd, mock_shell, mock_time, tmp_path: Path,
    ):
        source = self._make_db(tmp_path / "backup.db")
        data_dir = tmp_path / "data"
        (data_dir / "db").mkdir(parents=True)
        (data_dir / "backups").mkdir(parents=True)
        self._make_db(data_dir / "db" / "wheel_storage.db")
        install = tmp_path / "install"
        install.mkdir()

        logic.restore_database(source, data_dir, install)

        backups = list((data_dir / "backups").glob("wheel_storage_*.db"))
        assert len(backups) == 1

    @patch.object(logic, "time")
    @patch.object(logic, "run_shell", return_value=_ok(0, stdout=""))
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_no_backup_when_no_live_db(
        self, mock_cmd, mock_shell, mock_time, tmp_path: Path,
    ):
        source = self._make_db(tmp_path / "backup.db")
        data_dir = tmp_path / "data"
        (data_dir / "db").mkdir(parents=True)
        install = tmp_path / "install"
        install.mkdir()

        logic.restore_database(source, data_dir, install)

        backups = list((data_dir / "backups").glob("*.db"))
        assert backups == []

    def test_invalid_source_raises_before_stopping_service(
        self, tmp_path: Path,
    ):
        bad = tmp_path / "bad.db"
        bad.write_bytes(b"this is not sqlite!!" + b"\x00" * 80)
        data_dir = tmp_path / "data"
        (data_dir / "db").mkdir(parents=True)
        install = tmp_path / "install"
        install.mkdir()

        with pytest.raises(ValueError, match="Header"):
            logic.restore_database(bad, data_dir, install)

    def test_missing_source_raises(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        (data_dir / "db").mkdir(parents=True)
        with pytest.raises(ValueError, match="nicht gefunden"):
            logic.restore_database(
                tmp_path / "nope.db", data_dir, tmp_path / "install")

    def test_wrong_schema_raises(self, tmp_path: Path):
        """A valid SQLite file with the wrong tables is rejected."""
        bad = tmp_path / "wrong_schema.db"
        con = sqlite3.connect(str(bad))
        con.execute(
            "CREATE TABLE unrelated (id INTEGER PRIMARY KEY, x TEXT)")
        con.commit()
        con.close()
        data_dir = tmp_path / "data"
        (data_dir / "db").mkdir(parents=True)
        with pytest.raises(ValueError, match="Pflicht-Tabellen"):
            logic.restore_database(
                bad, data_dir, tmp_path / "install")


# ────────────────────────────────────────────────
# VALIDATE PORT
# ────────────────────────────────────────────────
class TestValidatePort:
    def test_valid_port(self):
        assert logic.validate_port("5000") == 5000

    def test_boundary_low(self):
        assert logic.validate_port("1") == 1

    def test_boundary_high(self):
        assert logic.validate_port("65535") == 65535

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            logic.validate_port("0")

    def test_above_max_raises(self):
        with pytest.raises(ValueError):
            logic.validate_port("65536")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            logic.validate_port("abc")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            logic.validate_port("")

    def test_float_string_raises(self):
        with pytest.raises(ValueError):
            logic.validate_port("80.5")


# ────────────────────────────────────────────────
# RESOLVE DISPLAY NAME
# ────────────────────────────────────────────────
class TestResolveDisplayName:
    def test_returns_stripped_value(self):
        assert logic.resolve_display_name("  Mein App  ") == "Mein App"

    def test_empty_falls_back_to_default(self):
        assert logic.resolve_display_name("") == "Reifenmanager"

    def test_whitespace_only_falls_back(self):
        assert logic.resolve_display_name("   ") == "Reifenmanager"


# ────────────────────────────────────────────────
# UNINSTALL STEPS
# ────────────────────────────────────────────────
class TestStopService:
    @patch.object(logic, "time")
    @patch.object(logic, "run_shell", return_value=_ok(0, stdout=""))
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_stop_via_sc(self, mock_cmd, mock_shell, mock_time, tmp_path: Path):
        msgs: list[str] = []
        logic.stop_service(tmp_path / "install", log=msgs.append)
        assert "gestoppt" in msgs[0]

    @patch.object(logic, "time")
    @patch.object(logic, "run_shell", return_value=_ok(0, stdout=""))
    @patch.object(logic, "run_cmd", return_value=_ok(1))
    def test_fallback_to_nssm(self, mock_cmd, mock_shell, mock_time, tmp_path: Path):
        install = tmp_path / "install"
        install.mkdir()
        nssm = install / "nssm.exe"
        nssm.write_bytes(b"\x00")
        msgs: list[str] = []
        logic.stop_service(install, log=msgs.append)
        assert "NSSM" in msgs[0]

    @patch.object(logic, "time")
    @patch.object(logic, "run_shell", return_value=_ok(0, stdout=""))
    @patch.object(logic, "run_cmd", return_value=_ok(1))
    def test_not_running(self, mock_cmd, mock_shell, mock_time, tmp_path: Path):
        msgs: list[str] = []
        logic.stop_service(tmp_path / "empty", log=msgs.append)
        assert "nicht aktiv" in msgs[0] or "ℹ" in msgs[0]


class TestRemoveService:
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_remove_via_nssm(self, mock_run, tmp_path: Path):
        install = tmp_path / "install"
        install.mkdir()
        (install / "nssm.exe").write_bytes(b"\x00")
        msgs: list[str] = []
        logic.remove_service(install, log=msgs.append)
        assert "NSSM" in msgs[0]

    @patch.object(logic, "run_cmd")
    def test_fallback_to_sc(self, mock_run, tmp_path: Path):
        mock_run.side_effect = [_ok(1), _ok(0)]  # nssm fails, sc ok
        install = tmp_path / "install"
        install.mkdir()
        (install / "nssm.exe").write_bytes(b"\x00")
        msgs: list[str] = []
        logic.remove_service(install, log=msgs.append)
        assert "sc.exe" in msgs[0]

    @patch.object(logic, "run_cmd", return_value=_ok(1))
    def test_no_nssm_sc_fails(self, mock_run, tmp_path: Path):
        msgs: list[str] = []
        logic.remove_service(tmp_path / "empty", log=msgs.append)
        assert "ℹ" in msgs[0]


class TestRemoveScheduledTask:
    @patch.object(logic, "run_shell", return_value=_ok(0))
    def test_success(self, mock_run):
        msgs: list[str] = []
        logic.remove_scheduled_task(log=msgs.append)
        assert "entfernt" in msgs[0]

    @patch.object(logic, "run_shell", return_value=_ok(1))
    def test_not_found(self, mock_run):
        msgs: list[str] = []
        logic.remove_scheduled_task(log=msgs.append)
        assert "ℹ" in msgs[0]


class TestRemoveFirewallRules:
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_removes_rules(self, mock_run):
        msgs: list[str] = []
        logic.remove_firewall_rules(extra_port=9000, log=msgs.append)
        # 5 ports: 80, 443, 5000, 8080, 9000
        assert mock_run.call_count == 5
        assert any("entfernt" in m for m in msgs)

    @patch.object(logic, "run_cmd", return_value=_ok(1))
    def test_none_found(self, mock_run):
        msgs: list[str] = []
        logic.remove_firewall_rules(log=msgs.append)
        assert any("Keine" in m for m in msgs)


class TestRemoveInstallDir:
    def test_removes_files_and_dir(self, tmp_path: Path):
        install = tmp_path / "install"
        install.mkdir()
        (install / "app.exe").write_bytes(b"\x00")
        (install / "nssm.exe").write_bytes(b"\x00")
        sub = install / "sub"
        sub.mkdir()
        (sub / "f.txt").write_text("x")
        msgs: list[str] = []
        logic.remove_install_dir(install, log=msgs.append)
        assert not install.exists()
        assert any("Gelöscht" in m for m in msgs)

    def test_nonexistent_dir(self, tmp_path: Path):
        msgs: list[str] = []
        logic.remove_install_dir(tmp_path / "nope", log=msgs.append)
        assert "ℹ" in msgs[0]


class TestRemoveDataDir:
    def test_removes_data(self, tmp_path: Path):
        data = tmp_path / "data"
        data.mkdir()
        (data / "db").mkdir()
        (data / "db" / "wheel_storage.db").write_bytes(b"\x00")
        msgs: list[str] = []
        logic.remove_data_dir(data, log=msgs.append)
        assert not data.exists()
        assert "entfernt" in msgs[0]

    def test_nonexistent_dir(self, tmp_path: Path):
        msgs: list[str] = []
        logic.remove_data_dir(tmp_path / "nope", log=msgs.append)
        assert "ℹ" in msgs[0]


# ────────────────────────────────────────────────
# FULL INSTALL / UNINSTALL SEQUENCE
# ────────────────────────────────────────────────
class TestFullInstallSequence:
    """
    Simulate the entire install sequence end-to-end using real
    temp dirs and mocked subprocess calls.
    """

    @patch.object(logic, "run_shell", return_value=_ok(0))
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_install_happy_path(self, mock_cmd, mock_shell, tmp_path: Path):
        install = tmp_path / "install"
        data = tmp_path / "data"
        port = 5000
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "nssm.exe").write_bytes(b"NSSM")
        (payload / "TireStorageManager.exe").write_bytes(b"APP")
        (payload / "db").mkdir()
        (payload / "db" / "wheel_storage.db").write_bytes(b"SEED")

        msgs: list[str] = []
        log = msgs.append

        # Run every install step in order
        logic.create_directories(install, data, log=log)
        nssm = logic.deploy_nssm(payload / "nssm.exe", install, log=log)
        app_exe = logic.deploy_app_exe(
            payload / "TireStorageManager.exe", install, log=log)
        logic.seed_database(
            payload / "db" / "wheel_storage.db", data, log=log)
        logic.add_firewall_rule(port, log=log)
        logic.install_service(
            nssm, app_exe, data, port, install, log=log)
        logic.start_service(nssm, log=log)
        logic.create_update_task(log=log)

        # Verify filesystem state
        assert install.is_dir()
        assert (install / "nssm.exe").read_bytes() == b"NSSM"
        assert (install / "TireStorageManager.exe").read_bytes() == b"APP"
        assert (data / "db" / "wheel_storage.db").read_bytes() == b"SEED"
        assert (data / "backups").is_dir()
        assert (data / "logs").is_dir()

        # Verify subprocess calls happened
        # create_update_task uses run_cmd (list, no shell=True) since the
        # run_shell → run_cmd migration to fix schtasks quoting.
        assert mock_cmd.call_count > 0
        assert mock_shell.call_count == 0

    @patch.object(logic, "run_shell", return_value=_ok(0))
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_uninstall_happy_path(
        self, mock_cmd, mock_shell, tmp_path: Path,
    ):
        # Set up as if installed
        install = tmp_path / "install"
        data = tmp_path / "data"
        install.mkdir()
        (install / "nssm.exe").write_bytes(b"NSSM")
        (install / "TireStorageManager.exe").write_bytes(b"APP")
        data.mkdir()
        (data / "db").mkdir()
        (data / "db" / "wheel_storage.db").write_bytes(b"DB")

        msgs: list[str] = []
        log = msgs.append

        # Run every uninstall step
        logic.stop_service(install, log=log)
        logic.remove_service(install, log=log)
        logic.remove_scheduled_task(log=log)
        logic.remove_firewall_rules(extra_port=5000, log=log)
        logic.remove_install_dir(install, log=log)
        logic.remove_data_dir(data, log=log)

        # Everything gone
        assert not install.exists()
        assert not data.exists()
        assert mock_cmd.call_count > 0
        assert mock_shell.call_count >= 1

    @patch.object(logic, "run_shell", return_value=_ok(0))
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_uninstall_keep_data(
        self, mock_cmd, mock_shell, tmp_path: Path,
    ):
        install = tmp_path / "install"
        data = tmp_path / "data"
        install.mkdir()
        (install / "TireStorageManager.exe").write_bytes(b"APP")
        data.mkdir()
        (data / "db").mkdir()
        (data / "db" / "wheel_storage.db").write_bytes(b"KEEP")

        msgs: list[str] = []
        log = msgs.append

        logic.stop_service(install, log=log)
        logic.remove_service(install, log=log)
        logic.remove_scheduled_task(log=log)
        logic.remove_firewall_rules(log=log)
        logic.remove_install_dir(install, log=log)
        # Do NOT call remove_data_dir

        assert not install.exists()
        assert data.exists()
        assert (data / "db" / "wheel_storage.db").read_bytes() == b"KEEP"

    @patch.object(logic, "run_shell", return_value=_ok(0))
    @patch.object(logic, "run_cmd", return_value=_ok(0))
    def test_reinstall_after_keep_data_uses_existing_db(
        self, mock_cmd, mock_shell, tmp_path: Path,
    ):
        """Uninstall with keep_data=True then reinstall must reuse the
        existing database and must not overwrite it with the seed.

        Scenario:
          1. Install → seed DB written (simulated by writing b"USERDATA")
          2. Uninstall keeping data → install dir gone, data dir intact
          3. Reinstall → seed_database skips because DB already exists
          4. Service is registered pointing at the same data dir
          5. Data is intact — no data loss
        """
        install = tmp_path / "install"
        data = tmp_path / "data"
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "nssm.exe").write_bytes(b"NSSM")
        (payload / "TireStorageManager.exe").write_bytes(b"APP")
        (payload / "db").mkdir()
        (payload / "db" / "wheel_storage.db").write_bytes(b"SEED")
        port = 5000

        log: list[str] = []

        # ── Step 1: initial install ──────────────────────────────────
        logic.create_directories(install, data, log=log.append)
        nssm = logic.deploy_nssm(
            payload / "nssm.exe", install, log=log.append)
        app_exe = logic.deploy_app_exe(
            payload / "TireStorageManager.exe", install, log=log.append)
        logic.seed_database(
            payload / "db" / "wheel_storage.db", data, log=log.append)
        logic.add_firewall_rule(port, log=log.append)
        logic.install_service(
            nssm, app_exe, data, port, install, log=log.append)
        logic.start_service(nssm, log=log.append)
        logic.create_update_task(log=log.append)

        # Simulate user data written after install
        db_path = data / "db" / "wheel_storage.db"
        db_path.write_bytes(b"USERDATA")

        # ── Step 2: uninstall keeping data ───────────────────────────
        logic.stop_service(install, log=log.append)
        logic.remove_service(install, log=log.append)
        logic.remove_scheduled_task(log=log.append)
        logic.remove_firewall_rules(extra_port=port, log=log.append)
        logic.remove_install_dir(install, log=log.append)
        # keep_data: do NOT call remove_data_dir

        assert not install.exists(), "install dir must be gone"
        assert data.exists(), "data dir must survive keep_data uninstall"
        assert db_path.read_bytes() == b"USERDATA", (
            "user data must be intact after keep_data uninstall"
        )

        # ── Step 3: reinstall ────────────────────────────────────────
        install.mkdir()  # fresh install dir
        nssm2 = logic.deploy_nssm(
            payload / "nssm.exe", install, log=log.append)
        app_exe2 = logic.deploy_app_exe(
            payload / "TireStorageManager.exe", install, log=log.append)
        # seed_database must skip because DB already exists
        logic.seed_database(
            payload / "db" / "wheel_storage.db", data, log=log.append)
        logic.add_firewall_rule(port, log=log.append)
        logic.install_service(
            nssm2, app_exe2, data, port, install, log=log.append)
        logic.start_service(nssm2, log=log.append)
        logic.create_update_task(log=log.append)

        # ── Assertions ───────────────────────────────────────────────
        # Data must be untouched — seed must not overwrite user data.
        assert db_path.read_bytes() == b"USERDATA", (
            "reinstall must not overwrite existing user database"
        )
        # seed_database logged "existiert bereits"
        seed_msgs = [m for m in log if "existiert" in m]
        assert seed_msgs, (
            "seed_database must log that the DB already exists"
        )
        # Install dir recreated
        assert install.is_dir()
        assert (install / "nssm.exe").exists()
        assert (install / "TireStorageManager.exe").exists()


# ────────────────────────────────────────────────
# create_desktop_shortcut / remove_desktop_shortcut
# ────────────────────────────────────────────────
class TestDesktopShortcut:
    def test_creates_url_file(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("PUBLIC", str(tmp_path))
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        logic.create_desktop_shortcut(
            "http://192.168.1.10:5000/",
            display_name="Mein Reifen",
        )

        shortcut = desktop / "Mein Reifen.url"
        assert shortcut.exists()
        content = shortcut.read_text(encoding="utf-8")
        assert "[InternetShortcut]" in content
        assert "URL=http://192.168.1.10:5000/" in content

    def test_creates_url_file_default_name(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("PUBLIC", str(tmp_path))
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        logic.create_desktop_shortcut("http://localhost:5000/")

        shortcut = desktop / "Reifenmanager.url"
        assert shortcut.exists()

    def test_log_called(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("PUBLIC", str(tmp_path))
        (tmp_path / "Desktop").mkdir()
        msgs: list[str] = []
        logic.create_desktop_shortcut(
            "http://localhost:5000/", log=msgs.append
        )
        assert any("Desktop-Verknüpfung" in m for m in msgs)

    def test_removes_url_file(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("PUBLIC", str(tmp_path))
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        shortcut = desktop / "Mein Tool.url"
        shortcut.write_text("[InternetShortcut]\nURL=http://x/\n")

        logic.remove_desktop_shortcut("Mein Tool")

        assert not shortcut.exists()

    def test_remove_graceful_if_missing(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("PUBLIC", str(tmp_path))
        (tmp_path / "Desktop").mkdir()
        msgs: list[str] = []
        # Should not raise
        logic.remove_desktop_shortcut("NonExistent", log=msgs.append)
        assert any("Keine" in m or "nicht gefunden" in m for m in msgs)

    def test_remove_log_on_success(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("PUBLIC", str(tmp_path))
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        (desktop / "TestApp.url").write_text("[InternetShortcut]\nURL=x\n")
        msgs: list[str] = []
        logic.remove_desktop_shortcut("TestApp", log=msgs.append)
        assert any("entfernt" in m for m in msgs)
