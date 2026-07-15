"""
Shared infrastructure for the Release Acceptance Test.

Contains:
  - Global test state (_failures, _warnings, _counters)
  - Test reporter (_check, _dump_diag, _poll_list, _section)
  - HTTP helpers (_get, _post, _wait_http_up, _wait_http_down, _get_csrf,
                  _delete_by_plate)
  - Process helpers (_run_installer, _start_app, _stop_app)
  - Windows OS helpers (_service_state, _service_start_type, _service_exists,
                        _task_exists, _firewall_rule_exists, _is_admin)
  - SQLite helpers (_make_valid_db, _make_db_missing_table, _wal_checkpoint)
"""
from __future__ import annotations

import http.cookiejar
import io
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

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
    name: str, ok: bool, detail: str = "", *, warn: bool = False,
    diag: bytes | str | None = None,
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
        if diag is not None:
            _dump_diag(diag)
    return ok


def _dump_diag(data: bytes | str, *, max_chars: int = 1000) -> None:
    """Print a truncated snippet of *data* to help diagnose a failure.

    Strips surrounding HTML boilerplate (keeps flash messages and data rows)
    so the useful content is visible at a glance.
    """
    if isinstance(data, bytes):
        text = data.decode("utf-8", errors="replace")
    else:
        text = str(data)
    text = text.strip()
    if not text:
        print("  │ (empty response body)", flush=True)
        return
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n  … [{len(text) - max_chars} more chars truncated]"
    print("  ┌─ response body ─────────────────────────────", flush=True)
    for line in text.splitlines()[:30]:
        print(f"  │ {line}", flush=True)
    print("  └─────────────────────────────────────────────", flush=True)


def _poll_list(base: str, search: bytes, *,
               retries: int = 3, delay: float = 0.5) -> tuple[bool, bytes]:
    """GET /wheelsets up to *retries* times until *search* appears.

    Returns (found, last_body).  The delay gives SQLite time to flush the
    WAL to the main database file between the POST commit and the read.
    """
    body = b""
    for _ in range(retries):
        _, body = _get(base, "/wheelsets")
        if search in body:
            return True, body
        time.sleep(delay)
    return False, body


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


def _delete_by_plate(base: str, plate: str) -> None:
    """Delete any wheelset with *plate* from the DB (idempotent pre-test cleanup).

    Silently does nothing if the plate is not present.
    This ensures repeated RAT runs do not fail due to leftover data.
    """
    _, list_body = _get(base, "/wheelsets")
    for wid_b in re.findall(rb"/wheelsets/(\d+)/edit", list_body):
        wid = wid_b.decode()
        _, edit_body = _get(base, f"/wheelsets/{wid}/edit")
        if plate.encode() in edit_body:
            csrf = _get_csrf(base)
            _post(base, f"/wheelsets/{wid}/delete", {
                "_csrf_token": csrf,
                "confirm_plate": plate,
            })
            return


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
    source_db: Path | None = None,
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


def _service_start_type() -> str:
    """Return the START_TYPE string for the service (e.g. 'AUTO_START').

    Uses ``sc.exe qc`` (query config) rather than ``sc.exe query``
    (runtime state).  Returns an empty string if the service does not
    exist or the field is absent.
    """
    r = subprocess.run(
        ["sc.exe", "qc", SERVICE_NAME],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    for line in r.stdout.splitlines():
        if "START_TYPE" in line:
            # typical line: "        START_TYPE         : 2  AUTO_START"
            return line.split(":")[-1].strip()
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


def _wal_checkpoint(db_path: Path) -> bool:
    """Force-merge the WAL file into the main SQLite database.

    Must be called when no other process holds a lock on the DB
    (i.e. after the app / service has fully exited).  This ensures
    all committed rows are written to the main .db file and the
    -wal / -shm files are cleaned up.

    Retries up to 5 times with a 1-second sleep between attempts to
    handle Windows' delayed file-handle release after TerminateProcess.

    Returns True if the checkpoint succeeded, False otherwise.
    """
    if not db_path.exists():
        print(f"    _wal_checkpoint: DB not found: {db_path}", flush=True)
        return False
    wal_path = db_path.parent / (db_path.name + "-wal")
    if not wal_path.exists():
        # No WAL file → nothing to checkpoint (data already in main DB)
        return True
    print(f"    _wal_checkpoint: WAL exists ({wal_path.stat().st_size} bytes)"
          f" – merging into {db_path.name}", flush=True)
    for attempt in range(1, 6):
        try:
            con = sqlite3.connect(str(db_path))
            result = con.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
            con.close()
            # result = (blocked, wal_pages, checkpointed_pages)
            if result and result[0] == 0:
                print(f"    _wal_checkpoint: OK on attempt {attempt} "
                      f"(pages: {result[1]}/{result[2]})", flush=True)
                return True
            # blocked=1 means another connection held a lock
            print(f"    _wal_checkpoint: blocked on attempt {attempt} "
                  f"(result={result})", flush=True)
        except sqlite3.Error as exc:
            print(f"    _wal_checkpoint: attempt {attempt} failed: {exc}",
                  flush=True)
        time.sleep(1)
    print("    _wal_checkpoint: FAILED after 5 attempts", flush=True)
    return False


# ══════════════════════════════════════════════════════════════════════
# Phase 1 – App EXE standalone
# ══════════════════════════════════════════════════════════════════════
