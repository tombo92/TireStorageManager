#!/usr/bin/env python
"""
installer_logic.py  –  Pure-logic helpers for the TSM Installer/Uninstaller.

No Tkinter imports here — everything is testable without a display.
All functions that touch the OS (subprocess, filesystem) are collected
here so they can be mocked in unit tests.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

# ========================================================
# CONSTANTS (duplicated from TSMInstaller for independence)
# ========================================================
APP_NAME = "TireStorageManager"
SERVICE_NAME = "TireStorageManager"

# GitHub release coordinates — can be overridden via env vars
_GH_OWNER = os.environ.get("TSM_GH_OWNER", "tombo92")
_GH_REPO = os.environ.get("TSM_GH_REPO", "TireStorageManager")
_GH_RELEASES_URL = (
    f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/releases/latest"
)
_HTTP_TIMEOUT = 20
_INSTALLER_ASSET_NAME = "TSM-Installer.exe"
_CHANGELOG_RAW_URL = (
    f"https://raw.githubusercontent.com/{_GH_OWNER}/{_GH_REPO}/master/CHANGELOG.md"
)


# ========================================================
# UPDATE CHECK (SSL-safe, corporate-network aware)
# ========================================================
def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context that trusts the OS certificate store.

    On Windows this includes enterprise root CAs deployed via Group Policy,
    which fixes SSL_CERTIFICATE_VERIFY_FAILED in managed/corporate networks.
    Certificate verification is never disabled.
    """
    ctx = ssl.create_default_context()
    if os.name == "nt":
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    return ctx


