"""Print the VERSION string from config.py — used by CI to set the release tag."""
import re
from pathlib import Path

text = Path("config.py").read_text(encoding="utf-8")
m = re.search(r'VERSION\s*=\s*["\'](.+?)["\']', text)
if not m:
    raise SystemExit("VERSION not found in config.py")
print(m.group(1))
