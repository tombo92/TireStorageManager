#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Integration test – scheduled service restart via Windows Task Scheduler.

What this tests end-to-end:
  1. create_update_task() registers a schtasks entry that contains
     cmd /c and both sc.exe stop AND sc.exe start (regression guard).
  2. A real schtasks task is created with a trigger 2 minutes in the
     future, the EXE service stops and restarts, and the web server
     responds HTTP 200 again within the expected window.
  3. remove_scheduled_task() deletes the task; schtasks /Query confirms
     it is gone.

Skip conditions (auto-detected, no manual flag needed):
  - Not running on Windows
  - Not running as Administrator
  - dist/TireStorageManager.exe does not exist
  - SERVICE_NAME service is not registered (not installed via NSSM)

Run manually (elevated PowerShell / cmd):
    pytest tests/test_scheduled_restart.py -v -m integration
"""
from __future__ import annotations

import ctypes
import http.cookiejar
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from installer import installer_logic as logic

# ── Skip conditions ───────────────────────────────────────────────────
_IS_WINDOWS = sys.platform == "win32"


def _is_admin() -> bool:
    if not _IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def _service_registered() -> bool:
    """Return True when SERVICE_NAME is known to sc.exe."""
    if not _IS_WINDOWS:
        return False
    r = subprocess.run(
        ["sc.exe", "query", logic.SERVICE_NAME],
        capture_output=True, encoding="utf-8", errors="replace",
        check=False,
    )
    return r.returncode == 0


def _exe_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "dist" / "TireStorageManager.exe"


_SKIP_REASON = (
    "integration test requires Windows + Administrator"
    " + installed service + dist/TireStorageManager.exe"
)

_skip_unless_ready = pytest.mark.skipif(
    not (_IS_WINDOWS
         and _is_admin()
         and _exe_path().exists()
         and _service_registered()),
    reason=_SKIP_REASON,
)

# ── HTTP helper ───────────────────────────────────────────────────────


def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _wait_http_200(port: int, timeout: int = 90) -> bool:
    """Poll GET / until HTTP 200 or timeout (seconds)."""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj))
    deadline = time.monotonic() + timeout
    url = _base_url(port) + "/"
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(2)
    return False


def _wait_http_down(port: int, timeout: int = 45) -> bool:
    """Poll until the server stops responding (connection refused)."""
    deadline = time.monotonic() + timeout
    url = _base_url(port) + "/"
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
        except OSError:
            return True   # refused / no route = server is down
        time.sleep(1)
    return False


def _task_exists(task_name: str) -> bool:
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", task_name],
        capture_output=True, encoding="utf-8", errors="replace",
        check=False,
    )
    return r.returncode == 0


def _get_service_port() -> int:
    """Read the port the service was installed with from sc qc output."""
    r = subprocess.run(
        ["sc.exe", "qc", logic.SERVICE_NAME],
        capture_output=True, encoding="utf-8", errors="replace",
        check=False,
    )
    for part in r.stdout.split():
        try:
            candidate = int(part)
            if 1024 <= candidate <= 65535:
                return candidate
        except ValueError:
            continue
    return 5000


# ══════════════════════════════════════════════════════════════════════
# Helpers – task creation with custom trigger time
# ══════════════════════════════════════════════════════════════════════

def _create_task_at(trigger_time: datetime) -> subprocess.CompletedProcess:
    """
    Create the TireStorageManager_DailyUpdate task with a one-off trigger
    at *trigger_time* (local time, HH:MM format).

    This mirrors create_update_task() but sets /ST to a value in the near
    future so the test doesn't have to wait until 03:00.
    """
    task_name = f"{logic.APP_NAME}_DailyUpdate"
    hhmm = trigger_time.strftime("%H:%M")
    cmd = (
        f'schtasks /Create /F /TN "{task_name}" '
        f'/TR "cmd /c \\"sc.exe stop {logic.SERVICE_NAME} & '
        f'timeout /t 5 /nobreak >nul & '
        f'sc.exe start {logic.SERVICE_NAME}\\"" '
        f'/SC ONCE /ST {hhmm} /RL HIGHEST'
    )
    return logic.run_shell(cmd)


# ══════════════════════════════════════════════════════════════════════
# Test class
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestScheduledRestartIntegration:
    """Real smoke tests that touch Windows Task Scheduler and the live
    service."""

    task_name = f"{logic.APP_NAME}_DailyUpdate"

    def teardown_method(self):
        """Always clean up the scheduled task after each test."""
        subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", self.task_name],
            capture_output=True,
            check=False,
        )

    # ── Test 1: task creation produces a cmd /c wrapper ───────────────
    @_skip_unless_ready
    def test_create_task_registers_with_cmd_wrapper(self):
        """
        create_update_task() must produce a task whose action contains
        cmd /c so that the & operator is interpreted by the shell.
        Verifies the schtasks /Query /XML output contains the full
        stop-and-start chain.
        """
        msgs: list[str] = []
        logic.create_update_task(log=msgs.append)

        assert _task_exists(self.task_name), (
            "Task was not created by create_update_task()"
        )
        assert any("Task" in m for m in msgs), (
            "Expected success message in log"
        )

        # Inspect the task XML to confirm the command is correct.
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", self.task_name,
             "/XML", "ONE"],
            capture_output=True, encoding="utf-8", errors="replace",
            check=False,
        )
        xml = r.stdout
        assert "cmd" in xml.lower(), (
            "cmd not found in task XML – /TR wrapper missing"
        )
        assert f"sc.exe stop {logic.SERVICE_NAME}".lower() in xml.lower()
        assert f"sc.exe start {logic.SERVICE_NAME}".lower() in xml.lower()
        # stop must appear before start in the command string
        assert xml.lower().index("sc.exe stop") < xml.lower().index(
            "sc.exe start"
        ), "sc.exe stop must precede sc.exe start in the task command"

    # ── Test 2: scheduled restart actually stops and restarts the EXE ─
    @_skip_unless_ready
    def test_service_restarts_at_scheduled_time(self):
        """
        Schedule the task 2 minutes from now (ONCE trigger), wait for
        the service to go down, then come back up, and verify HTTP 200.

        Timeline:
          T+0   Task registered with trigger = now + 2 min
          T+120 Task Scheduler fires – sc.exe stop runs
          T+125 timeout /t 5 elapses – sc.exe start runs
          T+145 service is up; HTTP 200 expected
        """
        port = _get_service_port()

        # Precondition: service is already up
        assert _wait_http_200(port, timeout=15), (
            "Service did not respond before the test started – "
            "is it running?"
        )

        trigger = datetime.now() + timedelta(minutes=2)
        result = _create_task_at(trigger)
        assert result.returncode == 0, (
            f"schtasks /Create failed: {result.stderr.strip()}"
        )
        assert _task_exists(self.task_name)

        # Wait for the service to go down (Task Scheduler fires at T+2 min).
        # Allow up to 3.5 min total for the trigger + sc.exe stop to complete.
        print(
            f"\n  Waiting for service to stop (trigger at "
            f"{trigger.strftime('%H:%M')}) ..."
        )
        went_down = _wait_http_down(port, timeout=210)
        assert went_down, (
            "Service did not stop within 3.5 minutes – "
            "Task Scheduler may not have fired or sc.exe stop failed"
        )

        # Wait for the service to come back (sc.exe start + boot time).
        print("  Service stopped – waiting for restart ...")
        came_back = _wait_http_200(port, timeout=90)
        assert came_back, (
            "Service did not restart within 90 seconds after stopping – "
            "sc.exe start in the task command likely failed "
            "(cmd /c wrapper regression?)"
        )

    # ── Test 3: uninstall removes the task ────────────────────────────
    @_skip_unless_ready
    def test_remove_scheduled_task_deletes_it(self):
        """
        remove_scheduled_task() must delete the schtasks entry so the
        service is not restarted after uninstallation.
        """
        # Create the task first so there is something to remove.
        msgs_create: list[str] = []
        logic.create_update_task(log=msgs_create.append)
        assert _task_exists(self.task_name), (
            "Task not created – cannot test removal"
        )

        msgs_remove: list[str] = []
        logic.remove_scheduled_task(log=msgs_remove.append)

        assert not _task_exists(self.task_name), (
            "Task still exists after remove_scheduled_task() – "
            "uninstall would leave a dangling restart schedule"
        )
        assert any("✓" in m or "entfernt" in m for m in msgs_remove), (
            "Expected success message in remove log"
        )

    # ── Test 4: remove is idempotent (task already gone) ──────────────
    @_skip_unless_ready
    def test_remove_scheduled_task_is_idempotent(self):
        """
        Calling remove_scheduled_task() when the task does not exist must
        not raise and must log a friendly info message.
        """
        # Guarantee the task is absent before the call.
        subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", self.task_name],
            capture_output=True,
            check=False,
        )

        msgs: list[str] = []
        logic.remove_scheduled_task(log=msgs.append)

        assert not _task_exists(self.task_name)
        assert any("ℹ" in m for m in msgs), (
            "Expected informational message when task was already absent"
        )
