#!/usr/bin/env python3
# updater.py  —  Lightweight auto-updater for TireStorage Manager (Windows friendly)
# - Compares local VERSION in wheels_manager.py to remote (GitHub master branch)
# - If different: downloads branch ZIP, overlays code files (preserve DB/backups/.venv)
# - Exits 0 (no update), 10 (updated), or >0 (non-fatal error -> caller may continue)

import os, re, sys, io, json, urllib.request, urllib.error, zipfile, shutil, tempfile

OWNER  = os.environ.get("TSM_GH_OWNER",  "tombo92")
REPO   = os.environ.get("TSM_GH_REPO",   "TireStorageManager")
BRANCH = os.environ.get("TSM_GH_BRANCH", "master")

RAW_URL = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/wheels_manager.py"  # raw endpoint for a branch file [1](https://github.com/tombo92/TireStorageManager)
ZIP_URL = f"https://github.com/{OWNER}/{REPO}/archive/refs/heads/{BRANCH}.zip"           # branch archive zip (no releases required) [2](https://github.com/tombo92/TireStorageManager/releases)

HERE = os.path.abspath(os.path.dirname(__file__))
APP_FILE = os.path.join(HERE, "wheels_manager.py")

INCLUDE_PATTERNS = (
    ".py",                 # Python sources (single-file app + helpers)
    ".cmd", ".bat", ".ps1",
    "requirements.txt",
)

def read_local_version(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    try:
        txt = open(path, "r", encoding="utf-8", errors="ignore").read()
        m = re.search(r'^\s*VERSION\s*=\s*"([^"]+)"', txt, re.MULTILINE)
        return m.group(1) if m else None
    except Exception:
        return None

def fetch_remote_version() -> str | None:
    try:
        with urllib.request.urlopen(RAW_URL, timeout=15) as resp:
            data = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r'^\s*VERSION\s*=\s*"([^"]+)"', data, re.MULTILINE)
        return m.group(1) if m else None
    except Exception:
        return None

def semantic_tuple(v: str) -> tuple:
    # turns "1.2.3" -> (1,2,3); non-numeric parts get 0 fallback
    parts = re.split(r"[.-]", v.strip())
    out = []
    for p in parts:
        try: out.append(int(p))
        except: out.append(0)
    return tuple(out)

def should_update(local: str | None, remote: str | None) -> bool:
    if not remote:
        return False
    if not local:
        return True
    # Prefer semantic compare; fallback to simple inequality
    try:
        return semantic_tuple(remote) > semantic_tuple(local)
    except Exception:
        return remote != local

def download_zip_to_mem(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()

def overlay_from_zip(zip_bytes: bytes, dest_root: str) -> None:
    # GitHub branch archives contain a single top-level folder "<REPO>-<BRANCH>/..."
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Find top-level dir
        top = None
        for n in zf.namelist():
            if n.endswith("/") and n.count("/") == 1:
                top = n
                break
        if not top:
            # Fallback: find common prefix
            top = os.path.commonprefix(zf.namelist())
        for name in zf.namelist():
            if not name.startswith(top):
                continue
            rel = name[len(top):]
            if not rel or rel.endswith("/"):
                # directory
                continue
            # Only copy included patterns
            if not any(rel.endswith(ext) for ext in INCLUDE_PATTERNS):
                continue
            src_data = zf.read(name)
            dest_path = os.path.join(dest_root, rel)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(src_data)

def main() -> int:
    local_v  = read_local_version(APP_FILE)
    remote_v = fetch_remote_version()

    if remote_v is None:
        print("[updater] WARN: could not read remote version; skipping update.")
        return 1

    if not should_update(local_v, remote_v):
        print(f"[updater] OK: up to date (local={local_v or 'n/a'}, remote={remote_v}).")
        return 0

    print(f"[updater] INFO: updating from {local_v or 'n/a'} to {remote_v} ...")

    # Best-effort: stop existing process is handled by caller (batch) later if needed.
    # Here we only replace files atomically where possible.
    try:
        zip_bytes = download_zip_to_mem(ZIP_URL)
    except urllib.error.URLError as e:
        print(f"[updater] ERROR: download failed: {e}")
        return 2

    # Extract and overlay into a temp dir first; then copy into place
    with tempfile.TemporaryDirectory() as tmp:
        try:
            overlay_from_zip(zip_bytes, dest_root=tmp)
        except zipfile.BadZipFile:
            print("[updater] ERROR: invalid ZIP from GitHub.")
            return 3

        # Copy selected files from tmp root into HERE, preserving DB/backups/.venv
        for root, _, files in os.walk(tmp):
            for fname in files:
                rel = os.path.relpath(os.path.join(root, fname), tmp)
                dst = os.path.join(HERE, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(root, fname), dst)

    print(f"[updater] OK: updated to {remote_v}.")
    return 10  # signal "updated"

if __name__ == "__main__":
    sys.exit(main())
