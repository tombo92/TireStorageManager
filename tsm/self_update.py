#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EXE self-updater for deployed TireStorageManager installations.

On every start (when running as a frozen PyInstaller EXE) this module:
  1. Checks GitHub Releases for a tag newer than the local VERSION.
  2. Downloads the new TireStorageManager.exe asset.
  3. Swaps the running EXE using a rename trick (Windows file-lock safe).
  4. Schedules a service restart so the new version takes over.

The update is skipped when:
  - Running from source (not frozen / not a .exe)
  - No network / GitHub unreachable
  - Already on the latest version
  - The --no-update flag is passed

Usage from run.py:
    from tsm.self_update import check_for_update
    check_for_update()          # blocks briefly, then returns
"""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("TSM.updater")

# ── GitHub coordinates (same env vars as tools/updater.py) ──
OWNER = os.environ.get("TSM_GH_OWNER", "tombo92")
REPO = os.environ.get("TSM_GH_REPO", "TireStorageManager")
BRANCH = os.environ.get("TSM_GH_BRANCH", "master")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

RELEASES_URL = (
    f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
)
# Fallback: raw config.py on the branch (same as tools/updater.py)
RAW_CONFIG_URL = (
    f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/config.py"
)

# The asset name we look for inside a release
ASSET_NAME = "TireStorageManager.exe"

# Service name used by NSSM
SERVICE_NAME = os.environ.get("TSM_SERVICE_NAME", "TireStorageManager")

# Timeout for HTTP requests (seconds)
HTTP_TIMEOUT = 30

# Semver regex – handles pre-release suffixes like 1.2.0-beta
_VER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_VERSION_LINE_RE = re.compile(
    r'^\s*VERSION\s*=\s*"([^"]+)"', re.MULTILINE)


# ── Helpers ──────────────────────────────────────────────
def _is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def _current_exe() -> Path:
    """Absolute path of the running .exe."""
    return Path(sys.executable).resolve()


def _ver_tuple(v: str):
    """Parse version string into comparable tuple.
    Handles pre-release suffixes (e.g. 1.2.0-beta → (1, 2, 0)).
    Falls back to splitting on [.-] like tools/updater.py.
    """
    m = _VER_RE.search(v)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # Fallback: split on dots and dashes, coerce to int
    parts = re.split(r"[.-]", v.strip())
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    # Pad to at least 3 elements for consistent comparison
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def _make_request(url: str,
                  extra_headers: dict | None = None
                  ) -> urllib.request.Request:
    """Build a Request with cache-busting headers (aligned with
    tools/updater.py) and optional GitHub auth."""
    headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "TSM-Updater/1.1",
        "Accept": "application/vnd.github+json",
    }
    if extra_headers:
        headers.update(extra_headers)
    if GITHUB_TOKEN and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return urllib.request.Request(url, headers=headers)


def _nocache_url(url: str) -> str:
    """Append a timestamp query param to defeat CDN caching."""
    ts = int(time.time())
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}ts={ts}"


def _fetch_latest_release() -> dict | None:
    """Fetch the latest GitHub Release metadata (with cache-busting)."""
    req = _make_request(_nocache_url(RELEASES_URL))
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.debug("No releases found (404).")
        else:
            log.warning("GitHub API error: %s", e)
        return None
    except Exception as e:
        log.warning("Could not reach GitHub: %s", e)
        return None


def _find_exe_asset(release: dict) -> dict | None:
    """Find the TireStorageManager.exe asset in a release."""
    for asset in release.get("assets", []):
        if asset.get("name", "").lower() == ASSET_NAME.lower():
            return asset
    return None


def _fetch_remote_version_via_raw() -> str | None:
    """Fallback: read VERSION from raw config.py on the branch
    (same approach as tools/updater.py)."""
    req = _make_request(_nocache_url(RAW_CONFIG_URL))
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = resp.read().decode("utf-8", errors="ignore")
        m = _VERSION_LINE_RE.search(data)
        if m:
            return m.group(1)
    except Exception as e:
        log.debug("Raw config.py fetch failed: %s", e)
    return None


def _download_asset(url: str, dest: Path) -> bool:
    """Download binary asset to a local file."""
    req = _make_request(
        _nocache_url(url),
        extra_headers={"Accept": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
        return True
    except Exception as e:
        log.error("Download failed: %s", e)
        return False


def _swap_exe(current: Path, new_exe: Path) -> bool:
    """
    Swap the running EXE with the new one.

    On Windows the running .exe is locked, but it CAN be renamed.
    Strategy:
      1. Rename current.exe → current.exe.old
      2. Move new_exe       → current.exe
      3. Schedule cleanup of .old on next start
    """
    old_backup = current.with_suffix(".exe.old")
    try:
        # Remove any leftover from a previous update
        if old_backup.exists():
            try:
                old_backup.unlink()
            except OSError:
                pass

        # Rename running exe out of the way
        os.rename(current, old_backup)
        log.info("Renamed running EXE -> %s", old_backup.name)

        # Put new exe in place
        os.rename(new_exe, current)
        log.info("New EXE installed -> %s", current.name)
        return True

    except OSError as e:
        log.error("EXE swap failed: %s", e)
        # Try to roll back
        if not current.exists() and old_backup.exists():
            try:
                os.rename(old_backup, current)
            except OSError:
                pass
        return False


def _restart_service():
    """Ask NSSM / sc.exe to restart the service (async)."""
    # Use cmd /c so the restart happens in a detached process;
    # the current process (old EXE) can exit cleanly.
    restart_cmd = (
        f'cmd /c "sc.exe stop {SERVICE_NAME} & '
        f'timeout /t 3 /nobreak >nul & '
        f'sc.exe start {SERVICE_NAME}"'
    )
    log.info("Scheduling service restart ...")
    # DETACHED_PROCESS and CREATE_NO_WINDOW are Windows-only constants;
    # fall back to 0 on other platforms so tests pass on Linux CI.
    _flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    try:
        subprocess.Popen(
            restart_cmd, shell=True,
            creationflags=_flags,
        )
    except Exception as e:
        log.error("Could not schedule restart: %s", e)


def _cleanup_old_exe():
    """Delete leftover .exe.old from a previous update."""
    old = _current_exe().with_suffix(".exe.old")
    if old.exists():
        try:
            old.unlink()
            log.info("Cleaned up old EXE: %s", old.name)
        except OSError:
            pass  # still locked — will be cleaned next time


# ── Public API ───────────────────────────────────────────

# Server-side cache for update info
# (avoids hammering GitHub on every AJAX poll)
_update_info_cache: dict | None = None
_update_info_cache_ts: float = 0.0
_UPDATE_INFO_TTL = 600  # 10 minutes


def get_update_info() -> dict:
    """
    Lightweight check: return update availability info without applying.

    Returns a dict:
        {
            "update_available": bool,
            "current_version": str,
            "remote_version": str | None,
            "release_notes": str | None,    # markdown body from GitHub
            "release_url": str | None,       # HTML URL to the release page
            "frozen": bool,
        }
    Result is cached server-side for _UPDATE_INFO_TTL seconds.
    """
    global _update_info_cache, _update_info_cache_ts

    now = time.time()
    if _update_info_cache and (now - _update_info_cache_ts) < _UPDATE_INFO_TTL:
        return _update_info_cache

    try:
        from config import VERSION as local_version
    except ImportError:
        local_version = "0.0.0"

    result = {
        "update_available": False,
        "current_version": local_version,
        "remote_version": None,
        "release_notes": None,
        "release_url": None,
        "frozen": _is_frozen(),
    }

    try:
        release = _fetch_latest_release()
        if release:
            tag = release.get("tag_name", "")
            remote_version = tag.lstrip("vV")
            result["remote_version"] = remote_version
            result["release_notes"] = release.get("body") or None
            result["release_url"] = release.get("html_url") or None

            if _ver_tuple(remote_version) > _ver_tuple(local_version):
                result["update_available"] = True
    except Exception as e:
        log.debug("get_update_info failed: %s", e)

    _update_info_cache = result
    _update_info_cache_ts = now
    return result


def invalidate_update_cache():
    """Clear the cached update info so the next call re-fetches."""
    global _update_info_cache, _update_info_cache_ts
    _update_info_cache = None
    _update_info_cache_ts = 0.0


def check_for_update() -> bool:
    """
    Check GitHub for a newer release and self-update if available.

    Returns True if an update was applied (caller should expect a
    service restart shortly). Returns False otherwise.
    """
    # Housekeeping: remove leftover from previous update
    _cleanup_old_exe()

    if not _is_frozen():
        log.debug("Not a frozen EXE — skipping self-update check.")
        return False

    # Read local version
    try:
        from config import VERSION as local_version
    except ImportError:
        log.warning("Cannot import config.VERSION — skip update.")
        return False

    log.info("Current version: %s - checking for updates ...",
             local_version)

    # ── Primary: check GitHub Releases ──
    release = _fetch_latest_release()
    remote_version = None
    asset = None

    if release:
        tag = release.get("tag_name", "")
        remote_version = tag.lstrip("vV")
        log.info("Latest release: %s (tag: %s)", remote_version, tag)
        asset = _find_exe_asset(release)
    else:
        log.info("No GitHub Release found.")

    # ── Fallback: read VERSION from raw config.py on branch ──
    # (same approach as tools/updater.py — useful for logging
    #  even when a release exists, to detect branch-only bumps)
    raw_version = _fetch_remote_version_via_raw()
    if raw_version:
        log.info("Remote VERSION (raw branch): %s", raw_version)
        # If no release exists, use raw version for comparison
        if not remote_version:
            remote_version = raw_version

    # Compare versions
    if not remote_version:
        log.info("Could not determine remote version — skipping.")
        return False

    if _ver_tuple(remote_version) <= _ver_tuple(local_version):
        log.info("Already up-to-date (%s).", local_version)
        return False

    log.info("Update available: %s -> %s", local_version, remote_version)

    # ── Download: need an .exe asset from a release ──
    if not asset:
        log.warning(
            "No '%s' asset in release — cannot self-update. "
            "A new release with the EXE attached is required.",
            ASSET_NAME)
        return False

    download_url = asset.get("browser_download_url") or asset.get("url")
    asset_size = asset.get("size", 0)
    log.info(
        "Downloading %s (%.1f MB) ...",
        ASSET_NAME, asset_size / 1024 / 1024)

    # Download to a temp file next to the current EXE
    current = _current_exe()
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".exe.tmp", dir=current.parent)
    os.close(tmp_fd)
    tmp_file = Path(tmp_path)

    try:
        if not _download_asset(download_url, tmp_file):
            tmp_file.unlink(missing_ok=True)
            return False

        # Basic sanity: file should be > 1 MB for a PyInstaller EXE
        if tmp_file.stat().st_size < 1_000_000:
            log.error("Downloaded file too small — aborting update.")
            tmp_file.unlink(missing_ok=True)
            return False

        log.info("Download complete. Swapping EXE ...")
        if not _swap_exe(current, tmp_file):
            tmp_file.unlink(missing_ok=True)
            return False

        log.info(
            "OK: Updated %s -> %s. Restarting service ...",
            local_version, remote_version)
        _restart_service()
        return True

    except Exception as e:
        log.error("Update failed: %s", e, exc_info=True)
        tmp_file.unlink(missing_ok=True)
        return False
