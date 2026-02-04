#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Lightweight auto-updater for TireStorage Manager (Windows friendly)

- Compares local VERSION in config.py to remote (GitHub branch)
- If different: downloads branch ZIP, overlays code files
  (preserve DB/backups/.venv)
- Exits 0 (no update), 10 (updated), or >0 (non-fatal error
  -> caller may continue)
"""

# ========================================================
# IMPORTS
# ========================================================
import os
import re
import io
import sys
import time
import urllib.request
import urllib.error
import zipfile
import tempfile
import json

# ========================================================
# GLOBALS
# ========================================================
OWNER = os.environ.get("TSM_GH_OWNER", "tombo92")
REPO = os.environ.get("TSM_GH_REPO", "TireStorageManager")
BRANCH = os.environ.get("TSM_GH_BRANCH", "master")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # optional to avoid rate limits

# [1] Raw file URL for config.py to read VERSION
RAW_BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}"
RAW_URL = f"{RAW_BASE}/config.py"
# [2] Branch ZIP
ZIP_URL = f"https://github.com/{OWNER}/{REPO}/archive/refs/heads/{BRANCH}.zip"
# [3] Latest commit on branch
COMMITS_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/commits/{BRANCH}"

HERE = os.path.abspath(os.path.dirname(__file__))
APP_FILE = os.path.join(HERE, "config.py")

# Include common source and template/static assets (but not DB/backups)
INCLUDE_PATTERNS = (
    ".py", ".cmd", ".bat", ".ps1",
    ".html", ".jinja", ".jinja2",
    ".css", ".js",
    "requirements.txt",
    ".txt", ".md", ".ini", ".cfg", ".json",
)

VERSION_RX = re.compile(r'^\s*VERSION\s*=\s*"([^"]+)"', re.MULTILINE)


# ========================================================
# Functions
# ========================================================
def log(msg: str):
    print(f"[updater] {msg}")


def _make_request(url: str,
                  headers: dict | None = None) -> urllib.request.Request:
    base_headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "TSM-Updater/1.1",
    }
    if headers:
        base_headers.update(headers)
    # Optional GitHub token
    if GITHUB_TOKEN and "Authorization" not in base_headers:
        base_headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return urllib.request.Request(url, headers=base_headers)


def read_local_version(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            m = VERSION_RX.search(f.read())
            return m.group(1) if m else None
    except Exception:
        return None


def fetch_text_nocache(url: str, timeout=15) -> str | None:
    """
    Fetch text from URL with cache-buster query and 'no-cache' headers to
    avoid CDN caching.
    """
    ts = int(time.time())
    sep = "&" if "?" in url else "?"
    nocache_url = f"{url}{sep}ts={ts}"
    req = _make_request(nocache_url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log(f"WARN: fetch_text_nocache failed for {url}: {e}")
        return None


def fetch_remote_version_via_raw() -> str | None:
    data = fetch_text_nocache(RAW_URL)
    if not data:
        return None
    m = VERSION_RX.search(data)
    if m:
        return m.group(1)
    log("WARN: VERSION not found in raw; preview:\n" + data[:200])
    return None


def fetch_zip_bytes() -> bytes:
    ts = int(time.time())
    sep = "&" if "?" in ZIP_URL else "?"
    url = f"{ZIP_URL}{sep}ts={ts}"
    req = _make_request(url, headers={"Accept": "application/zip"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _read_config_version_from_zip(zf: zipfile.ZipFile) -> str | None:
    """
    Try to read VERSION from config.py inside the archive.
    """
    # Find a path ending with /config.py or config.py at root
    candidates = [n for n in zf.namelist() if n.endswith("/config.py") or
                  n.endswith("config.py")]
    # Prefer the shortest candidate (likely root/app root)
    candidates.sort(key=len)
    for name in candidates:
        try:
            data = zf.read(name).decode("utf-8", errors="ignore")
            m = VERSION_RX.search(data)
            if m:
                return m.group(1)
        except Exception:
            continue
    return None


def _fallback_scan_version_in_zip(zf: zipfile.ZipFile) -> str | None:
    """
    As a last resort, scan small text files for a VERSION line.
    This is intentionally limited for performance.
    """
    for name in zf.namelist():
        if not name.endswith((".py", ".txt", ".md",
                              ".cfg", ".ini", ".json",
                              ".html", ".js", ".css",
                              ".bat")):
            continue
        # Avoid big files
        try:
            info = zf.getinfo(name)
            if info.file_size > 256 * 1024:
                continue
            data = zf.read(name).decode("utf-8", errors="ignore")
            m = VERSION_RX.search(data)
            if m:
                return m.group(1)
        except Exception:
            continue
    return None


def extract_remote_version_from_zip(zip_bytes: bytes) -> str | None:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        v = _read_config_version_from_zip(zf)
        if v:
            return v
        return _fallback_scan_version_in_zip(zf)


def fetch_latest_commit_sha() -> str | None:
    """
    Optional: query GitHub commits endpoint to detect branch change
    (best-effort).
    """
    try:
        req = _make_request(COMMITS_URL,
                            headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            obj = json.loads(resp.read().decode("utf-8", errors="ignore"))
        # The endpoint returns a commit object for ref/branch. We use 'sha'.
        if isinstance(obj, dict) and "sha" in obj:
            return obj["sha"]
    except Exception:
        return None
    return None


def semantic_tuple(v: str) -> tuple:
    parts = re.split(r"[.-]", v.strip())
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except Exception:
            out.append(0)
    return tuple(out)


def should_update(local: str | None, remote: str | None) -> bool:
    if not remote:
        return False
    if not local:
        return True
    try:
        return semantic_tuple(remote) > semantic_tuple(local)
    except Exception:
        return remote != local


def overlay_from_zip(zip_bytes: bytes, dest_root: str) -> None:
    """
    Overlay selected files from archive to dest_root.

    Preserves DB/backups/.venv by only writing files matching INCLUDE_PATTERNS.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Detect top-level directory (e.g., "Repo-branch/")
        top = None
        for n in zf.namelist():
            if n.endswith("/") and n.count("/") == 1:
                top = n
                break
        if not top:
            top = os.path.commonprefix(zf.namelist())

        for name in zf.namelist():
            if not name.startswith(top):
                continue
            rel = name[len(top):]
            if not rel or rel.endswith("/"):
                continue
            if not any(rel.endswith(ext) for ext in INCLUDE_PATTERNS):
                continue

            # Normalize destination path
            dest_path = os.path.join(dest_root, rel)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            # Write file
            src_data = zf.read(name)
            with open(dest_path, "wb") as f:
                f.write(src_data)
            log(f"updated: {rel}")


