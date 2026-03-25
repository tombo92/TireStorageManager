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
import subprocess
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
        cmd, check=check, capture_output=True, text=True, shell=False,
    )


def run_shell(cmd: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command string and return the result."""
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
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
    """Step 3 – copy TireStorageManager.exe into *install_dir*."""
    target = install_dir / f"{APP_NAME}.exe"
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


def create_update_task(
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Step 8 – schedule a daily service restart at 03:00."""
    task_name = f"{APP_NAME}_DailyUpdate"
    cmd = (
        f'schtasks /Create /F /TN "{task_name}" '
        f'/TR "sc.exe stop {SERVICE_NAME} & '
        f'timeout /t 5 & '
        f'sc.exe start {SERVICE_NAME}" '
        f'/SC DAILY /ST 03:00 /RL HIGHEST'
    )
    result = run_shell(cmd)
    if log:
        if result.returncode == 0:
            log(f"   ✓ Täglicher Neustart-Task '{task_name}' um 03:00 erstellt.")
        else:
            log(f"   ℹ Task-Erstellung: {result.stderr.strip()}")


def create_desktop_shortcut(
    url: str,
    display_name: str = "Reifenmanager",
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Step 9 – create a .url Internet Shortcut on the All Users Desktop."""
    desktop = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
    shortcut = desktop / f"{display_name}.url"
    shortcut.write_text(
        f"[InternetShortcut]\nURL={url}\n", encoding="utf-8"
    )
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
    """Uninstall step 1 – stop the running service."""
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


def remove_install_dir(
    install_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Uninstall step 5 – delete install directory contents."""
    if not install_dir.exists():
        if log:
            log(f"   ℹ Verzeichnis existiert nicht: {install_dir}")
        return

    errors: list[str] = []
    for item in install_dir.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            if log:
                log(f"   ✓ Gelöscht: {item.name}")
        except OSError as e:
            errors.append(str(e))
            if log:
                log(f"   ⚠ Konnte nicht löschen: {item.name} ({e})")

    try:
        install_dir.rmdir()
        if log:
            log(f"   ✓ Verzeichnis entfernt: {install_dir}")
    except OSError:
        if log:
            if errors:
                log("   ⚠ Verzeichnis nicht leer, bitte manuell löschen.")
            else:
                log("   ℹ Verzeichnis konnte nicht entfernt werden.")


def remove_data_dir(
    data_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Uninstall step 6 – delete data directory entirely."""
    if not data_dir.exists():
        if log:
            log(f"   ℹ Verzeichnis existiert nicht: {data_dir}")
        return
    try:
        shutil.rmtree(data_dir)
        if log:
            log(f"   ✓ Datenverzeichnis entfernt: {data_dir}")
    except OSError as e:
        if log:
            log(f"   ⚠ Konnte Datenverzeichnis nicht vollständig löschen: {e}")
            log(f"     Bitte manuell entfernen: {data_dir}")
