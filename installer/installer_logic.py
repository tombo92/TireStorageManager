#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
installer_logic.py  –  Pure-logic helpers for the TSM Installer/Uninstaller.

No Tkinter imports here — everything is testable without a display.
All functions that touch the OS (subprocess, filesystem) are collected
here so they can be mocked in unit tests.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

# ========================================================
# CONSTANTS (duplicated from TSMInstaller for independence)
# ========================================================
APP_NAME = "TireStorageManager"
SERVICE_NAME = "TireStorageManager"


# ========================================================
# LOW-LEVEL HELPERS
# ========================================================
def ensure_dir(p: Path) -> None:
    """Create directory (and parents) if missing."""
    p.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess and return the result."""
    return subprocess.run(
        cmd, check=check, capture_output=True,
        encoding="utf-8", errors="replace", shell=False,
    )


def run_shell(cmd: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command string and return the result."""
    return subprocess.run(
        cmd, shell=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )


def copy_file(src: Path, dest: Path, overwrite: bool = False) -> bool:
    """Copy *src* → *dest*. Returns True on success, False if src missing."""
    if not src.exists():
        return False
    if dest.exists() and not overwrite:
        return True
    ensure_dir(dest.parent)
    shutil.copy2(src, dest)
    return True


# ========================================================
# INSTALL STEPS
# ========================================================
def create_directories(
    install_dir: Path,
    data_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Step 1 – create install + data sub-directories."""
    for d in [
        install_dir,
        data_dir,
        data_dir / "db",
        data_dir / "backups",
        data_dir / "logs",
    ]:
        ensure_dir(d)
        if log:
            log(f"   ✓ {d}")


def deploy_nssm(
    src: Path,
    install_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> Path:
    """Step 2 – copy nssm.exe into *install_dir*. Returns dest path."""
    target = install_dir / "nssm.exe"
    if not copy_file(src, target, overwrite=True):
        raise RuntimeError("nssm.exe nicht im Payload gefunden.")
    if log:
        log(f"   ✓ {target}")
    return target


def deploy_app_exe(
    src: Path,
    install_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> Path:
    """Step 3 – copy TireStorageManager.exe into *install_dir*.

    If the service is still running (reinstall scenario) the EXE will be
    locked on Windows.  We stop the service first so the file handle is
    released before attempting the copy.
    """
    target = install_dir / f"{APP_NAME}.exe"
    if target.exists():
        # Service may hold the file open – stop it before overwriting.
        stop_service(install_dir, log=log)
    if not copy_file(src, target, overwrite=True):
        raise RuntimeError(f"{APP_NAME}.exe nicht im Payload gefunden.")
    if log:
        log(f"   ✓ {target}")
    return target


def seed_database(
    seed_db: Path,
    data_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Step 4 – copy seed DB if the target doesn't exist yet."""
    db_path = data_dir / "db" / "wheel_storage.db"
    if not db_path.exists() and seed_db.exists():
        shutil.copy2(seed_db, db_path)
        if log:
            log("   ✓ Datenbank aus Vorlage erstellt.")
    elif db_path.exists():
        if log:
            log("   ✓ Datenbank existiert bereits.")
    else:
        if log:
            log("   ℹ Keine Vorlage – wird beim ersten Start angelegt.")


def add_firewall_rule(
    port: int,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Step 5 – add an inbound TCP firewall rule."""
    rule_name = f"{APP_NAME} TCP {port}"
    result = run_cmd([
        "netsh", "advfirewall", "firewall", "add", "rule",
        f"name={rule_name}", "dir=in", "action=allow",
        "protocol=TCP", f"localport={port}",
    ], check=False)
    if log:
        if result.returncode == 0:
            log(f"   ✓ Firewall-Regel '{rule_name}' erstellt.")
        else:
            log(f"   ℹ Regel existiert bereits oder Fehler: "
                f"{result.stderr.strip()}")


def install_service(
    nssm: Path,
    app_exe: Path,
    data_dir: Path,
    port: int,
    install_dir: Path,
    display_name: str = "Reifenmanager",
    secret_key: str = "",
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Step 6 – register the Windows Service via NSSM."""
    # Remove any existing service
    run_cmd([str(nssm), "stop", SERVICE_NAME], check=False)
    run_cmd([str(nssm), "remove", SERVICE_NAME, "confirm"], check=False)

    app_args = (
        f'--data-dir "{data_dir}" --host 0.0.0.0 --port {port}'
    )
    run_cmd([str(nssm), "install", SERVICE_NAME, str(app_exe), app_args],
            check=True)
    run_cmd([str(nssm), "set", SERVICE_NAME,
             "AppDirectory", str(install_dir)], check=True)
    run_cmd([str(nssm), "set", SERVICE_NAME,
             "DisplayName", display_name], check=True)
    run_cmd([str(nssm), "set", SERVICE_NAME,
             "Description",
             f"{display_name} – Webserver & Backup-Dienst"], check=True)
    run_cmd([str(nssm), "set", SERVICE_NAME,
             "Start", "SERVICE_AUTO_START"], check=True)

    log_dir = data_dir / "logs"
    run_cmd([str(nssm), "set", SERVICE_NAME,
             "AppStdout", str(log_dir / "service_stdout.log")], check=True)
    run_cmd([str(nssm), "set", SERVICE_NAME,
             "AppStderr", str(log_dir / "service_stderr.log")], check=True)

    env_extra = (
        f"TSM_DATA_DIR={data_dir}\n"
        f"TSM_PORT={port}\n"
        f"TSM_APP_NAME={display_name}"
    )
    if secret_key:
        env_extra += f"\nTSM_SECRET_KEY={secret_key}"
    run_cmd([str(nssm), "set", SERVICE_NAME,
             "AppEnvironmentExtra", env_extra], check=True)
    if log:
        log(f"   ✓ Dienst '{SERVICE_NAME}' installiert.")


def start_service(
    nssm: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Step 7 – start the service."""
    result = run_cmd(["sc.exe", "start", SERVICE_NAME], check=False)
    if result.returncode == 0:
        if log:
            log("   ✓ Dienst gestartet.")
    else:
        run_cmd([str(nssm), "start", SERVICE_NAME], check=False)
        if log:
            log("   ✓ Dienst gestartet (via NSSM).")


def validate_port(value: str) -> int:
    """Parse and validate a TCP port string.

    Returns the port as an int on success.
    Raises ValueError with a human-readable message on failure.
    """
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"'{value}' ist keine gültige Zahl."
        )
    if not 1 <= port <= 65535:
        raise ValueError(
            f"Port {port} liegt außerhalb des gültigen Bereichs "
            f"(1–65535)."
        )
    return port


def resolve_display_name(raw: str) -> str:
    """Return *raw* stripped, falling back to DEFAULT_DISPLAY_NAME."""
    return raw.strip() or "Reifenmanager"


def create_update_task(
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Step 8 – schedule a daily service restart at 03:00."""
    task_name = f"{APP_NAME}_DailyUpdate"
    # /TR must be wrapped in cmd /c so the shell evaluates the & chaining.
    # Without cmd /c, schtasks passes the literal & to sc.exe, which only
    # runs the stop command and never restarts the service.
    #
    # Use run_cmd (list, no shell=True) so Python does NOT apply any
    # additional shell quoting to the /TR value.  The /TR argument is
    # passed directly to schtasks.exe as a single token.
    tr_value = (
        f"cmd /c \"sc.exe stop {SERVICE_NAME} & "
        f"timeout /t 5 /nobreak >nul & "
        f"sc.exe start {SERVICE_NAME}\""
    )
    result = run_cmd([
        "schtasks", "/Create", "/F",
        "/TN", task_name,
        "/TR", tr_value,
        "/SC", "DAILY",
        "/ST", "03:00",
        "/RL", "HIGHEST",
    ], check=False)
    if log:
        if result.returncode == 0:
            log(f"   ✓ Täglicher Neustart-Task '{task_name}' um 03:00 erstellt.")
        else:
            log(f"   ℹ Task-Erstellung: {result.stderr.strip()}")


DB_FILENAME = "wheel_storage.db"
_SQLITE_MAGIC = b"SQLite format 3\x00"

# Minimum columns required per table for the application to function.
# Extra columns (from schema migrations) are accepted; missing required
# columns cause the restore to be rejected before touching the live DB.
_REQUIRED_SCHEMA: dict[str, set[str]] = {
    "wheel_sets": {
        "id", "customer_name", "license_plate",
        "car_type", "storage_position",
    },
    "settings": {
        "id", "backup_interval_minutes", "backup_copies",
    },
    "audit_log": {
        "id", "action",
    },
}


def validate_sqlite_file(path: Path) -> None:
    """Raise ValueError if *path* is not a usable SQLite3 database.

    Checks performed (in order):
      1. File exists.
      2. File size ≥ 16 bytes.
      3. SQLite3 magic header present (file is a real DB, not a CSV/ZIP).
      4. Required tables and their mandatory columns are present as a
         subset — extra tables/columns from older or newer schema versions
         are accepted; only missing required columns are rejected.
    """
    if not path.exists():
        raise ValueError(f"Datei nicht gefunden: {path}")
    if path.stat().st_size < 16:
        raise ValueError(
            f"Datei zu klein für eine SQLite-Datenbank: {path}")
    with open(path, "rb") as fh:
        header = fh.read(16)
    if header != _SQLITE_MAGIC:
        raise ValueError(
            f"'{path.name}' ist keine gültige SQLite3-Datenbank "
            f"(falscher Datei-Header)."
        )
    # Schema check — open read-only (uri mode) so we never modify the file.
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        raise ValueError(
            f"Datenbank konnte nicht geöffnet werden: {exc}"
        ) from exc
    try:
        cur = con.cursor()
        # Collect all table names present in the file.
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        existing_tables = {row[0] for row in cur.fetchall()}

        missing_tables = set(_REQUIRED_SCHEMA) - existing_tables
        if missing_tables:
            raise ValueError(
                f"Pflicht-Tabellen fehlen in der Datenbank: "
                f"{', '.join(sorted(missing_tables))}."
            )

        # For each required table, check the column subset.
        for table, required_cols in _REQUIRED_SCHEMA.items():
            cur.execute(f"PRAGMA table_info({table})")  # noqa: S608
            present_cols = {row[1] for row in cur.fetchall()}
            missing_cols = required_cols - present_cols
            if missing_cols:
                raise ValueError(
                    f"Pflicht-Spalten fehlen in Tabelle '{table}': "
                    f"{', '.join(sorted(missing_cols))}."
                )
    finally:
        con.close()


def restore_database(
    source_db: Path,
    data_dir: Path,
    install_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Replace the live database with *source_db* (e.g. a backup).

    Steps:
      1. Validate *source_db* is a readable SQLite3 file.
      2. Stop the Windows service so file handles are released.
      3. Back up the current DB (renamed with a timestamp suffix).
      4. Copy *source_db* to the live DB path.
      5. Restart the service.

    Raises ValueError for validation failures, RuntimeError for I/O
    failures so the caller can surface a clean message.
    """
    validate_sqlite_file(source_db)

    live_db = data_dir / "db" / DB_FILENAME
    backup_dir = data_dir / "backups"
    ensure_dir(backup_dir)

    # Stop service before touching the DB file.
    stop_service(install_dir, log=log)

    # Backup the current DB if it exists.
    if live_db.exists():
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"wheel_storage_{ts}.db"
        shutil.copy2(live_db, backup_path)
        if log:
            log(f"   ✓ Backup erstellt: {backup_path.name}")

    # Replace the live DB.
    ensure_dir(live_db.parent)
    shutil.copy2(source_db, live_db)
    if log:
        log(f"   ✓ Datenbank wiederhergestellt: {live_db}")

    # Restart the service.
    nssm = install_dir / "nssm.exe"
    start_service(nssm, log=log)


def create_desktop_shortcut(
    url: str,
    display_name: str = "Reifenmanager",
    icon_path: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Step 9 – create a .url Internet Shortcut on the All Users Desktop."""
    desktop = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
    shortcut = desktop / f"{display_name}.url"
    content = f"[InternetShortcut]\nURL={url}\n"
    if icon_path and icon_path.exists():
        content += f"IconFile={icon_path}\nIconIndex=0\n"
    shortcut.write_text(content, encoding="utf-8")
    if log:
        log(f"   ✓ Desktop-Verknüpfung erstellt: {shortcut}")


def remove_desktop_shortcut(
    display_name: str = "Reifenmanager",
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Uninstall – remove the .url shortcut from the All Users Desktop."""
    desktop = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
    for candidate in [display_name, "Reifenmanager", APP_NAME]:
        shortcut = desktop / f"{candidate}.url"
        if shortcut.exists():
            shortcut.unlink()
            if log:
                log(f"   ✓ Desktop-Verknüpfung entfernt: {shortcut.name}")
            return
    if log:
        log("   ℹ Keine Desktop-Verknüpfung gefunden.")


# ========================================================
# UNINSTALL STEPS
# ========================================================
def stop_service(
    install_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Uninstall step 1 – stop the running service and wait until the
    process has fully released its file handles."""
    nssm = install_dir / "nssm.exe"
    result = run_cmd(["sc.exe", "stop", SERVICE_NAME], check=False)
    if result.returncode == 0:
        if log:
            log(f"   ✓ Dienst '{SERVICE_NAME}' gestoppt.")
    elif nssm.exists():
        run_cmd([str(nssm), "stop", SERVICE_NAME], check=False)
        if log:
            log(f"   ✓ Dienst '{SERVICE_NAME}' gestoppt (via NSSM).")
    else:
        if log:
            log("   ℹ Dienst war nicht aktiv oder nicht gefunden.")

    # Wait up to 15 s for the EXE process to actually exit so file
    # handles are released before we try to delete the install directory.
    exe_name = f"{APP_NAME}.exe"
    for _ in range(15):
        try:
            result = run_shell(
                f'tasklist /FI "IMAGENAME eq {exe_name}" /NH'
            )
            stdout = (result.stdout or "").lower()
            if exe_name.lower() not in stdout:
                break
        except Exception:
            break  # can't check — assume it's gone and continue
        if log:
            log(f"   … warte auf Prozessende von {exe_name}")
        time.sleep(1)
    else:
        # Force-kill if still running after timeout
        try:
            run_shell(f'taskkill /F /IM "{exe_name}"')
        except Exception:
            pass
        time.sleep(1)
        if log:
            log(f"   ⚠ Prozess {exe_name} wurde zwangsbeendet.")


def remove_service(
    install_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Uninstall step 2 – delete the Windows Service."""
    nssm = install_dir / "nssm.exe"
    if nssm.exists():
        result = run_cmd(
            [str(nssm), "remove", SERVICE_NAME, "confirm"], check=False)
        if result.returncode == 0:
            if log:
                log(f"   ✓ Dienst '{SERVICE_NAME}' entfernt (via NSSM).")
            return
    result = run_cmd(["sc.exe", "delete", SERVICE_NAME], check=False)
    if log:
        if result.returncode == 0:
            log(f"   ✓ Dienst '{SERVICE_NAME}' entfernt (via sc.exe).")
        else:
            log("   ℹ Dienst konnte nicht entfernt werden oder existierte nicht.")


def remove_scheduled_task(
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Uninstall step 3 – delete the daily scheduled task."""
    task_name = f"{APP_NAME}_DailyUpdate"
    cmd = f'schtasks /Delete /F /TN "{task_name}"'
    result = run_shell(cmd)
    if log:
        if result.returncode == 0:
            log(f"   ✓ Task '{task_name}' entfernt.")
        else:
            log("   ℹ Task nicht gefunden oder bereits entfernt.")


def remove_firewall_rules(
    extra_port: Optional[int] = None,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Uninstall step 4 – remove firewall rules."""
    deleted = False
    ports = {5000, 8080, 80, 443}
    if extra_port:
        ports.add(extra_port)
    for port in sorted(ports):
        rule_name = f"{APP_NAME} TCP {port}"
        result = run_cmd([
            "netsh", "advfirewall", "firewall", "delete", "rule",
            f"name={rule_name}",
        ], check=False)
        if result.returncode == 0:
            if log:
                log(f"   ✓ Firewall-Regel '{rule_name}' entfernt.")
            deleted = True
    if not deleted and log:
        log("   ℹ Keine Firewall-Regeln gefunden.")


def _delete_with_retry(
    path: Path,
    retries: int = 5,
    delay: float = 1.5,
    log: Optional[Callable[[str], None]] = None,
) -> bool:
    """Try to delete *path* (file or directory) up to *retries* times.
    Falls back to scheduling deletion on next reboot via MoveFileEx
    if the file is still locked after all retries."""
    for attempt in range(retries):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return True
        except OSError:
            if attempt < retries - 1:
                time.sleep(delay)

    # Last resort: schedule deletion on next Windows reboot
    try:
        import ctypes
        MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
        ok = ctypes.windll.kernel32.MoveFileExW(  # type: ignore[attr-defined]
            str(path), None, MOVEFILE_DELAY_UNTIL_REBOOT
        )
        if ok and log:
            log(f"   ⚠ Wird beim nächsten Neustart gelöscht: {path.name}")
        elif log:
            log(f"   ✗ Konnte nicht gelöscht werden: {path.name}")
    except Exception:
        if log:
            log(f"   ✗ Konnte nicht gelöscht werden: {path.name}")
    return False


def remove_install_dir(
    install_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Uninstall step 5 – delete install directory contents."""
    if not install_dir.exists():
        if log:
            log(f"   ℹ Verzeichnis existiert nicht: {install_dir}")
        return

    all_ok = True
    for item in list(install_dir.iterdir()):
        ok = _delete_with_retry(item, log=log)
        if ok and log:
            log(f"   ✓ Gelöscht: {item.name}")
        else:
            all_ok = False

    if all_ok:
        try:
            install_dir.rmdir()
            if log:
                log(f"   ✓ Verzeichnis entfernt: {install_dir}")
        except OSError:
            _delete_with_retry(install_dir, log=log)


def remove_data_dir(
    data_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Uninstall step 6 – delete data directory entirely."""
    if not data_dir.exists():
        if log:
            log(f"   ℹ Verzeichnis existiert nicht: {data_dir}")
        return
    ok = _delete_with_retry(data_dir, log=log)
    if ok and log:
        log(f"   ✓ Datenverzeichnis entfernt: {data_dir}")
    elif log:
        log(f"   ⚠ Bitte manuell entfernen: {data_dir}")
