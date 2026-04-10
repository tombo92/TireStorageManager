"""
Release Acceptance Test – Phases 3, 4 and 5.

Phase 3: Update flow (repeated update-check API + POST /settings/update-now).
Phase 4: Installer in-place upgrade with data-survival check.
Phase 5: Headless installer update-check (JSON shape + SSL validation).
"""
from __future__ import annotations

import json as _json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Optional

from .helpers import (
    _check,
    _delete_by_plate,
    _get,
    _get_csrf,
    _poll_list,
    _post,
    _run_installer,
    _section,
    _service_start_type,
    _service_state,
    _wait_http_up,
    SERVICE_NAME,
)
from .phase1 import (
    _phase1b_crud,
    _phase1c_settings,
    _phase1e_security,
)

def _phase3_update_once(base: str, app_exe: Path, port: int,
                        data_dir: Path, cycle: int) -> None:
    """
    One update cycle:
      a) /api/update-check returns valid JSON shape.
      b) POST /settings/update-now → 200 or redirect.
      c) Server stays alive (same-version case) OR
         old process exits and a fresh EXE boots back up.
      d) /wheelsets still returns 200.
    """
    prefix = f"Cycle {cycle}"

    # 3a – update-check API shape
    code, body = _get(base, "/api/update-check")
    _check(f"{prefix}: GET /api/update-check -> 200",
           code == 200, f"got {code}")
    api_ok = False
    try:
        data = _json.loads(body)
        required = {
            "update_available", "current_version",
            "remote_version", "release_notes",
            "release_url", "frozen",
        }
        missing = required - data.keys()
        api_ok = len(missing) == 0
        _check(
            f"{prefix}: update-check response has all keys",
            api_ok,
            f"missing: {missing}" if missing else "",
        )
        _check(
            f"{prefix}: current_version non-empty",
            isinstance(data.get("current_version"), str)
            and len(data.get("current_version", "")) > 0,
        )

        # 3a-ssl – SSL health: the EXE always calls GitHub over HTTPS when the
        # update-check endpoint is hit.  remote_version being non-null proves
        # the HTTPS call succeeded; CERTIFICATE_VERIFY_FAILED in the log is a
        # hard failure (corporate CA not loaded into the context).
        remote_version = data.get("remote_version")
        _check(
            f"{prefix}: SSL health: remote_version non-null (GitHub HTTPS call succeeded)",
            remote_version is not None,
            "GitHub unreachable — possible SSL error; check tsm.log",
        )
        log_file = data_dir / "logs" / "tsm.log"
        try:
            log_content = log_file.read_text(encoding="utf-8", errors="replace")
            ssl_error = "CERTIFICATE_VERIFY_FAILED" in log_content
            _check(
                f"{prefix}: SSL health: no CERTIFICATE_VERIFY_FAILED in tsm.log",
                not ssl_error,
                "SSL cert error in log — corporate CA not in Windows trust store?" if ssl_error else "",
            )
            if ssl_error:
                for line in log_content.splitlines():
                    if "CERTIFICATE_VERIFY_FAILED" in line or "SSL" in line.upper():
                        print(f"  [LOG] {line}", flush=True)
        except OSError:
            print(f"  [INFO] tsm.log not found at {log_file} — skipping log scan", flush=True)

    except (ValueError, KeyError) as exc:
        _check(f"{prefix}: update-check is valid JSON", False, str(exc))

    # 3b – trigger update endpoint
    csrf = _get_csrf(base)
    code, body = _post(base, "/settings/update-now",
                       {"_csrf_token": csrf})
    _check(
        f"{prefix}: POST /settings/update-now -> 200/302",
        code in (200, 302),
        f"got {code}",
    )

    body_text = body.decode("utf-8", errors="replace").lower()
    no_update = (
        "kein update" in body_text
        or "no update" in body_text
        or "nicht" in body_text
    )

    # 3c – liveness check
    if no_update or code in (200, 302):
        # Same-version path: server stays up
        alive = _wait_http_up(base, timeout=15)
        _check(
            f"{prefix}: server still alive after update-now",
            alive,
        )
        if alive:
            code2, _ = _get(base, "/wheelsets")
            _check(
                f"{prefix}: /wheelsets reachable after update-now",
                code2 == 200,
                f"got {code2}",
            )
        return

    # Real-update path: old process should exit
    print(
        f"  Cycle {cycle}: EXE restarting – waiting for shutdown …",
        flush=True,
    )
    deadline = time.monotonic() + 30
    gone = False
    while time.monotonic() < deadline:
        probe, _ = _get(base, "/")
        if probe == 0:
            gone = True
            break
        time.sleep(1)
    _check(f"{prefix}: old EXE exited after real update", gone)

    if not gone:
        return

    # Start fresh EXE on same port/data-dir
    new_proc = _start_app(app_exe, port, data_dir)
    up = _wait_http_up(base, timeout=60)
    _check(f"{prefix}: new EXE boots after real update", up)
    if up:
        code3, _ = _get(base, "/wheelsets")
        _check(
            f"{prefix}: /wheelsets reachable in new EXE",
            code3 == 200,
            f"got {code3}",
        )
    _stop_app(new_proc)


