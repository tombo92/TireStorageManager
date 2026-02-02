#!/usr/bin/env python3
# updater.py  —  Lightweight auto-updater for TireStorage Manager (Windows friendly)
# - Compares local VERSION in wheels_manager.py to remote (GitHub master branch)
# - If different: downloads branch ZIP, overlays code files (preserve DB/backups/.venv)
# - Exits 0 (no update), 10 (updated), or >0 (non-fatal error -> caller may continue)

import os, re, sys, io, time, urllib.request, urllib.error, zipfile, shutil, tempfile, json

OWNER  = os.environ.get("TSM_GH_OWNER",  "tombo92")
REPO   = os.environ.get("TSM_GH_REPO",   "TireStorageManager")
BRANCH = os.environ.get("TSM_GH_BRANCH", "master")

RAW_BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}"              # [1](https://github.com/tombo92/TireStorageManager)
RAW_URL  = f"{RAW_BASE}/wheels_manager.py"
ZIP_URL  = f"https://github.com/{OWNER}/{REPO}/archive/refs/heads/{BRANCH}.zip"     # [2](https://github.com/tombo92/TireStorageManager/releases)
COMMITS_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/commits/{BRANCH}"       # [3](https://docs.github.com/en/rest/commits)

HERE = os.path.abspath(os.path.dirname(__file__))
APP_FILE = os.path.join(HERE, "wheels_manager.py")

INCLUDE_PATTERNS = (".py", ".cmd", ".bat", ".ps1", "requirements.txt")

VERSION_RX = re.compile(r'^\s*VERSION\s*=\s*"([^"]+)"', re.MULTILINE)

def log(msg): print(f"[updater] {msg}")

def read_local_version(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            m = VERSION_RX.search(f.read())
            return m.group(1) if m else None
    except Exception:
        return None

def fetch_text_nocache(url: str, timeout=15) -> str | None:
    """
    Fetch text from URL with cache-buster query and 'no-cache' headers to avoid CDN caching.
    """
    ts = int(time.time())
    sep = "&" if "?" in url else "?"
    nocache_url = f"{url}{sep}ts={ts}"
    req = urllib.request.Request(
        nocache_url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "TSM-Updater/1.0"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

def fetch_remote_version_via_raw() -> str | None:
    data = fetch_text_nocache(RAW_URL)
    if not data:
        return None
    m = VERSION_RX.search(data)
    if m:
        return m.group(1)
    # If not matched, print a short preview to help diagnose format differences
    log("WARN: VERSION not found in raw; preview:\n" + data[:100])
    return None

def fetch_zip_bytes():
    ts = int(time.time())
    sep = "&" if "?" in ZIP_URL else "?"
    url = f"{ZIP_URL}{sep}ts={ts}"
    req = urllib.request.Request(url, headers={"User-Agent": "TSM-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()

def extract_remote_version_from_zip(zip_bytes: bytes) -> str | None:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Find wheels_manager.py within the archive
        # The archive root usually is "<REPO>-<BRANCH>/".
        cand = [n for n in zf.namelist() if n.endswith("wheels_manager.py")]
        if not cand:
            return None
        data = zf.read(cand[0]).decode("utf-8", errors="ignore")
        m = VERSION_RX.search(data)
        return m.group(1) if m else None

def fetch_latest_commit_sha() -> str | None:
    """
    Optional fallback: query GitHub commits endpoint to detect change on branch.
    If SHA differs from last saved SHA, we can treat as 'update available'.
    """
    try:
        req = urllib.request.Request(COMMITS_URL, headers={"User-Agent": "TSM-Updater/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            obj = json.loads(resp.read().decode("utf-8", errors="ignore"))
        # The endpoint returns the commit object for the ref/branch. We want 'sha'.
        if isinstance(obj, dict) and "sha" in obj:
            return obj["sha"]
    except Exception:
        return None
    return None

def semantic_tuple(v: str) -> tuple:
    parts = re.split(r"[.-]", v.strip())
    out = []
    for p in parts:
        try: out.append(int(p))
        except: out.append(0)
    return tuple(out)

def should_update(local, remote) -> bool:
    if not remote: return False
    if not local:  return True
    try:
        return semantic_tuple(remote) > semantic_tuple(local)
    except Exception:
        return remote != local

def overlay_from_zip(zip_bytes: bytes, dest_root: str) -> None:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        top = None
        for n in zf.namelist():
            if n.endswith("/") and n.count("/") == 1:
                top = n; break
        if not top:
            top = os.path.commonprefix(zf.namelist())
        for name in zf.namelist():
            if not name.startswith(top): continue
            rel = name[len(top):]
            if not rel or rel.endswith("/"): continue
            if not any(rel.endswith(ext) for ext in INCLUDE_PATTERNS): continue
            src_data = zf.read(name)
            dest_path = os.path.join(HERE, rel)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(src_data)

def main() -> int:
    local_v  = read_local_version(APP_FILE)
    log(f"Local VERSION: {local_v or 'n/a'}")

    remote_v = fetch_remote_version_via_raw()
    log(f"Remote VERSION (raw): {remote_v or 'n/a'}")

    # If raw says "same", double-check by reading version inside the ZIP to defeat CDN caches
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
        # Optional last resort: if versions look equal but latest commit changed, consider update
        sha = fetch_latest_commit_sha()  # REST commits API  [3](https://docs.github.com/en/rest/commits)
        if sha:
            # You could load/save the last-seen SHA to a file and compare; for brevity we only log it.
            log(f"Latest branch commit SHA: {sha}")
        log("OK: no update needed.")
        return 0

    log(f"INFO: updating {local_v or 'n/a'} -> {remote_v} ...")
    try:
        zip_bytes = fetch_zip_bytes()
    except urllib.error.URLError as e:
        log(f"ERROR: download failed: {e}")
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        try:
            # Extract into tmp, then overlay
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(tmp)
            # Reuse overlay routine for selected files
            overlay_from_zip(zip_bytes, dest_root=HERE)
        except zipfile.BadZipFile:
            log("ERROR: invalid ZIP from GitHub.")
            return 3

    log(f"OK: updated to {remote_v}.")
    return 10

if __name__ == "__main__":
    sys.exit(main())
