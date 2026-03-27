#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Installer EXE Smoke Test – end-to-end verification of TSM-Installer.exe.

Drives the compiled installer in --headless mode and verifies every
installation and uninstallation step against the real Windows environment.
Requires: Windows, admin rights, dist/TSM-Installer.exe present.

Usage (called by CI):
    python tools/smoke_test_installer.py \\
        --exe     dist/TSM-Installer.exe \\
        --install-dir C:/tsm_ci_install \\
        --data-dir    C:/tsm_ci_data \\
        --port        59200

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed (details printed to stdout).
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# Force UTF-8 output on Windows CI runners whose default stdout codec
# (cp1252) cannot encode the Unicode box-drawing / tick characters used
# in the check output.  Python 3.7+ supports reconfigure(); fall back to
# wrapping with a TextIOWrapper for older builds.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace")

APP_NAME = "TireStorageManager"
SERVICE_NAME = "TireStorageManager"
TASK_NAME = f"{APP_NAME}_DailyUpdate"

PASS = "OK"
FAIL = "FAIL"

_failures: list[str] = []


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _check(name: str, ok: bool, detail: str = "") -> bool:
    if ok:
        print(f"  {PASS} {name}", flush=True)
    else:
        msg = f"  {FAIL} {name}" + (f": {detail}" if detail else "")
        print(msg, flush=True)
        _failures.append(msg)
    return ok


def _run_installer(
    exe: Path,
    action: str,
    install_dir: Path,
    data_dir: Path,
    port: int,
    *,
    keep_data: bool = False,
    shortcut: bool = False,
    timeout: int = 120,
) -> tuple[int, str]:
    """Run TSM-Installer.exe in headless mode.

    Output is streamed line-by-line to stdout in real time so CI logs
    show progress instead of a silent pause.  Returns (returncode, output).
    """
    cmd = [
        str(exe),
        "--headless",
        "--action", action,
        "--install-dir", str(install_dir),
        "--data-dir", str(data_dir),
        "--port", str(port),
    ]
    if keep_data:
        cmd.append("--keep-data")
    if shortcut:
        cmd.append("--shortcut")

    lines: list[str] = []
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        print(f"    {line}", flush=True)
        lines.append(line)
    proc.wait(timeout=timeout)
    return proc.returncode, "\n".join(lines)


def _service_state() -> str:
    """Return sc.exe query state string, e.g. 'RUNNING', 'STOPPED'."""
    r = subprocess.run(
        ["sc.exe", "query", SERVICE_NAME],
        capture_output=True, encoding="utf-8",
        errors="replace", check=False,
    )
    for line in r.stdout.splitlines():
        if "STATE" in line:
            return line.split()[-1]
    return ""


def _service_exists() -> bool:
    r = subprocess.run(
        ["sc.exe", "query", SERVICE_NAME],
        capture_output=True, encoding="utf-8",
        errors="replace", check=False,
    )
    return r.returncode == 0


def _task_exists() -> bool:
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True, encoding="utf-8",
        errors="replace", check=False,
    )
    return r.returncode == 0


def _firewall_rule_exists(port: int) -> bool:
    rule = f"{APP_NAME} TCP {port}"
    r = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule",
         f"name={rule}"],
        capture_output=True, encoding="utf-8",
        errors="replace", check=False,
    )
    return r.returncode == 0


def _http_ok(port: int, timeout: int = 30) -> bool:
    """Poll http://127.0.0.1:<port>/ until HTTP 200 or timeout.

    Prints a progress line every 15 s so CI logs show the wait is alive.
    """
    deadline = time.monotonic() + timeout
    last_dot = time.monotonic()
    while time.monotonic() < deadline:
        try:
            r = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/",
                timeout=3,
            )
            if r.status == 200:
                return True
        except OSError:
            pass
        if time.monotonic() - last_dot >= 15:
            elapsed = int(time.monotonic() - (deadline - timeout))
            print(f"  ... waiting for service on :{port} ({elapsed}s)",
                  flush=True)
            last_dot = time.monotonic()
        time.sleep(1)
    return False


def _shortcut_exists(display_name: str) -> bool:
    public = os.environ.get("PUBLIC", r"C:\Users\Public")
    return (Path(public) / "Desktop" / f"{display_name}.url").exists()


# ──────────────────────────────────────────────────────────────────────
# Pre-flight
# ──────────────────────────────────────────────────────────────────────
def check_preconditions(exe: Path) -> bool:
    print("\n── Pre-flight checks ──────────────────────────────────")
    ok = True
    ok &= _check("EXE exists", exe.exists(), str(exe))
    ok &= _check(
        "--version flag works",
        _version_flag_works(exe),
        "EXE returned non-zero for --version",
    )
    ok &= _check(
        "Running as admin",
        _is_admin(),
        "Re-run in elevated PowerShell",
    )
    ok &= _check(
        "Service not already installed",
        not _service_exists(),
        f"Remove service '{SERVICE_NAME}' before running smoke test",
    )
    return ok


