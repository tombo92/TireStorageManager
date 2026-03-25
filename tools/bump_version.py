#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-04 10:17:55
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Bump VERSION="x.y.z" in config.py (patch bump by default).
 - Reads repo-root/config.py, increments patch, writes back.
 - Stamps the [Unreleased] section in CHANGELOG.md with the new version.
 - Prints the new version to stdout (so the CI can capture it).
"""
# ========================================================
# IMPORTS
# ========================================================
import re
from datetime import date
from pathlib import Path
import sys


# ========================================================
# GLOBALS
# ========================================================
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"
CHANGELOG_PATH = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
VERSION_RX = re.compile(r'(^\s*VERSION\s*=\s*")(\d+)\.(\d+)\.(\d+)(".*$)',
                        re.MULTILINE)


# ========================================================
# FUNCTIONS
# ========================================================
def _stamp_changelog(new_version: str):
    """Move [Unreleased] entries into a versioned section."""
    if not CHANGELOG_PATH.exists():
        return
    text = CHANGELOG_PATH.read_text(encoding="utf-8")

    today = date.today().isoformat()  # YYYY-MM-DD
    new_heading = (
        f"## [Unreleased]\n\n"
        f"## [{new_version}] – {today}"
    )
    # Replace the first "## [Unreleased]" with two headings:
    # a fresh empty [Unreleased] + the new versioned section
    updated = text.replace("## [Unreleased]", new_heading, 1)
    if updated != text:
        CHANGELOG_PATH.write_text(updated, encoding="utf-8")


def main() -> int:
    """
    main function
    """
    minor_bump = "--minor" in sys.argv

    if not CONFIG_PATH.exists():
        print(f"ERR: config.py not found at {CONFIG_PATH}", file=sys.stderr)
        return 2

    text = CONFIG_PATH.read_text(encoding="utf-8")
    m = VERSION_RX.search(text)
    if not m:
        print('ERR: VERSION="x.y.z" not found in config.py', file=sys.stderr)
        return 3

    pre, major, minor, patch, post = m.groups()
    major, minor, patch = int(major), int(minor), int(patch)

    if minor_bump:
        minor += 1
        patch = 0
    else:
        patch += 1

    new_version = f"{major}.{minor}.{patch}"

    new_text = VERSION_RX.sub(f'{pre}{new_version}{post}', text, count=1)
    if new_text == text:
        print("ERR: substitution failed", file=sys.stderr)
        return 4

    CONFIG_PATH.write_text(new_text, encoding="utf-8")
    _stamp_changelog(new_version)
    # print only the version, CI step captures this
    print(new_version)
    return 0


# ========================================================
# MAIN
# ========================================================
if __name__ == "__main__":
    sys.exit(main())
