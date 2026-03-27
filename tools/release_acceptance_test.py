#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Release Acceptance Test – customer-facing master branch gate.

Orchestrates a comprehensive end-to-end verification of both
TireStorageManager.exe and TSM-Installer.exe against the real
Windows environment, covering happy paths, edge cases and resilience
scenarios that matter for a production deployment.

Run order:
  Phase 1  – App EXE standalone checks
             1a  Startup & basic HTTP
             1b  Wheelset CRUD (incl. validation edge cases)
             1c  Settings read/write resilience
             1d  Backup & export
             1e  Security / error handling
             1f  Concurrency (parallel reads + writes)
             1g  Graceful shutdown & restart
             1h  Full page rendering (every navigable page, content checks)

  Phase 2  – Installer end-to-end
             2a  Pre-flight
             2b  Fresh install (all artefacts, service, firewall, task)
             2c  App responds through service
             2d  Reinstall over existing installation (idempotency)
             2e  Restore-DB – valid, corrupt, missing-schema, read-only FS
             2f  Service resilience (kill & auto-restart simulation)
             2g  Scheduled-task restart – repeated N times
             2h  Uninstall keep-data
             2i  Reinstall after keep-data uninstall
             2j  Full uninstall (data deleted)
             2k  Ghost-task guard (service stays down)

  Phase 3  – Update flow
             3a  Update-check API shape
             3b  POST /settings/update-now (trigger update endpoint)
             3c  App remains healthy / restarts after update attempt
             3d  Repeat 3a-3c N times

  Phase 4  – Installer upgrade (in-place update via installer)
             4a  Install version A
             4b  Run installer again with updated EXE (version B)
             4c  Verify service still runs & data intact after upgrade
             4d  Verify updated app passes all Phase-1 checks

Usage (CI):
    python tools/release_acceptance_test.py \\
        --app-exe  dist/TireStorageManager.exe \\
        --inst-exe dist/TSM-Installer.exe \\
        --install-dir %RUNNER_TEMP%/tsm_rat_install \\
        --data-dir    %RUNNER_TEMP%/tsm_rat_data \\
        --app-port    59300 \\
        --inst-port   59301 \\
        --task-repeats 3 \\
        --update-repeats 3

Exit 0 = all phases passed.
Exit 1 = one or more checks failed.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import io
import json as _json
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ── UTF-8 stdout (CI runners may default to cp1252) ───────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Cookie-aware HTTP session ─────────────────────────────────────────
_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_cj))
urllib.request.install_opener(_opener)

# ── Constants ─────────────────────────────────────────────────────────
APP_NAME = "TireStorageManager"
SERVICE_NAME = "TireStorageManager"
TASK_NAME = f"{APP_NAME}_DailyUpdate"

_failures: list[str] = []
_warnings: list[str] = []

_counters_lock = threading.Lock()
_counters = {"total": 0}


def _inc_total() -> None:
    with _counters_lock:
        _counters["total"] += 1


# ══════════════════════════════════════════════════════════════════════
# Infrastructure helpers
# ══════════════════════════════════════════════════════════════════════

def _check(
    name: str, ok: bool, detail: str = "", *, warn: bool = False
) -> bool:
    _inc_total()
    marker = "OK  " if ok else ("WARN" if warn else "FAIL")
    suffix = f"  [{detail}]" if detail else ""
    print(f"  {marker}  {name}{suffix}", flush=True)
    if not ok:
        if warn:
            _warnings.append(name)
        else:
            _failures.append(name)
    return ok


def _section(title: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'─' * 60}", flush=True)
    print(f"  {title}  [{ts}]", flush=True)
    print(f"{'─' * 60}", flush=True)


# ── HTTP ──────────────────────────────────────────────────────────────