def main() -> int:
    local_v = read_local_version(APP_FILE)
    log(f"Local VERSION: {local_v or 'n/a'}")

    remote_v = fetch_remote_version_via_raw()
    log(f"Remote VERSION (raw): {remote_v or 'n/a'}")

    # If raw says "same":
    # double-check by reading version inside ZIP to defeat caching
    if local_v and remote_v and local_v == remote_v:
        try:
            zip_bytes = fetch_zip_bytes()
            remote_v_zip = extract_remote_version_from_zip(zip_bytes)
            if remote_v_zip and remote_v_zip != remote_v:
                log(f"Remote VERSION (zip): {remote_v_zip}")
                remote_v = remote_v_zip
        except Exception as e:
            log(f"WARN: ZIP cross-check failed: {e}")

    if not should_update(local_v, remote_v):
        # Optional last resort:
        # if versions look equal but latest commit changed, just log it
        sha = fetch_latest_commit_sha()
        if sha:
            log(f"Latest branch commit SHA: {sha}")
        log("OK: no update needed.")
        return 0

    log(f"INFO: updating {local_v or 'n/a'} -> {remote_v} ...")
    try:
        zip_bytes = fetch_zip_bytes()
    except urllib.error.URLError as e:
        log(f"ERROR: download failed: {e}")
        return 2

    # Extract into temp to validate ZIP; then overlay
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(tmp)
        except zipfile.BadZipFile:
            log("ERROR: invalid ZIP from GitHub.")
            return 3
        # Overlay selected files into this project directory
        overlay_from_zip(zip_bytes, dest_root=HERE)

    log(f"OK: updated to {remote_v}.")
    return 10


# ========================================================
# MAIN
# ========================================================
if __name__ == "__main__":
    sys.exit(main())
