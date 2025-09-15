import os
import sys
import tempfile
import urllib.request
import json
import shutil
import subprocess
from app.config import __version__

# URL to your latest.json hosted in your GitHub repo or server
UPDATE_INFO_URL = "https://raw.githubusercontent.com/tombo92/TireStorageManager/refs/heads/master/latest.json"

def check_for_update():
    """
    Check remote JSON file for newer version.
    Returns tuple (latest_version, download_url) if update exists, else None.
    """
    try:
        with urllib.request.urlopen(UPDATE_INFO_URL, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        latest = data["version"]
        url = data["url"]
        if compare_versions(latest, __version__) > 0:
            return (latest, url)
    except Exception as e:
        print("Update check failed:", e)
    return None

def download_and_schedule_update(download_url: str):
    """
    Download new exe to a temp file, then schedule a .bat script to replace current exe.
    """
    tmp_path = tempfile.mktemp(suffix=".exe")

    # Download the file
    with urllib.request.urlopen(download_url) as resp, open(tmp_path, "wb") as out:
        shutil.copyfileobj(resp, out)

    current_exe = os.path.abspath(sys.argv[0])
    updater = tmp_path + "_updater.bat"

    # Write updater batch file
    with open(updater, "w") as f:
        f.write(f"""@echo off
echo Updating TireStorage...
timeout /t 2 >nul
move /y "{tmp_path}" "{current_exe}"
start "" "{current_exe}"
""")

    # Launch updater and exit
    subprocess.Popen([updater], shell=True)
    sys.exit(0)

def compare_versions(a: str, b: str) -> int:
    """
    Compare semantic version strings (e.g., "1.2.0").
    Returns 1 if a > b, -1 if a < b, 0 if equal.
    """
    def parts(v): return [int(x) for x in v.split(".")]
    pa, pb = parts(a), parts(b)
    return (pa > pb) - (pa < pb)