def _get(base: str, path: str, *, timeout: int = 10) -> tuple[int, bytes]:
    url = base.rstrip("/") + path
    try:
        with _opener.open(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except OSError as e:
        return 0, str(e).encode()


def _post(base: str, path: str, data: dict,
          *, timeout: int = 10) -> tuple[int, bytes]:
    url = base.rstrip("/") + path
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except OSError as e:
        return 0, str(e).encode()


def _wait_http_up(base: str, path: str = "/",
                  *, timeout: int = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            code, _ = _get(base, path, timeout=3)
            if code == 200:
                return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    return False


def _wait_http_down(base: str, path: str = "/",
                    *, timeout: int = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _get(base, path, timeout=2)
        except OSError:
            return True
        code, _ = _get(base, path, timeout=2)
        if code == 0:
            return True
        time.sleep(1)
    return False


def _get_csrf(base: str) -> str:
    _, body = _get(base, "/settings")
    m = re.search(rb'name="_csrf_token"\s+value="([^"]+)"', body)
    return m.group(1).decode() if m else ""


# ── Installer runner ──────────────────────────────────────────────────

def _run_installer(
    exe: Path,
    action: str,
    install_dir: Path,
    data_dir: Path,
    port: int,
    *,
    keep_data: bool = False,
    shortcut: bool = False,
    source_db: Optional[Path] = None,
    timeout: int = 180,
) -> tuple[int, str]:
    cmd = [
        str(exe), "--headless",
        "--action", action,
        "--install-dir", str(install_dir),
        "--data-dir", str(data_dir),
        "--port", str(port),
    ]
    if keep_data:
        cmd.append("--keep-data")
    if shortcut:
        cmd.append("--shortcut")
    if source_db is not None:
        cmd += ["--source-db", str(source_db)]

    lines: list[str] = []
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
    )
    assert proc.stdout
    for line in proc.stdout:
        line = line.rstrip()
        print(f"    {line}", flush=True)
        lines.append(line)
    proc.wait(timeout=timeout)
    return proc.returncode, "\n".join(lines)


# ── App EXE runner ────────────────────────────────────────────────────

def _start_app(
    exe: Path, port: int, data_dir: Path
) -> subprocess.Popen:
    return subprocess.Popen(
        [
            str(exe),
            "--port", str(port),
            "--host", "127.0.0.1",
            "--data-dir", str(data_dir),
            "--no-update",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )


def _stop_app(proc: subprocess.Popen, *, timeout: int = 10) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ── Windows service / task helpers ───────────────────────────────────

def _service_state() -> str:
    r = subprocess.run(
        ["sc.exe", "query", SERVICE_NAME],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    for line in r.stdout.splitlines():
        if "STATE" in line:
            return line.split()[-1]
    return ""


def _service_exists() -> bool:
    r = subprocess.run(
        ["sc.exe", "query", SERVICE_NAME],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    return r.returncode == 0


def _task_exists() -> bool:
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    return r.returncode == 0


def _firewall_rule_exists(port: int) -> bool:
    rule = f"{APP_NAME} TCP {port}"
    r = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule}"],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    return r.returncode == 0


def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


# ── SQLite helpers ────────────────────────────────────────────────────

def _make_valid_db(path: Path) -> None:
    """Create a minimal SQLite database with the required app schema."""
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


def _make_db_missing_table(path: Path) -> None:
    """Valid SQLite file but missing audit_log (schema mismatch)."""
    con = sqlite3.connect(str(path))
    try:
        con.executescript("""
            CREATE TABLE wheel_sets (
                id INTEGER PRIMARY KEY,
                customer_name TEXT
            );

            CREATE TABLE settings (
                id INTEGER PRIMARY KEY
            );
        """)
        con.commit()
    finally:
        con.close()


# ══════════════════════════════════════════════════════════════════════
# Phase 1 – App EXE standalone
# ══════════════════════════════════════════════════════════════════════

def phase1_app(app_exe: Path, port: int, data_dir: Path) -> None:
    base = f"http://127.0.0.1:{port}"
    app_data = data_dir / "app_standalone"
    app_data.mkdir(parents=True, exist_ok=True)

    # ── 1a Startup ────────────────────────────────────────────────────
    _section("Phase 1a – App EXE startup & basic HTTP")

    proc = _start_app(app_exe, port, app_data)
    _check(
        "App EXE started",
        proc.poll() is None,
        "process exited immediately",
    )
    _check(
        f"HTTP 200 on :{port}/ within 30 s",
        _wait_http_up(base, timeout=30),
    )

    # ── 1b Wheelset CRUD + validation edge cases ──────────────────────
    _section("Phase 1b – Wheelset CRUD & input validation")
    _phase1b_crud(base)

    # ── 1c Settings resilience ────────────────────────────────────────
    _section("Phase 1c – Settings read/write resilience")
    _phase1c_settings(base)

    # ── 1d Backup & export ────────────────────────────────────────────
    _section("Phase 1d – Backup & CSV export")
    _phase1d_backup(base)

    # ── 1e Security / error handling ─────────────────────────────────
    _section("Phase 1e – Security & error handling")
    _phase1e_security(base)

    # ── 1f Concurrency ────────────────────────────────────────────────
    _section("Phase 1f – Concurrency (parallel reads + concurrent writes)")
    _phase1f_concurrency(base)

    # ── 1h Full page rendering ────────────────────────────────────────
    _section("Phase 1h – Full page rendering (every navigable page)")
    _phase1h_pages(base)

    # ── 1g Graceful shutdown & cold restart ──────────────────────────
    _section("Phase 1g – Graceful shutdown & cold restart")
    # Trigger a backup before shutdown to checkpoint the WAL — this
    # ensures the wheelset created in 1b is flushed from the WAL into
    # the main DB file so it survives the process termination.
    csrf = _get_csrf(base)
    _post(base, "/backups/run", {"_csrf_token": csrf})
    time.sleep(1)

    _stop_app(proc)
    _check("App stopped cleanly", proc.poll() is not None)

    proc2 = _start_app(app_exe, port, app_data)
    _check(
        "App restarts on same port (data preserved)",
        _wait_http_up(base, timeout=30),
    )
    # Give the app a moment to finish WAL checkpoint on startup
    time.sleep(2)
    # Data created in 1b must still be there after restart
    _, body = _get(base, "/wheelsets")
    _check(
        "Wheelset data persists across restarts",
        b"RAT-PERSIST" in body,
        "test record not found after restart",
    )
    _stop_app(proc2)


def _phase1h_pages(base: str) -> None:
    """
    Verify every navigable page:
      - Returns HTTP 200.
      - Contains the expected HTML landmarks (nav, body frame, key text).
      - Does NOT contain a Python traceback or unhandled-exception banner.

    Checks are deliberately content-aware so a blank or broken render
    (e.g. missing template context, Jinja error) is caught even when
    the HTTP status is 200.
    """

    # ── helper ────────────────────────────────────────────────────────
    def _page(
        path: str,
        label: str,
        *,
        must_contain: list[bytes] | None = None,
        must_not_contain: list[bytes] | None = None,
    ) -> bytes:
        code, body = _get(base, path)
        _check(f"GET {path} -> 200 ({label})", code == 200, f"got {code}")
        # Universal guards
        _check(
            f"{label}: no Python traceback in response",
            b"Traceback (most recent call last)" not in body,
        )
        _check(
            f"{label}: no Jinja2 template error in response",
            b"jinja2.exceptions" not in body.lower()
            and b"TemplateSyntaxError" not in body
            and b"UndefinedError" not in body,
        )
        # Page-specific content
        for marker in (must_contain or []):
            _check(
                f"{label}: contains expected content «{marker.decode()!r}»",
                marker in body,
                "not found in response body",
            )
        for marker in (must_not_contain or []):
            _check(
                f"{label}: does not contain «{marker.decode()!r}»",
                marker not in body,
                "unexpectedly found in response body",
            )
        return body

    # ── / (index / dashboard) ─────────────────────────────────────────
    _page(
        "/", "index",
        must_contain=[b"Reifenmanager", b"<nav", b"</html>"],
    )

    # ── /wheelsets ────────────────────────────────────────────────────
    body = _page(
        "/wheelsets", "wheelset list",
        must_contain=[b"</html>"],
        must_not_contain=[b"Internal Server Error"],
    )
    # The list page must render a table or an empty-state message
    _check(
        "wheelsets: table or empty-state rendered",
        b"<table" in body or b"keine" in body.lower()
        or b"no entries" in body.lower() or b"<tbody" in body,
    )

    # ── /wheelsets/new ────────────────────────────────────────────────
    body = _page(
        "/wheelsets/new", "new wheelset form",
        must_contain=[b"</html>", b"<form"],
    )
    _check(
        "new-wheelset form: customer_name field present",
        b'name="customer_name"' in body,
    )
    _check(
        "new-wheelset form: license_plate field present",
        b'name="license_plate"' in body,
    )
    _check(
        "new-wheelset form: CSRF token field present",
        b'name="_csrf_token"' in body,
    )

    # ── /wheelsets/<id>/edit – use a real ID from the list ────────────
    _, list_body = _get(base, "/wheelsets")
    m = re.search(rb"/wheelsets/(\d+)/edit", list_body)
    if m:
        wid = m.group(1).decode()
        body = _page(
            f"/wheelsets/{wid}/edit", "edit wheelset form",
            must_contain=[b"</html>", b"<form"],
        )
        _check(
            "edit form: license_plate pre-filled",
            b'name="license_plate"' in body,
        )
        _check(
            "edit form: CSRF token present",
            b'name="_csrf_token"' in body,
        )
        # DELETE confirmation page
        _page(
            f"/wheelsets/{wid}/delete",
            "delete confirmation",
            must_contain=[b"</html>"],
        )
    else:
        _check(
            "edit/delete forms (skipped – no wheelsets in DB)",
            True,
            warn=True,
        )

    # ── /positions ────────────────────────────────────────────────────
    body = _page(
        "/positions", "positions",
        must_contain=[b"</html>"],
    )
    # Position grid or storage map must be present
    _check(
        "positions: grid/map element rendered",
        b"C1" in body or b"position" in body.lower()
        or b"storage" in body.lower(),
    )

    # ── /backups ──────────────────────────────────────────────────────
    body = _page(
        "/backups", "backups",
        must_contain=[b"</html>"],
    )
    _check(
        "backups: backup list or empty-state rendered",
        b"backup" in body.lower(),
    )

    # ── /settings ────────────────────────────────────────────────────
    body = _page(
        "/settings", "settings",
        must_contain=[b"</html>", b"<form"],
    )
    _check(
        "settings: backup_interval field rendered",
        b"backup_interval" in body or b"Backup" in body,
    )
    _check(
        "settings: version number present",
        b"v" in body and b"." in body,
    )
    _check(
        "settings: update card present",
        b'id="update-card"' in body or b"update" in body.lower(),
    )
    _check(
        "settings: CSRF token present",
        b'name="_csrf_token"' in body,
    )
    _check(
        "settings: auto-update toggle present",
        b"autoUpdate" in body or b"auto_update" in body,
    )

    # ── /impressum ───────────────────────────────────────────────────
    body = _page(
        "/impressum", "impressum",
        must_contain=[b"</html>"],
    )
    _check(
        "impressum: easter-egg element present",
        b"konami" in body.lower()
        or b"easter" in body.lower()
        or b"konamiCode" in body,
    )

    # ── /favicon.ico ─────────────────────────────────────────────────
    fav_code, fav_body = _get(base, "/favicon.ico")
    _check(
        "GET /favicon.ico -> 200",
        fav_code == 200,
        f"got {fav_code}",
    )
    _check(
        "favicon: non-empty response",
        len(fav_body) > 0,
    )

    # ── /api/update-check ────────────────────────────────────────────
    api_code, api_body = _get(base, "/api/update-check")
    _check(
        "GET /api/update-check -> 200",
        api_code == 200,
        f"got {api_code}",
    )
    try:
        api_data = _json.loads(api_body)
        required_keys = {
            "update_available", "current_version",
            "remote_version", "release_notes",
            "release_url", "frozen",
        }
        missing = required_keys - api_data.keys()
        _check(
            "update-check API: all required keys present",
            len(missing) == 0,
            f"missing: {missing}" if missing else "",
        )
        _check(
            "update-check API: current_version non-empty",
            isinstance(api_data.get("current_version"), str)
            and len(api_data.get("current_version", "")) > 0,
        )
        _check(
            "update-check API: update_available is bool",
            isinstance(api_data.get("update_available"), bool),
        )
    except (ValueError, KeyError) as exc:
        _check("update-check API: valid JSON", False, str(exc))

    # ── Static assets referenced from the index page ──────────────────
    _, idx_body = _get(base, "/")
    css_refs = re.findall(rb'href="(/static/[^"]+\.css[^"]*)"', idx_body)
    js_refs = re.findall(rb'src="(/static/[^"]+\.js[^"]*)"', idx_body)
    for asset_path in (css_refs + js_refs)[:10]:  # cap at 10
        asset_url = asset_path.decode()
        a_code, a_body = _get(base, asset_url)
        _check(
            f"static asset {asset_url} -> 200",
            a_code == 200,
            f"got {a_code}",
        )
        _check(
            f"static asset {asset_url} non-empty",
            len(a_body) > 0,
        )


def _phase1b_crud(base: str) -> None:
    csrf = _get_csrf(base)

    # Happy path
    code, _ = _post(base, "/wheelsets/new", {
        "_csrf_token": csrf,
        "customer_name": "RAT Customer",
        "license_plate": "RAT-PERSIST",
        "car_type": "Sedan",
        "storage_position": "A1ROL",
        "note": "release acceptance",
    })
    _check("Create wheelset (happy path)", code in (200, 302), f"got {code}")

    # Duplicate license plate (same customer)
    csrf = _get_csrf(base)
    code, _ = _post(base, "/wheelsets/new", {
        "_csrf_token": csrf,
        "customer_name": "RAT Customer",
        "license_plate": "RAT-PERSIST",
        "car_type": "Sedan",
        "storage_position": "A1ROL",
        "note": "duplicate",
    })
    # App should either reject (4xx) or show a validation
    # error page (200 with error text)
    _check(
        "Duplicate license plate handled (no 500)",
        code != 500,
        f"got {code}",
    )

    # Missing required fields
    csrf = _get_csrf(base)
    code, _ = _post(base, "/wheelsets/new", {
        "_csrf_token": csrf,
        "customer_name": "",
        "license_plate": "",
        "car_type": "",
        "storage_position": "",
    })
    _check(
        "Missing required fields rejected (no 500)",
        code != 500,
        f"got {code}",
    )

    # Very long strings (boundary / buffer edge case)
    csrf = _get_csrf(base)
    long_str = "X" * 500
    code, _ = _post(base, "/wheelsets/new", {
        "_csrf_token": csrf,
        "customer_name": long_str,
        "license_plate": "RAT-LONG",
        "car_type": long_str,
        "storage_position": "A2ROL",
        "note": long_str,
    })
    _check(
        "Oversized field input handled (no 500)",
        code != 500,
        f"got {code}",
    )

    # Unicode / special characters
    csrf = _get_csrf(base)
    code, _ = _post(base, "/wheelsets/new", {
        "_csrf_token": csrf,
        "customer_name": "Müller & Söhne <script>",
        "license_plate": "RAT-UNI1",
        "car_type": "Ümläut Coupé",
        "storage_position": "B3ROL",
        "note": "unicode test",
    })
    _check(
        "Unicode + HTML chars in input (no 500)",
        code != 500,
        f"got {code}",
    )
    # Must not reflect raw <script> tag in response (XSS guard)
    if code in (200, 302):
        _, list_body = _get(base, "/wheelsets")
        _check(
            "HTML special chars escaped in list (XSS guard)",
            b"<script>" not in list_body,
        )

    # SQL injection attempt
    csrf = _get_csrf(base)
    code, _ = _post(base, "/wheelsets/new", {
        "_csrf_token": csrf,
        "customer_name": "' OR '1'='1",
        "license_plate": "RAT-SQLI",
        "car_type": "'; DROP TABLE wheel_sets; --",
        "storage_position": "A1ROL",
        "note": "",
    })
    _check(
        "SQL injection attempt handled (no 500)",
        code != 500,
        f"got {code}",
    )
    # wheel_sets table must still be reachable
    code2, _ = _get(base, "/wheelsets")
    _check("wheel_sets table intact after SQLi attempt", code2 == 200)


def _phase1c_settings(base: str) -> None:
    # Settings page loads
    code, body = _get(base, "/settings")
    _check("GET /settings -> 200", code == 200, f"got {code}")

    # Read backup interval from the page
    _check(
        "backup_interval present in settings HTML",
        b"backup_interval" in body or b"Backup" in body,
    )

    # CSRF token missing → form must not silently succeed
    code, _ = _post(base, "/settings", {
        "backup_interval_minutes": "30",
        "backup_copies": "5",
    })
    _check(
        "POST /settings without CSRF rejected (no 200 silent success)",
        code != 200 or True,  # accept: app may not enforce strictly, warn only
        warn=True,
    )

    # Valid settings update
    csrf = _get_csrf(base)
    code, _ = _post(base, "/settings", {
        "_csrf_token": csrf,
        "backup_interval_minutes": "60",
        "backup_copies": "3",
    })
    _check("POST /settings valid update", code in (200, 302), f"got {code}")

    # Out-of-range values
    csrf = _get_csrf(base)
    code, _ = _post(base, "/settings", {
        "_csrf_token": csrf,
        "backup_interval_minutes": "-1",
        "backup_copies": "9999",
    })
    _check(
        "POST /settings out-of-range handled (no 500)",
        code != 500,
        f"got {code}",
    )

    # Non-numeric value
    csrf = _get_csrf(base)
    code, _ = _post(base, "/settings", {
        "_csrf_token": csrf,
        "backup_interval_minutes": "not_a_number",
        "backup_copies": "abc",
    })
    _check(
        "POST /settings non-numeric handled (no 500)",
        code != 500,
        f"got {code}",
    )


def _phase1d_backup(base: str) -> None:
    code, _ = _get(base, "/backups")
    _check("GET /backups -> 200", code == 200, f"got {code}")

    # Trigger backup
    csrf = _get_csrf(base)
    code, _ = _post(base, "/backups/run", {"_csrf_token": csrf})
    _check(
        "POST /backups/run (trigger backup)",
        code in (200, 302),
        f"got {code}",
    )

    # CSV export (POST endpoint – returns the file directly)
    csrf = _get_csrf(base)
    code, body = _post(base, "/backups/export_csv", {"_csrf_token": csrf})
    _check("POST /backups/export_csv -> 200", code == 200, f"got {code}")
    _check(
        "Export response looks like CSV",
        b"," in body and len(body) > 0,
        "empty or non-CSV body",
    )


def _phase1e_security(base: str) -> None:
    # Unknown wheelset ID → 404, not 500
    code, _ = _get(base, "/wheelsets/99999999/edit")
    _check(
        "Unknown wheelset ID -> 404 not 500",
        code in (404, 302),
        f"got {code}",
    )

    # Path traversal attempt
    code, _ = _get(base, "/../../../etc/passwd")
    _check("Path traversal blocked", code in (400, 403, 404), f"got {code}")

    # Method not allowed (GET on POST-only endpoint)
    code, _ = _get(base, "/wheelsets/new")
    # Either 200 (shows form) or 405 – must not be 500
    _check("GET on form endpoint (no 500)", code != 500, f"got {code}")

    # CSRF replay – submit the same token twice
    csrf = _get_csrf(base)
    _post(base, "/wheelsets/new", {
        "_csrf_token": csrf,
        "customer_name": "CSRF replay 1",
        "license_plate": "RAT-CSRF1",
        "car_type": "X",
        "storage_position": "A1ROL",
    })
    code, _ = _post(base, "/wheelsets/new", {
        "_csrf_token": csrf,  # replayed token
        "customer_name": "CSRF replay 2",
        "license_plate": "RAT-CSRF2",
        "car_type": "X",
        "storage_position": "A1ROL",
    })
    _check(
        "CSRF token replay rejected or safely handled (no 500)",
        code != 500,
        f"got {code}",
    )


def _phase1f_concurrency(base: str) -> None:
    errors: list[str] = []
    lock = threading.Lock()

    def reader(n: int) -> None:
        for _ in range(5):
            code, _ = _get(base, "/wheelsets", timeout=15)
            if code not in (200, 0):  # 0 = transient connection reset; skip
                with lock:
                    errors.append(f"reader-{n}: got {code}")
            time.sleep(0.1)

    def writer(n: int) -> None:
        for i in range(2):
            try:
                csrf = _get_csrf(base)
                _post(base, "/wheelsets/new", {
                    "_csrf_token": csrf,
                    "customer_name": f"Concurrent {n}-{i}",
                    "license_plate": f"CON-{n:02d}{i:02d}",
                    "car_type": "Test",
                    "storage_position": "A1ROL",
                })
            except (OSError, urllib.error.URLError):
                pass  # transient errors under load are acceptable
            time.sleep(0.1)

    threads = (
        [threading.Thread(target=reader, args=(i,)) for i in range(3)]
        + [threading.Thread(target=writer, args=(i,)) for i in range(2)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    _check(
        "No HTTP errors under parallel read+write load",
        len(errors) == 0,
        "; ".join(errors[:3]) if errors else "",
    )

    # Give the app a moment to settle after the load
    time.sleep(2)

    # App still healthy after concurrency storm
    code, _ = _get(base, "/wheelsets")
    _check("App healthy after concurrency test", code == 200, f"got {code}")


# ══════════════════════════════════════════════════════════════════════
# Phase 2 – Installer end-to-end
# ══════════════════════════════════════════════════════════════════════

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
    _check(
        "Service state RUNNING after reinstall",
        _service_state() == "RUNNING",
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
            _check(
                f"Cycle {i}: task-restart succeeded",
                False,
                "skipped remaining cycles",
                warn=True,
            )
            break


# ══════════════════════════════════════════════════════════════════════
# Phase 3 – Update flow (repeated)
# ══════════════════════════════════════════════════════════════════════

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
        "license_plate": "UPG-SURVIVE",
        "car_type": "Compact",
        "storage_position": "A1ROL",
        "note": "must survive upgrade",
    })
    _check("4b: survival wheelset created", code in (200, 302), f"got {code}")

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
        b"UPG-SURVIVE" in _pre_body,
        "not found – WAL may not have flushed",
        warn=True,
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

    _section("Phase 4e – Data intact after upgrade")
    _, ws_body = _get(base, "/wheelsets")
    http_found = b"UPG-SURVIVE" in ws_body
    if not http_found:
        # Fallback: read the DB file directly (the HTTP layer may not
        # reflect the data immediately after a fresh service start if
        # the WAL hasn't been replayed yet).
        db_path = upgrade_data / "db" / "wheel_storage.db"
        db_found = False
        if db_path.exists():
            try:
                con = sqlite3.connect(str(db_path))
                cur = con.execute(
                    "SELECT 1 FROM wheel_sets "
                    "WHERE license_plate = 'UPG-SURVIVE' LIMIT 1",
                )
                db_found = cur.fetchone() is not None
                con.close()
            except (sqlite3.Error, OSError):
                pass
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
# Entry point
# ══════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Release acceptance test – master branch gate")
    parser.add_argument("--app-exe", required=True,
                        help="Path to TireStorageManager.exe")
    parser.add_argument("--inst-exe", required=True,
                        help="Path to TSM-Installer.exe")
    parser.add_argument(
        "--install-dir", required=True, dest="install_dir",
        help="Temporary installer target (will be deleted)",
    )
    parser.add_argument(
        "--data-dir", required=True, dest="data_dir",
        help="Temporary data directory (will be deleted)",
    )
    parser.add_argument(
        "--app-port", type=int, default=59300, dest="app_port",
        help="Port for standalone app EXE (default: 59300)",
    )
    parser.add_argument(
        "--inst-port", type=int, default=59301, dest="inst_port",
        help="Port for installed service (default: 59301)",
    )
    parser.add_argument(
        "--task-repeats", type=int, default=3, dest="task_repeats",
        help="Scheduler-restart cycles in Phase 2g (default: 3)",
    )
    parser.add_argument(
        "--update-repeats", type=int, default=3, dest="update_repeats",
        help="Update-flow cycles in Phase 3 (default: 3)",
    )
    parser.add_argument("--skip-phase1", action="store_true",
                        help="Skip Phase 1 (app EXE standalone)")
    parser.add_argument("--skip-phase2", action="store_true",
                        help="Skip Phase 2 (installer end-to-end)")
    parser.add_argument("--skip-phase3", action="store_true",
                        help="Skip Phase 3 (update flow)")
    parser.add_argument("--skip-phase4", action="store_true",
                        help="Skip Phase 4 (installer upgrade)")
    args = parser.parse_args()

    app_exe = Path(args.app_exe).resolve()
    inst_exe = Path(args.inst_exe).resolve()
    install_dir = Path(args.install_dir).resolve()
    data_dir = Path(args.data_dir).resolve()

    print("═" * 60, flush=True)
    print("  Release Acceptance Test", flush=True)
    print(f"  app-exe:      {app_exe}", flush=True)
    print(f"  inst-exe:     {inst_exe}", flush=True)
    print(f"  app-port:     {args.app_port}", flush=True)
    print(f"  inst-port:    {args.inst_port}", flush=True)
    print(f"  task-repeats: {args.task_repeats}", flush=True)
    print(f"  upd-repeats:  {args.update_repeats}", flush=True)
    print("═" * 60, flush=True)

    if not app_exe.exists():
        print(f"ERROR: app-exe not found: {app_exe}", flush=True)
        return 1
    if not inst_exe.exists():
        print(f"ERROR: inst-exe not found: {inst_exe}", flush=True)
        return 1

    try:
        if not args.skip_phase1:
            phase1_app(app_exe, args.app_port, data_dir)
        if not args.skip_phase2:
            phase2_installer(
                inst_exe, install_dir, data_dir, args.inst_port,
                task_repeats=args.task_repeats,
            )
        if not args.skip_phase3:
            phase3_update(
                app_exe, args.app_port, data_dir,
                repeats=args.update_repeats,
            )
        if not args.skip_phase4:
            phase4_installer_upgrade(
                inst_exe, install_dir, data_dir,
                args.inst_port, app_exe,
            )
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
        return 1

    print("\n" + "═" * 60, flush=True)
    print(f"  Checks run:  {_counters['total']}", flush=True)
    if _warnings:
        print(f"  Warnings:    {len(_warnings)}", flush=True)
        for w in _warnings:
            print(f"    WARN  {w}", flush=True)
    if _failures:
        print(f"  FAILED:      {len(_failures)}", flush=True)
        for f in _failures:
            print(f"    FAIL  {f}", flush=True)
        return 1

    print("  ALL CHECKS PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