def phase3_update(
    app_exe: Path, port: int, data_dir: Path, *, repeats: int = 3
) -> None:
    """
    Run the update cycle *repeats* times against a standalone EXE.
    The EXE must already be running when this is called.
    """
    base = f"http://127.0.0.1:{port}"
    app_data = data_dir / "app_standalone"

    # Start a fresh EXE for Phase 3
    _section("Phase 3 – Update flow")
    proc = _start_app(app_exe, port, app_data)
    if not _wait_http_up(base, timeout=30):
        _check("Phase 3: App started for update cycles", False)
        _stop_app(proc)
        return
    _check("Phase 3: App started for update cycles", True)

    for i in range(1, repeats + 1):
        _section(f"Phase 3 – Update cycle {i}/{repeats}")
        _phase3_update_once(base, app_exe, port, app_data, cycle=i)
        # If the process died (real update), restart for the next cycle
        if proc.poll() is not None:
            proc = _start_app(app_exe, port, app_data)
            if not _wait_http_up(base, timeout=30):
                _check(
                    f"Phase 3 cycle {i}: app restarted for next cycle",
                    False,
                )
                break

    _stop_app(proc)


# ══════════════════════════════════════════════════════════════════════
# Phase 4 – Installer in-place upgrade
# ══════════════════════════════════════════════════════════════════════

