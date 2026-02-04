#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-04 10:17:55
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Bump VERSION="x.y.z" in config.py (patch bump by default).
 - Reads repo-root/config.py, increments patch, writes back.
 - Prints the new version to stdout (so the CI can capture it).
"""
# ========================================================
# IMPORTS
# ========================================================
import re
from pathlib import Path
import sys


# ========================================================
# GLOBALS
# ========================================================
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"
VERSION_RX = re.compile(r'(^\s*VERSION\s*=\s*")(\d+)\.(\d+)\.(\d+)(".*$)',
                        re.MULTILINE)


# ========================================================
# FUNCTIONS
# ========================================================
def main() -> int:
    """
    main function
    """
    if not CONFIG_PATH.exists():
        print(f"ERR: config.py not found at {CONFIG_PATH}", file=sys.stderr)
        return 2

    text = CONFIG_PATH.read_text(encoding="utf-8")
    m = VERSION_RX.search(text)
    if not m:
        print('ERR: VERSION="x.y.z" not found in config.py', file=sys.stderr)
        return 3

    pre, major, minor, patch, post = m.groups()
    major, minor, patch = int(major), int(minor), int(patch) + 1
    new_version = f"{major}.{minor}.{patch}"

    new_text = VERSION_RX.sub(f'{pre}{new_version}{post}', text, count=1)
    if new_text == text:
        print("ERR: substitution failed", file=sys.stderr)
        return 4

    CONFIG_PATH.write_text(new_text, encoding="utf-8")
    # print only the version, CI step captures this
    print(new_version)
    return 0


# ========================================================
# MAIN
# ========================================================
if __name__ == "__main__":
    sys.exit(main())