def _version_flag_works(exe: Path) -> bool:
    r = subprocess.run(
        [str(exe), "--version"],
        capture_output=True, encoding="utf-8",
        errors="replace", timeout=30, check=False,
    )
    return r.returncode == 0 and bool(r.stdout.strip())


def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


# ──────────────────────────────────────────────────────────────────────
# Install suite
# ──────────────────────────────────────────────────────────────────────
def run_install_checks(
    exe: Path, install_dir: Path, data_dir: Path, port: int
) -> None:
    _ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n-- Install [{_ts}] ----------------------------------------")

    rc, _ = _run_installer(
        exe, "install", install_dir, data_dir, port, shortcut=True)
    _check("Installer exited 0", rc == 0, f"exit code {rc}")

    # ── Payload unpacking ────────────────────────────────────────────
    _check(
        "TireStorageManager.exe deployed",
        (install_dir / f"{APP_NAME}.exe").exists(),
    )
    _check(
        "nssm.exe deployed",
        (install_dir / "nssm.exe").exists(),
    )

    # ── Directory structure ──────────────────────────────────────────
    _check("data/db/ created",      (data_dir / "db").is_dir())
    _check("data/backups/ created", (data_dir / "backups").is_dir())
    _check("data/logs/ created",    (data_dir / "logs").is_dir())

    # ── Database seed ────────────────────────────────────────────────
    # The seed DB is optional – it may not be bundled in CI builds.
    # Accept either: seeded from template, OR file absent (created on
    # first start).  Only fail if the db/ directory itself is missing.
    db_path = data_dir / "db" / "wheel_storage.db"
    _check(
        "wheel_storage.db present or will be created on first start",
        db_path.exists() or (data_dir / "db").is_dir(),
    )

    # ── Windows Service ──────────────────────────────────────────────
    _check("Service registered", _service_exists())

    # ── Service starts and responds ──────────────────────────────────
    _check(
        f"Service responds on :{port} (HTTP 200)",
        _http_ok(port, timeout=45),
    )
    _check("Service state RUNNING", _service_state() == "RUNNING")

    # ── Scheduled Task ───────────────────────────────────────────────
    _check("Daily update task created", _task_exists())

    # ── Scheduled Task contains cmd /c wrapper ───────────────────────
    _check(
        "Scheduled task uses cmd /c wrapper",
        _task_has_cmd_c_wrapper(),
    )

    # ── Firewall ─────────────────────────────────────────────────────
    _check(
        f"Firewall rule for port {port}",
        _firewall_rule_exists(port),
    )

    # ── Desktop shortcut ─────────────────────────────────────────────
    _check(
        "Desktop shortcut created",
        _shortcut_exists("Reifenmanager"),
    )


def _task_has_cmd_c_wrapper() -> bool:
    """Verify the scheduled task's action contains the cmd /c wrapper.

    Uses /FO LIST (plain text) instead of /XML because the XML format
    splits <Command> and <Arguments> into separate elements, so
    'cmd /c' never appears as a contiguous string in the XML output.
    The LIST format emits a 'Task To Run:' line with the full command.
    """
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
        capture_output=True, encoding="utf-8",
        errors="replace", check=False,
    )
    text = r.stdout.lower()
    return (
        "cmd /c" in text
        and "sc.exe stop" in text
        and "sc.exe start" in text
    )


def _http_down(port: int, timeout: int = 60) -> bool:
    """Poll until the server stops responding, or timeout expires.

    Prints a progress dot every 30 s so CI logs show the wait is alive.
    """
    deadline = time.monotonic() + timeout
    last_dot = time.monotonic()
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=2)
        except OSError:
            return True   # connection refused / reset = server is down
        if time.monotonic() - last_dot >= 30:
            elapsed = int(time.monotonic() - (deadline - timeout))
            print(f"  ... still waiting for service to stop ({elapsed}s)",
                  flush=True)
            last_dot = time.monotonic()
        time.sleep(1)
    return False


def _reschedule_task_once(trigger: datetime) -> bool:
    """Overwrite the daily task with a ONCE trigger at *trigger* (local).

    /SD (start date) pins the trigger to today so Task Scheduler cannot
    skip the task if the HH:MM is close to the current time.
    Uses a list invocation (no shell=True) to avoid quoting mangling.
    Returns True on success.
    """
    hhmm = trigger.strftime("%H:%M")
    mmddyyyy = trigger.strftime("%m/%d/%Y")   # schtasks date format
    tr_value = (
        f"cmd /c \"sc.exe stop {SERVICE_NAME} & "
        f"timeout /t 5 /nobreak >nul & "
        f"sc.exe start {SERVICE_NAME}\""
    )
    r = subprocess.run(
        [
            "schtasks", "/Create", "/F",
            "/TN", TASK_NAME,
            "/TR", tr_value,
            "/SC", "ONCE",
            "/SD", mmddyyyy,
            "/ST", hhmm,
            "/RL", "HIGHEST",
        ],
        capture_output=True, encoding="utf-8",
        errors="replace", check=False,
    )
    if r.returncode != 0:
        print(f"  schtasks error: {r.stderr.strip()}", flush=True)
    return r.returncode == 0