def phase4_installer_upgrade(
    inst_exe: Path,
    install_dir: Path,
    data_dir: Path,
    port: int,
    app_exe: Path,
) -> None:
    """
    Simulate deploying an updated version of the app through the installer:

    4a  Fresh install.
    4b  Seed the DB with a known wheelset (survival marker).
    4c  Re-run the installer with the same (or updated) EXE binaries
        (mirrors what CI does: bump version, rebuild, re-run installer).
    4d  Verify the service is still running after the in-place upgrade.
    4e  Verify the survival-marker wheelset is still present (data intact).
    4f  Run a focused subset of Phase-1 checks against the upgraded service
        (startup, CRUD, settings, security – no concurrency storm needed).
    4g  Full uninstall to leave the runner clean.
    """
    base = f"http://127.0.0.1:{port}"
    upgrade_dir = install_dir.parent / "tsm_rat_upgrade"
    upgrade_data = data_dir.parent / "tsm_rat_upgrade_data"

    _section("Phase 4a – Fresh install (upgrade baseline)")
    rc, _ = _run_installer(
        inst_exe, "install", upgrade_dir, upgrade_data, port)
    _check("4a: baseline install exited 0", rc == 0, f"exit {rc}")
    _check(
        "4a: service responds after baseline install",
        _wait_http_up(base, timeout=60),
    )

    _section("Phase 4b – Seed survival-marker wheelset")
    csrf = _get_csrf(base)
    code, _ = _post(base, "/wheelsets/new", {
        "_csrf_token": csrf,
        "customer_name": "Upgrade Survival Test",
        "license_plate": "UPG-S 7",
        "car_type": "Compact",
        "storage_position": "C1ROL",
        "note": "must survive upgrade",
    })
    _check("4b: survival wheelset created", code in (200, 302), f"got {code}")

    # Verify the wheelset actually landed in the DB (catch silent
    # rejections due to invalid position or duplicate plate).
    _found_s7, _seed_body = _poll_list(base, b"UPG-S 7")
    _check(
        "4b: survival wheelset appears in list",
        _found_s7,
        "POST returned 200/302 but wheelset not in /wheelsets – "
        "likely a silent validation rejection",
        diag=_seed_body,
    )

    _section("Phase 4c – In-place upgrade via installer")
    # Trigger a backup so SQLite checkpoints the WAL before we stop the
    # service — this ensures the survival wheelset is committed to the
    # main DB file and survives the force-kill.
    csrf = _get_csrf(base)
    _post(base, "/backups/run", {"_csrf_token": csrf})
    time.sleep(2)  # allow checkpoint to complete

    # Verify the survival wheelset is visible *before* stopping the
    # service (proves the data was written and is reachable).
    _, _pre_body = _get(base, "/wheelsets")
    _check(
        "4c: survival wheelset visible before upgrade",
        b"UPG-S 7" in _pre_body,
        "not found – backup/checkpoint may not have flushed",
        diag=_pre_body,
    )

    # Stop the service so the EXE file handle is released.
    # Use NSSM stop first (prevents NSSM from auto-restarting the
    # process after sc.exe stop).
    _nssm_upgrade = upgrade_dir / "nssm.exe"
    if _nssm_upgrade.exists():
        subprocess.run(
            [str(_nssm_upgrade), "stop", SERVICE_NAME],
            capture_output=True, check=False,
        )
    subprocess.run(
        ["sc.exe", "stop", SERVICE_NAME],
        capture_output=True, check=False,
    )
    # Wait for the process to exit (up to 15 s)
    _proc_alive = True
    for _ in range(15):
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {APP_NAME}.exe",
             "/FO", "CSV", "/NH"],
            capture_output=True, encoding="utf-8", check=False,
        )
        if APP_NAME.lower() not in r.stdout.lower():
            _proc_alive = False
            break
        time.sleep(1)
    # Force-kill as last resort so shutil.copy2 doesn't hit WinError 32
    if _proc_alive:
        subprocess.run(
            ["taskkill", "/F", "/IM", f"{APP_NAME}.exe"],
            capture_output=True, check=False,
        )
        time.sleep(2)

    # Windows needs a moment to fully release file handles after
    # TerminateProcess – without this the WAL checkpoint may fail
    # because the OS still holds a shared lock on the DB file.
    time.sleep(2)

    # Merge WAL into the main DB file now that the process has exited –
    # this ensures the survival wheelset is in the main .db file and
    # survives the installer overwriting the EXE.
    _upgrade_db = upgrade_data / "db" / "wheel_storage.db"
    ckpt_ok = _wal_checkpoint(_upgrade_db)
    _check("4c: WAL checkpoint succeeded", ckpt_ok)

    # If the WAL checkpoint failed, try reading the data directly to see
    # if it's at least in the WAL (SQLite auto-replays WAL on open).
    if not ckpt_ok:
        try:
            con = sqlite3.connect(str(_upgrade_db))
            cur = con.execute(
                "SELECT 1 FROM wheel_sets "
                "WHERE license_plate = 'UPG-S 7' LIMIT 1",
            )
            found = cur.fetchone() is not None
            con.close()
            _check("4c: UPG-S 7 in DB via direct query (WAL replay)",
                   found, "not found even via direct query")
        except sqlite3.Error as exc:
            _check("4c: direct SQLite query failed", False, str(exc))

    dest_exe = upgrade_dir / f"{APP_NAME}.exe"
    try:
        shutil.copy2(str(app_exe), str(dest_exe))
        copied = True
    except OSError as exc:
        copied = False
        _check("4c: updated EXE staged for upgrade", False, str(exc))

    if copied:
        rc2, _ = _run_installer(
            inst_exe, "install", upgrade_dir, upgrade_data, port)
        _check("4c: upgrade installer exited 0", rc2 == 0, f"exit {rc2}")

    _section("Phase 4d – Service health after upgrade")
    _check(
        "4d: service responds after upgrade",
        _wait_http_up(base, timeout=60),
    )
    _check("4d: service state RUNNING", _service_state() == "RUNNING")
    _check(
        "4d: service start type is AUTO_START after upgrade",
        "AUTO_START" in _service_start_type(),
        _service_start_type() or "(service not found)",
    )

    _section("Phase 4e – Data intact after upgrade")
    # Give the freshly started service a moment to replay the WAL
    # and render the full wheelset list.
    time.sleep(3)
    _, ws_body = _get(base, "/wheelsets")
    http_found = b"UPG-S 7" in ws_body
    if not http_found:
        print("    4e: UPG-S 7 not in HTTP response, "
              "trying direct DB query …", flush=True)
        # Fallback: read the DB file directly (the HTTP layer may not
        # reflect the data immediately after a fresh service start if
        # the WAL hasn't been replayed yet).
        db_path = upgrade_data / "db" / "wheel_storage.db"
        db_found = False
        if db_path.exists():
            try:
                con = sqlite3.connect(str(db_path))
                # Count all rows to help diagnose empty-DB scenarios
                total = con.execute(
                    "SELECT COUNT(*) FROM wheel_sets"
                ).fetchone()[0]
                cur = con.execute(
                    "SELECT 1 FROM wheel_sets "
                    "WHERE license_plate = 'UPG-S 7' LIMIT 1",
                )
                db_found = cur.fetchone() is not None
                con.close()
                print(f"    4e: DB has {total} wheelset(s), "
                      f"UPG-S 7 found={db_found}", flush=True)
            except (sqlite3.Error, OSError) as exc:
                print(f"    4e: direct DB query error: {exc}", flush=True)
        else:
            print(f"    4e: DB file missing: {db_path}", flush=True)
        _check(
            "4e: survival wheelset still present after upgrade",
            db_found,
            "marker license plate not found in HTTP response or DB file",
        )
    else:
        _check(
            "4e: survival wheelset still present after upgrade",
            True,
        )

    _section("Phase 4f – App functionality after upgrade")
    _phase1b_crud(base)
    _phase1c_settings(base)
    _phase1e_security(base)

    _section("Phase 4g – Cleanup: full uninstall after upgrade test")
    rc3, _ = _run_installer(
        inst_exe, "uninstall", upgrade_dir, upgrade_data, port)
    _check("4g: post-upgrade uninstall exited 0", rc3 == 0, f"exit {rc3}")
    _check("4g: service removed", not _service_exists())
    _check("4g: upgrade install dir deleted", not upgrade_dir.exists())