def _ver_tuple(v: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple, ignoring pre-release suffixes."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (0, 0, 0)


def _fetch_changelog_section(remote_version: str) -> str | None:
    """Fetch CHANGELOG.md and return the section body for *remote_version*.

    Returns the text between the ``## [remote_version]`` header and the
    next ``## [`` header (both excluded), or ``None`` if the section is
    absent, empty, or the fetch fails.
    """
    try:
        req = urllib.request.Request(
            _CHANGELOG_RAW_URL,
            headers={"User-Agent": "TSM-Installer/1.0"},
        )
        with urllib.request.urlopen(
            req, timeout=_HTTP_TIMEOUT, context=_ssl_context()
        ) as resp:
            text = resp.read().decode("utf-8")
    except Exception:
        return None

    pattern = (
        r"##\s*\[" + re.escape(remote_version) + r"\][^\n]*\n"
        r"(.*?)"
        r"(?=\n##\s*\[|\Z)"
    )
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return None
    section = m.group(1).strip()
    return section or None


def fetch_update_info(current_version: str) -> dict:
    """Check GitHub Releases for a version newer than *current_version*.

    Returns a dict with keys:
        update_available (bool), current_version (str),
        remote_version (str | None), release_notes (str | None),
        changelog_section (str | None), release_url (str | None),
        installer_url (str | None).

    Never raises — network / SSL errors are swallowed and reflected as
    ``update_available=False``.
    """
    result: dict = {
        "update_available": False,
        "current_version": current_version,
        "remote_version": None,
        "release_notes": None,
        "changelog_section": None,
        "release_url": None,
        "installer_url": None,
    }
    try:
        ts = int(time.time())
        url = f"{_GH_RELEASES_URL}?ts={ts}"
        headers = {
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "TSM-Installer/1.0",
            "Accept": "application/vnd.github+json",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(
            req, timeout=_HTTP_TIMEOUT, context=_ssl_context()
        ) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return result

    tag = release.get("tag_name", "")
    remote_ver = tag.lstrip("v")
    result["remote_version"] = remote_ver or None
    result["release_notes"] = release.get("body") or None
    result["release_url"] = release.get("html_url") or None

    for asset in release.get("assets", []):
        if asset.get("name", "").lower() == _INSTALLER_ASSET_NAME.lower():
            result["installer_url"] = asset.get("browser_download_url")
            break

    if remote_ver and _ver_tuple(remote_ver) > _ver_tuple(current_version):
        result["update_available"] = True

    result["changelog_section"] = (
        _fetch_changelog_section(remote_ver) if remote_ver else None
    )

    return result


def download_file(
    url: str,
    dest: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> bool:
    """Download *url* to *dest*, calling *on_progress(received, total)* per chunk.

    Returns True on success.  Never raises.
    """
    headers = {
        "Cache-Control": "no-cache",
        "User-Agent": "TSM-Installer/1.0",
        "Accept": "application/octet-stream",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(
            req, timeout=120, context=_ssl_context()
        ) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            received = 0
            ensure_dir(dest.parent)
            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
                    if on_progress:
                        on_progress(received, total)
        return True
    except Exception:
        return False


# ========================================================
# LOW-LEVEL HELPERS
# ========================================================
def ensure_dir(p: Path) -> None:
    """Create directory (and parents) if missing."""
    p.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess and return result."""
    return subprocess.run(
        cmd, check=check, capture_output=True,
        encoding="utf-8", errors="replace", shell=False,
    )


def run_shell(cmd: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command string and return the result."""
    return subprocess.run(
        cmd, shell=True, capture_output=True,
        encoding="utf-8", errors="replace", check=check,
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
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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


def pre_upgrade_backup(
    data_dir: Path,
    log: Callable[[str], None] | None = None,
) -> Path | None:
    """Create a safety backup of the existing DB before an upgrade.

    Returns the backup path if a backup was created, or ``None`` if no
    existing DB was found (fresh install — nothing to protect).

    The backup is named ``pre_upgrade_<timestamp>.db`` and stored in the
    data directory's ``backups/`` folder.  This is distinct from the
    regular daily backups and is never rotated — the user can always
    revert to the exact state before the upgrade.
    """
    db_path = data_dir / "db" / "wheel_storage.db"
    if not db_path.exists():
        if log:
            log("   ℹ Keine bestehende Datenbank — kein Upgrade-Backup nötig.")
        return None

    backup_dir = data_dir / "backups"
    ensure_dir(backup_dir)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"pre_upgrade_{ts}.db"
    shutil.copy2(db_path, backup_path)
    if log:
        log(f"   ✓ Upgrade-Sicherung erstellt: {backup_path.name}")
        log(f"     ({db_path.stat().st_size / 1024:.0f} KB)")
    return backup_path


def seed_database(
    seed_db: Path,
    data_dir: Path,
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"'{value}' ist keine gültige Zahl."
        ) from exc
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
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
    icon_path: Path | None = None,
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
def service_exists() -> bool:
    """Return True if the Windows Service is currently registered.

    Uses ``sc.exe query`` which exits 0 when the service exists
    (regardless of whether it is running or stopped) and non-zero when
    the service is not registered at all.
    """
    result = run_cmd(
        ["sc.exe", "query", SERVICE_NAME], check=False)
    return result.returncode == 0


def stop_service(
    install_dir: Path,
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
    extra_port: int | None = None,
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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
    log: Callable[[str], None] | None = None,
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


# ========================================================
# DIAGNOSTIC TOOL (hidden dev panel – triggered by '###')
# ========================================================
def diagnose(
    install_dir: Path,
    data_dir: Path,
) -> list[dict]:
    """Collect diagnostic information about a TSM installation.

    Returns a list of check results, each a dict with:
        label (str): human-readable check name
        status (str): 'ok', 'warn', 'error'
        detail (str): human-readable detail text

    Designed for the hidden '###' diagnostic panel in the installer GUI.
    All checks are read-only and safe.
    """
    checks: list[dict] = []

    # 1. Service status
    svc = _diag_service_status()
    checks.append(svc)

    # 2. Service config (NSSM AppParameters, AppEnvironmentExtra)
    nssm_path = install_dir / "nssm.exe"
    checks.extend(_diag_nssm_config(nssm_path))

    # 3. Install directory
    checks.append(_diag_dir_exists("Install-Verzeichnis", install_dir))
    app_exe = install_dir / f"{APP_NAME}.exe"
    checks.append(_diag_file_exists("TireStorageManager.exe", app_exe))
    checks.append(_diag_file_exists("nssm.exe", nssm_path))

    # 4. Data directory
    checks.append(_diag_dir_exists("Daten-Verzeichnis", data_dir))
    db_path = data_dir / "db" / "wheel_storage.db"
    checks.append(_diag_db_file(db_path))

    # 5. Log directory & recent log entries
    log_dir = data_dir / "logs"
    checks.append(_diag_dir_exists("Log-Verzeichnis", log_dir))
    checks.extend(_diag_recent_logs(log_dir))

    # 6. Backup directory
    backup_dir = data_dir / "backups"
    checks.append(_diag_backup_dir(backup_dir))

    # 7. Port check
    checks.extend(_diag_port_listening(data_dir))

    # 8. Scheduled task
    checks.append(_diag_scheduled_task())

    return checks


def _diag_service_status() -> dict:
    """Check Windows service state via sc.exe."""
    try:
        r = run_cmd(["sc.exe", "query", SERVICE_NAME], check=False)
        out = r.stdout
        if "RUNNING" in out:
            return {"label": "Dienst-Status", "status": "ok",
                    "detail": "Dienst läuft (RUNNING)"}
        if "STOPPED" in out:
            return {"label": "Dienst-Status", "status": "error",
                    "detail": "Dienst ist gestoppt (STOPPED)"}
        if "STOP_PENDING" in out:
            return {"label": "Dienst-Status", "status": "warn",
                    "detail": "Dienst stoppt gerade (STOP_PENDING)"}
        if "START_PENDING" in out:
            return {"label": "Dienst-Status", "status": "warn",
                    "detail": "Dienst startet gerade (START_PENDING)"}
        return {"label": "Dienst-Status", "status": "warn",
                "detail": f"Unbekannter Status:\n{out.strip()[:200]}"}
    except Exception as e:
        return {"label": "Dienst-Status", "status": "error",
                "detail": f"Fehler: {e}"}


def _diag_nssm_config(nssm: Path) -> list[dict]:
    """Read NSSM service parameters to verify --data-dir is correct."""
    results = []
    if not nssm.exists():
        results.append({"label": "NSSM Konfiguration", "status": "error",
                        "detail": f"nssm.exe nicht gefunden: {nssm}"})
        return results

    # AppParameters (the command-line args passed to the EXE)
    try:
        r = run_cmd([str(nssm), "get", SERVICE_NAME, "AppParameters"],
                    check=False)
        params = r.stdout.strip()
        if "--data-dir" in params:
            results.append({"label": "NSSM AppParameters",
                            "status": "ok",
                            "detail": params})
        else:
            results.append({"label": "NSSM AppParameters",
                            "status": "warn",
                            "detail": f"--data-dir fehlt!\n{params}"})
    except Exception as e:
        results.append({"label": "NSSM AppParameters", "status": "error",
                        "detail": str(e)})

    # AppEnvironmentExtra (env vars passed to the service)
    try:
        r = run_cmd([str(nssm), "get", SERVICE_NAME,
                     "AppEnvironmentExtra"], check=False)
        env = r.stdout.strip()
        if "TSM_DATA_DIR" in env:
            results.append({"label": "NSSM Umgebungsvariablen",
                            "status": "ok", "detail": env})
        else:
            results.append({"label": "NSSM Umgebungsvariablen",
                            "status": "warn",
                            "detail": f"TSM_DATA_DIR fehlt!\n{env}"})
    except Exception as e:
        results.append({"label": "NSSM Umgebungsvariablen",
                        "status": "error", "detail": str(e)})

    return results


def _diag_dir_exists(label: str, path: Path) -> dict:
    """Check if a directory exists."""
    if path.exists() and path.is_dir():
        return {"label": label, "status": "ok",
                "detail": str(path)}
    return {"label": label, "status": "error",
            "detail": f"Nicht gefunden: {path}"}


def _diag_file_exists(label: str, path: Path) -> dict:
    """Check if a file exists and report its size."""
    if path.exists() and path.is_file():
        size_mb = path.stat().st_size / (1024 * 1024)
        return {"label": label, "status": "ok",
                "detail": f"{path.name} ({size_mb:.1f} MB)"}
    return {"label": label, "status": "error",
            "detail": f"Nicht gefunden: {path}"}


def _diag_db_file(db_path: Path) -> dict:
    """Check DB file exists, has data, and key tables are present."""
    if not db_path.exists():
        return {"label": "Datenbank", "status": "error",
                "detail": f"Nicht gefunden: {db_path}"}
    size_kb = db_path.stat().st_size / 1024
    if size_kb < 1:
        return {"label": "Datenbank", "status": "error",
                "detail": f"Leer oder beschädigt ({size_kb:.1f} KB)"}
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        ws_count = 0
        if "wheel_sets" in tables:
            cur.execute("SELECT COUNT(*) FROM wheel_sets")
            ws_count = cur.fetchone()[0]
        settings_count = 0
        if "settings" in tables:
            cur.execute("SELECT COUNT(*) FROM settings")
            settings_count = cur.fetchone()[0]
        conn.close()
        expected = {"wheel_sets", "settings", "audit_log"}
        missing = expected - tables
        if missing:
            return {"label": "Datenbank", "status": "warn",
                    "detail": f"{size_kb:.0f} KB, "
                              f"fehlende Tabellen: {', '.join(missing)}, "
                              f"{ws_count} Radsätze"}
        return {"label": "Datenbank", "status": "ok",
                "detail": f"{size_kb:.0f} KB, "
                          f"{ws_count} Radsätze, "
                          f"Settings: {'✓' if settings_count else '✗'}, "
                          f"Tabellen: {', '.join(sorted(tables))}"}
    except Exception as e:
        return {"label": "Datenbank", "status": "error",
                "detail": f"{size_kb:.0f} KB, Lesefehler: {e}"}


def _diag_recent_logs(log_dir: Path) -> list[dict]:
    """Check for recent log files and report last few lines."""
    results = []
    if not log_dir.exists():
        return results

    for name in ("tsm.log", "service_stderr.log"):
        path = log_dir / name
        if not path.exists():
            results.append({"label": f"Log: {name}", "status": "warn",
                            "detail": "Datei nicht vorhanden"})
            continue
        try:
            size_kb = path.stat().st_size / 1024
            # Read last 5 lines
            lines = path.read_text(encoding="utf-8", errors="replace"
                                   ).splitlines()
            tail = lines[-5:] if len(lines) > 5 else lines
            has_error = any("error" in ln.lower() or "traceback" in ln.lower()
                           for ln in tail)
            status = "warn" if has_error else "ok"
            detail = (f"{size_kb:.0f} KB, {len(lines)} Zeilen\n"
                      f"Letzte Einträge:\n" + "\n".join(tail))
            results.append({"label": f"Log: {name}", "status": status,
                            "detail": detail})
        except Exception as e:
            results.append({"label": f"Log: {name}", "status": "error",
                            "detail": str(e)})
    return results


def _diag_backup_dir(backup_dir: Path) -> dict:
    """Check backup directory for pre-upgrade and regular backups."""
    if not backup_dir.exists():
        return {"label": "Backups", "status": "warn",
                "detail": f"Verzeichnis nicht gefunden: {backup_dir}"}
    files = list(backup_dir.iterdir())
    db_files = [f for f in files if f.suffix == ".db"]
    pre_upgrade = [f for f in db_files if f.name.startswith("pre_upgrade_")]
    regular = [f for f in db_files
               if f.name.startswith("wheel_storage_")]
    return {"label": "Backups", "status": "ok",
            "detail": f"{len(files)} Dateien gesamt, "
                      f"{len(pre_upgrade)} Upgrade-Sicherungen, "
                      f"{len(regular)} reguläre DB-Backups"}


def _diag_port_listening(data_dir: Path) -> list[dict]:
    """Check if the configured port is responding."""
    results = []
    # Try to determine port from NSSM or default
    port = 5000
    try:
        r = run_cmd(["sc.exe", "qc", SERVICE_NAME], check=False)
        import re as _re
        m = _re.search(r"--port\s+(\d+)", r.stdout)
        if m:
            port = int(m.group(1))
    except Exception:
        pass

    import socket as _sock
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("127.0.0.1", port))
        s.close()
        results.append({"label": f"Port {port}", "status": "ok",
                        "detail": f"Port {port} antwortet (TCP-Verbindung OK)"})
    except Exception:
        results.append({"label": f"Port {port}", "status": "error",
                        "detail": f"Port {port} antwortet nicht — "
                                  f"Dienst läuft möglicherweise nicht"})
    return results


def _diag_scheduled_task() -> dict:
    """Check if the daily restart task exists."""
    try:
        r = run_cmd(
            ["schtasks", "/Query", "/TN",
             f"{APP_NAME}_DailyUpdate", "/FO", "LIST"],
            check=False)
        if r.returncode == 0:
            return {"label": "Geplante Aufgabe", "status": "ok",
                    "detail": f"{APP_NAME}_DailyUpdate vorhanden"}
        return {"label": "Geplante Aufgabe", "status": "warn",
                "detail": "Aufgabe nicht gefunden"}
    except Exception as e:
        return {"label": "Geplante Aufgabe", "status": "error",
                "detail": str(e)}
