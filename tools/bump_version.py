#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-04 10:17:55
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Bump VERSION="x.y.z" in config.py.

Versioning scheme:
  x  – major: updated manually only
  y  – minor: bumped on every push to master  (--minor flag, resets z to 0)
  z  – patch: bumped on every push to develop (default, no flag)

Usage:
  python tools/bump_version.py           # patch bump:  1.2.3 → 1.2.4
  python tools/bump_version.py --minor   # minor bump:  1.2.3 → 1.3.0
"""
# ========================================================
# IMPORTS
# ========================================================
import argparse
import re
import sys
from datetime import date
from pathlib import Path


# ========================================================
# GLOBALS
# ========================================================
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"
CHANGELOG_PATH = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"
VERSION_RX = re.compile(
    r'(^\s*VERSION\s*=\s*")(\d+)\.(\d+)\.(\d+)(".*$)',
    re.MULTILINE,
)
PYPROJECT_VERSION_RX = re.compile(
    r'^(version\s*=\s*")\d+\.\d+\.\d+(")',
    re.MULTILINE,
)


# ========================================================
# FUNCTIONS
# ========================================================
def _stamp_changelog(new_version: str):
    """Move [Unreleased] entries into a versioned section.

    Prints a warning to stderr when the [Unreleased] section is empty
    so the release notes are not silently blank.
    """
    if not CHANGELOG_PATH.exists():
        return
    text = CHANGELOG_PATH.read_text(encoding="utf-8")

    # Check if [Unreleased] has any content
    section_re = re.compile(r"^## \[([^\]]+)\][^\n]*$", re.MULTILINE)
    for m in section_re.finditer(text):
        if m.group(1).lower() == "unreleased":
            start = m.end()
            nxt = section_re.search(text, start)
            body = (text[start:nxt.start()] if nxt else text[start:]).strip()
            if not body:
                print(
                    "WARN: [Unreleased] section is empty – "
                    "release notes will be blank. "
                    "Add entries to CHANGELOG.md before merging.",
                    file=sys.stderr,
                )
            break

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


def _sync_pyproject_version(new_version: str) -> None:
    """Keep [project] version in pyproject.toml in sync with config.py."""
    if not PYPROJECT_PATH.exists():
        return
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    updated = PYPROJECT_VERSION_RX.sub(rf'\g<1>{new_version}\g<2>', text, count=1)
    if updated != text:
        PYPROJECT_PATH.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bump VERSION in config.py")
    parser.add_argument(
        "--minor", action="store_true",
        help="Bump minor version and reset patch to 0 (push to main)",
    )
    args = parser.parse_args()

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

    if args.minor:
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
    _sync_pyproject_version(new_version)
    _stamp_changelog(new_version)
    # print only the version — CI captures this via $()
    print(new_version)
    return 0


# ========================================================
# MAIN
# ========================================================
if __name__ == "__main__":
    sys.exit(main())