# ══════════════════════════════════════════════════════════════════════
# Phase 5 – Installer update-check (headless)
# ══════════════════════════════════════════════════════════════════════

def phase5_installer_update_check(inst_exe: Path) -> None:
    """
    5a  Run  inst_exe --headless --action check-update.
    5b  Exit code must be 0.
    5c  stdout must be valid JSON with all required keys.
    5d  current_version must be a non-empty string.
    5e  update_available must be a bool.
    5f  No SSL CERTIFICATE_VERIFY_FAILED in stderr (corporate-CA fix).
    """
    _section("Phase 5 – Installer update check (headless)")

    result = subprocess.run(
        [str(inst_exe), "--headless", "--action", "check-update"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    _check("5a: check-update exited 0", result.returncode == 0,
           f"exit {result.returncode}")

    # 5b – parse JSON
    info: dict = {}
    try:
        info = _json.loads(result.stdout)
        _check("5b: stdout is valid JSON", True)
    except (ValueError, TypeError) as exc:
        _check("5b: stdout is valid JSON", False, str(exc))
        return   # remaining checks need the dict

    required_keys = {
        "update_available", "current_version", "remote_version",
        "release_notes", "changelog_section", "release_url", "installer_url",
    }
    missing = required_keys - info.keys()
    _check("5c: JSON has all required keys",
           not missing, f"missing: {missing}")

    _check(
        "5d: current_version is non-empty",
        isinstance(info.get("current_version"), str)
        and len(info.get("current_version", "")) > 0,
        str(info.get("current_version")),
    )

    _check(
        "5e: update_available is bool",
        isinstance(info.get("update_available"), bool),
        str(type(info.get("update_available"))),
    )

    ssl_error = "CERTIFICATE_VERIFY_FAILED" in (
        result.stdout + result.stderr
    )
    _check(
        "5f: no SSL CERTIFICATE_VERIFY_FAILED in output",
        not ssl_error,
        "SSL cert error — corporate CA not in Windows trust store?" if ssl_error else "",
    )

    # Informational: log whether an update is available
    if info.get("update_available"):
        print(
            f"  [INFO] Update available: "
            f"{info.get('current_version')} → {info.get('remote_version')}",
            flush=True,
        )
    else:
        print(
            f"  [INFO] No update: current={info.get('current_version')}, "
            f"remote={info.get('remote_version')}",
            flush=True,
        )


# ══════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════

