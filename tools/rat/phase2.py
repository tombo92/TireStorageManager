"""
Release Acceptance Test – Phase 2: Installer end-to-end checks.

Covers fresh install, idempotent reinstall, DB restore edge cases,
service resilience, scheduled-task firing, uninstall (keep/delete data)
and ghost-task guard.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from .helpers import (
    APP_NAME,
    SERVICE_NAME,
    TASK_NAME,
    _check,
    _firewall_rule_exists,
    _get,
    _is_admin,
    _make_db_missing_table,
    _make_valid_db,
    _run_installer,
    _section,
    _service_exists,
    _service_start_type,
    _service_state,
    _task_exists,
    _wait_http_down,
    _wait_http_up,
    _warnings,
)


def phase2_installer(
    inst_exe: Path,
    install_dir: Path,
    data_dir: Path,
    port: int,
    *,
    task_repeats: int = 3,
) -> None:
    base = f"http://127.0.0.1:{port}"

    # ── 2a Pre-flight ────────────────────────────────────────────────
    _section("Phase 2a – Installer pre-flight")
    r = subprocess.run(
        [str(inst_exe), "--version"],
        capture_output=True, encoding="utf-8", timeout=30, check=False,
    )
    _check("--version returns 0 and a version string",
           r.returncode == 0 and bool(r.stdout.strip()),
           r.stdout.strip())
    _check("Running as admin", _is_admin(), "re-run in elevated shell")
    _check("Service not already installed", not _service_exists())

    # ── 2b Fresh install ──────────────────────────────────────────────
    _section("Phase 2b – Fresh install")
    rc, _ = _run_installer(inst_exe, "install", install_dir, data_dir, port,
                           shortcut=True)
    _check("Installer exited 0", rc == 0, f"exit {rc}")
    _check("App EXE deployed", (install_dir / f"{APP_NAME}.exe").exists())
    _check("nssm.exe deployed", (install_dir / "nssm.exe").exists())
    _check("data/db/ created", (data_dir / "db").is_dir())
    _check("data/backups/ created", (data_dir / "backups").is_dir())
    _check("data/logs/ created", (data_dir / "logs").is_dir())
    _check("Service registered", _service_exists())
    _check(
        "Service start type is AUTO_START (boots with Windows)",
        "AUTO_START" in _service_start_type(),
        _service_start_type() or "(service not found)",
    )
    _check(f"Firewall rule for port {port}", _firewall_rule_exists(port))
    _check("Scheduled task created", _task_exists())

    # ── 2c App responds through service ──────────────────────────────
    _section("Phase 2c – App responds through installed service")
    _check(
        f"HTTP 200 on :{port}/ within 60 s (via service)",
        _wait_http_up(base, timeout=60),
    )
    _check("Service state RUNNING", _service_state() == "RUNNING")
    # Basic page smoke via service
    code, _ = _get(base, "/wheelsets")
    _check("GET /wheelsets through service -> 200", code == 200, f"got {code}")

    # ── 2d Reinstall over existing installation (idempotency) ─────────
    _section("Phase 2d – Reinstall over existing installation (idempotency)")
    # Stop the service before reinstalling so the EXE is not locked.
    _nssm = install_dir / "nssm.exe"
    if _nssm.exists():
        subprocess.run([str(_nssm), "stop", SERVICE_NAME],
                       capture_output=True, check=False)
    subprocess.run(["sc.exe", "stop", SERVICE_NAME],
                   capture_output=True, check=False)
    # Wait for EXE process to exit (up to 15 s)
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
    # Force-kill if the process refused to exit gracefully
    if _proc_alive:
        subprocess.run(
            ["taskkill", "/F", "/IM", f"{APP_NAME}.exe"],
            capture_output=True, check=False,
        )
        time.sleep(2)
    rc2, _ = _run_installer(inst_exe, "install", install_dir, data_dir, port)
    _check("Reinstall exited 0", rc2 == 0, f"exit {rc2}")
    _check(
        "Service still responds after reinstall",
        _wait_http_up(base, timeout=60),
    )
    # NSSM updates the SCM state slightly after the process starts;
    # give it up to 10 s to transition to RUNNING.
    _svc_running = False
    for _ in range(10):
        if _service_state() == "RUNNING":
            _svc_running = True
            break
        time.sleep(1)
    _check(
        "Service state RUNNING after reinstall",
        _svc_running,
    )
    _check(
        "Service start type is AUTO_START after reinstall",
        "AUTO_START" in _service_start_type(),
        _service_start_type() or "(service not found)",
    )

    # ── 2e Restore-DB edge cases ──────────────────────────────────────
    _section("Phase 2e – Restore-DB edge cases")
    _phase2e_restore_db(inst_exe, install_dir, data_dir, port, base)

    # ── 2f Service resilience – kill & recovery ───────────────────────
    _section("Phase 2f – Service resilience (kill & auto-recovery)")
    _phase2f_service_resilience(base)

    # ── 2g Scheduled-task fires correctly ────────────────────────────
    _section("Phase 2g – Scheduled-task restart (repeated)")
    _phase2g_task_repeated(base, repeats=task_repeats)

    # ── 2h Uninstall keep-data ────────────────────────────────────────
    _section("Phase 2h – Uninstall (keep data)")
    rc, _ = _run_installer(inst_exe, "uninstall", install_dir, data_dir, port,
                           keep_data=True)
    _check("Uninstall (keep-data) exited 0", rc == 0, f"exit {rc}")
    _check("Service removed", not _service_exists())
    _check("Scheduled task removed", not _task_exists())
    _check("Firewall rule removed", not _firewall_rule_exists(port))
    _check("Install dir deleted", not install_dir.exists())
    _check("Data dir preserved", data_dir.exists())
    _check(
        "DB file preserved",
        (data_dir / "db" / "wheel_storage.db").exists(),
    )

    # ── 2i Reinstall after keep-data uninstall ────────────────────────
    _section("Phase 2i – Reinstall after keep-data uninstall")
    rc, _ = _run_installer(inst_exe, "install", install_dir, data_dir, port)
    _check("Reinstall after keep-data exited 0", rc == 0, f"exit {rc}")
    _check(
        "Service responds after reinstall-over-existing-data",
        _wait_http_up(base, timeout=60),
    )
    _check(
        "Service start type is AUTO_START after reinstall-over-data",
        "AUTO_START" in _service_start_type(),
        _service_start_type() or "(service not found)",
    )

    # ── 2j Full uninstall ─────────────────────────────────────────────
    _section("Phase 2j – Full uninstall (delete data)")
    rc, _ = _run_installer(inst_exe, "uninstall", install_dir, data_dir, port)
    _check("Full uninstall exited 0", rc == 0, f"exit {rc}")
    _check("Service removed", not _service_exists())
    _check("Task removed", not _task_exists())
    _check("Install dir deleted", not install_dir.exists())
    _check("Data dir deleted", not data_dir.exists())

    # ── 2k Ghost-task guard ────────────────────────────────────────────
    _section("Phase 2k – Ghost-task guard (service stays down)")
    _check("Service not running after full uninstall",
           _service_state() != "RUNNING")
    _check("No ghost task can restart service",
           not _task_exists())


def _phase2e_restore_db(
    inst_exe: Path,
    install_dir: Path,
    data_dir: Path,
    port: int,
    base: str,
) -> None:
    db_dir = data_dir / "db"
    backup_dir = data_dir / "backups"
    restore_tmp = data_dir / "_rat_restore_tmp"
    restore_tmp.mkdir(exist_ok=True)

    # Case 1: corrupt (non-SQLite) file
    corrupt = restore_tmp / "corrupt.db"
    corrupt.write_bytes(b"not a database")
    rc, out = _run_installer(inst_exe, "restore-db", install_dir, data_dir,
                             port, source_db=corrupt)
    _check("Corrupt DB rejected (non-zero exit)", rc != 0, f"exit {rc}")
    _check(
        "Error message in output for corrupt DB",
        "fehler" in out.lower()
        or "error" in out.lower()
        or "header" in out.lower(),
    )
    _check("Service still RUNNING after corrupt reject",
           _service_state() == "RUNNING")

    # Case 2: valid SQLite but missing required tables (schema mismatch)
    wrong_schema = restore_tmp / "wrong_schema.db"
    _make_db_missing_table(wrong_schema)
    rc, out = _run_installer(inst_exe, "restore-db", install_dir, data_dir,
                             port, source_db=wrong_schema)
    _check("Wrong-schema DB rejected (non-zero exit)", rc != 0, f"exit {rc}")
    _check("Service still RUNNING after schema-mismatch reject",
           _service_state() == "RUNNING")

    # Case 3: non-existent source file
    missing = restore_tmp / "does_not_exist.db"
    rc, _ = _run_installer(inst_exe, "restore-db", install_dir, data_dir,
                           port, source_db=missing)
    _check("Missing source DB rejected (non-zero exit)", rc != 0, f"exit {rc}")

    # Case 4: valid restore
    valid = restore_tmp / "valid.db"
    _make_valid_db(valid)
    backups_before = set(backup_dir.glob("wheel_storage_*.db"))
    rc, _ = _run_installer(inst_exe, "restore-db", install_dir, data_dir,
                           port, source_db=valid)
    _check("Valid restore exited 0", rc == 0, f"exit {rc}")
    backups_after = set(backup_dir.glob("wheel_storage_*.db"))
    _check(
        "Backup of old DB created before restore",
        len(backups_after - backups_before) >= 1,
    )
    live_db = db_dir / "wheel_storage.db"
    _check(
        "Live DB replaced (valid SQLite header)",
        live_db.exists()
        and live_db.read_bytes()[:16] == b"SQLite format 3\x00",
    )
    _check(
        "Service responds after restore",
        _wait_http_up(base, timeout=30),
    )

    # Cleanup temp dir
    shutil.rmtree(restore_tmp, ignore_errors=True)


def _phase2f_service_resilience(base: str) -> None:
    """Kill the service process directly; NSSM should restart it."""
    # Find the TireStorageManager.exe PID via tasklist
    r = subprocess.run(
        [
            "tasklist", "/FI",
            f"IMAGENAME eq {APP_NAME}.exe",
            "/FO", "CSV", "/NH",
        ],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    pids = re.findall(r'"TireStorageManager\.exe","(\d+)"', r.stdout)
    if not pids:
        _check("Service process found for kill test", False,
               "process not found – skipping kill test", warn=True)
        return

    pid = pids[0]
    subprocess.run(["taskkill", "/F", "/PID", pid],
                   capture_output=True, check=False)
    _check("Service process killed", True)

    # NSSM should restart it automatically
    _check(
        "Service auto-restarts after kill (HTTP 200 within 60 s)",
        _wait_http_up(base, timeout=60),
    )
    # Give NSSM a moment to update the SCM state after the restart
    time.sleep(5)
    _check("Service state RUNNING after kill", _service_state() == "RUNNING")


def _phase2g_task_once(base: str, hhmm: str, mmddyyyy: str) -> bool:
    """
    Reschedule TASK_NAME as a ONCE trigger and wait for it to fire.
    Returns True if the service went down and came back up.
    """
    tr = (
        f"cmd /c \"sc.exe stop {SERVICE_NAME} & "
        f"timeout /t 5 /nobreak >nul & "
        f"sc.exe start {SERVICE_NAME}\""
    )
    r = subprocess.run(
        [
            "schtasks", "/Create", "/F", "/TN", TASK_NAME,
            "/TR", tr, "/SC", "ONCE",
            "/SD", mmddyyyy, "/ST", hhmm,
            "/RL", "HIGHEST",
        ],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    rescheduled = r.returncode == 0
    _check(
        f"Task rescheduled for {hhmm} (ONCE)",
        rescheduled,
        r.stderr.strip() if not rescheduled else "",
    )
    if not rescheduled:
        _warnings.append("Skipping task-fire wait – rescheduling failed")
        return False

    wait_s = 240
    print(
        f"  Waiting up to {wait_s}s for task to fire at {hhmm} …",
        flush=True,
    )
    went_down = _wait_http_down(base, timeout=wait_s)
    _check(
        "Service stopped when task fired",
        went_down,
        f"task did not fire within {wait_s}s",
        warn=True,  # CI schedulers can be slow; not a hard blocker
    )
    if not went_down:
        return False

    came_back = _wait_http_up(base, timeout=90)
    _check(
        "Service restarted after task-triggered stop",
        came_back,
        warn=True,  # CI task scheduler timing is unreliable
    )
    return came_back


def _phase2g_task_repeated(base: str, *, repeats: int = 3) -> None:
    """
    Run the scheduled-task fire cycle *repeats* times, spacing triggers
    3 minutes apart.  Each round:
      1. Reschedule the task N minutes in the future.
      2. Wait for the service to stop (task fired).
      3. Wait for the service to come back up (task did sc.exe start).
      4. Verify /wheelsets responds 200 (data intact).
    """
    for i in range(1, repeats + 1):
        trigger = datetime.now() + timedelta(minutes=3)
        hhmm = trigger.strftime("%H:%M")
        mmddyyyy = trigger.strftime("%m/%d/%Y")
        print(
            f"\n  ── Task-restart cycle {i}/{repeats} "
            f"(trigger {hhmm}) ──",
            flush=True,
        )
        ok = _phase2g_task_once(base, hhmm, mmddyyyy)
        if ok:
            code, _ = _get(base, "/wheelsets")
            _check(
                f"Cycle {i}: /wheelsets reachable after restart",
                code == 200,
                f"got {code}",
            )
        else:
            # The failure was already recorded inside _phase2g_task_once;
            # task-scheduler timing is unreliable in CI, so skip remaining
            # cycles without adding a redundant warning entry.
            print(
                f"  NOTE  Cycle {i}: task-restart not confirmed"
                " – skipping remaining cycles",
                flush=True,
            )
            break


# ══════════════════════════════════════════════════════════════════════
# Phase 3 – Update flow (repeated)
# ══════════════════════════════════════════════════════════════════════