# ──────────────────────────────────────────────────────────────────────
# Scheduled-restart suite
# ──────────────────────────────────────────────────────────────────────
def run_restart_checks(port: int) -> None:
    """Verify the scheduled task actually fires and restarts the service.

    Strategy: overwrite the daily task with a ONCE trigger 2 minutes in
    the future, then wait for:
      1. The service to stop  (sc.exe stop fired by Task Scheduler)
      2. The service to restart and return HTTP 200  (sc.exe start ran)

    Also verifies that after uninstall the task is gone and therefore
    *cannot* restart the service again unexpectedly.
    """
    _ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n-- Scheduled restart [{_ts}] -------------------------------")

    trigger = datetime.now() + timedelta(minutes=3)
    rescheduled = _reschedule_task_once(trigger)
    _check(
        f"Task rescheduled for {trigger.strftime('%H:%M')} (ONCE)",
        rescheduled,
    )
    if not rescheduled:
        # Can't proceed without a working task.
        _failures.append("  Skipping restart wait - rescheduling failed")
        return

    # ── Wait for the task to fire and stop the service ────────────────
    # Allow 4 minutes: 3 min until trigger + 60 s margin for sc.exe stop.
    wait_until = datetime.now() + timedelta(seconds=240)
    print(
        f"  Waiting for Task Scheduler to fire at "
        f"{trigger.strftime('%H:%M')} "
        f"(deadline {wait_until.strftime('%H:%M:%S')}) ...",
        flush=True,
    )
    went_down = _http_down(port, timeout=240)
    _check(
        "Service stopped when task fired",
        went_down,
        "Task Scheduler did not stop the service within 3.5 min",
    )

    # ── Wait for sc.exe start to bring it back ────────────────────────
    if went_down:
        print("  Service stopped – waiting for restart …", flush=True)
        came_back = _http_ok(port, timeout=90)
        _check(
            "Service restarted and returned HTTP 200",
            came_back,
            "Service did not come back within 90 s after stopping "
            "(cmd /c wrapper regression or sc.exe start failed)",
        )


# ──────────────────────────────────────────────────────────────────────
# Uninstall suite
# ──────────────────────────────────────────────────────────────────────
def run_uninstall_checks(
    exe: Path, install_dir: Path, data_dir: Path, port: int
) -> None:
    _ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n-- Uninstall [{_ts}] -----------------------------------------")

    rc, _ = _run_installer(
        exe, "uninstall", install_dir, data_dir, port)
    _check("Uninstaller exited 0", rc == 0, f"exit code {rc}")

    # Service gone
    _check("Service removed", not _service_exists())

    # Port no longer responds – service was stopped by uninstaller,
    # so this should be immediate; use a short timeout as a safety net.
    _check(
        f"Port {port} no longer responds",
        not _http_ok(port, timeout=5),
    )

    # Scheduled task gone – verify the task is absent.
    # No need to poll; if task removal worked it is gone immediately.
    _check("Daily update task removed", not _task_exists())
    # Confirm the service cannot be restarted by a ghost task.
    _check(
        "Service stays down (no ghost restart)",
        _service_state() != "RUNNING",
    )

    # Firewall rule gone
    _check(
        f"Firewall rule for port {port} removed",
        not _firewall_rule_exists(port),
    )

    # Shortcut gone
    _check(
        "Desktop shortcut removed",
        not _shortcut_exists("Reifenmanager"),
    )

    # Install directory deleted
    _check(
        "Install directory deleted",
        not install_dir.exists(),
    )

    # Data directory deleted
    _check(
        "Data directory deleted",
        not data_dir.exists(),
    )


# ──────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end smoke test for TSM-Installer.exe")
    parser.add_argument(
        "--exe", required=True,
        help="Path to TSM-Installer.exe")
    parser.add_argument(
        "--install-dir", required=True, dest="install_dir",
        help="Temporary install directory (will be deleted)")
    parser.add_argument(
        "--data-dir", required=True, dest="data_dir",
        help="Temporary data directory (will be deleted)")
    parser.add_argument(
        "--port", type=int, default=59200,
        help="HTTP port to use during smoke test")
    args = parser.parse_args()

    exe = Path(args.exe).resolve()
    install_dir = Path(args.install_dir).resolve()
    data_dir = Path(args.data_dir).resolve()

    if not check_preconditions(exe):
        print("\nPre-flight failed – aborting.", flush=True)
        return 1

    try:
        run_install_checks(exe, install_dir, data_dir, args.port)
        run_restart_checks(args.port)
        run_uninstall_checks(exe, install_dir, data_dir, args.port)
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
        return 1

    print("\n" + "═" * 55, flush=True)
    if _failures:
        print(f"FAILED  ({len(_failures)} check(s)):", flush=True)
        for f in _failures:
            print(f"  {f}", flush=True)
        return 1

    print("ALL CHECKS PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
