#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Extract the changelog section for a given version (or [Unreleased]).

Usage:
    python tools/extract_changelog.py                  # → [Unreleased] section
    python tools/extract_changelog.py 1.4.2            # → [1.4.2] section
    python tools/extract_changelog.py --unreleased     # → [Unreleased] section

The script reads CHANGELOG.md from the repo root and prints
the body text (without the heading) to stdout.  If no matching
section is found it exits with code 0 and prints nothing — the
CI can fall back to a generic message.
"""
import io
import re
import sys
from pathlib import Path

# Ensure stdout in UTF-8 so changelog entries with Unicode characters
# (e.g. arrows, emoji used in user-facing descriptions) are not garbled
# on Windows consoles or when redirected in CI pipelines.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"

# Matches  ## [1.2.3]  or  ## [Unreleased]  (with optional date suffix)
_SECTION_RE = re.compile(
    r"^## \[([^\]]+)\][^\n]*$", re.MULTILINE
)


def extract(version: str | None = None) -> str:
    """Return the body of the changelog section for *version*.

    If *version* is ``None`` or ``"unreleased"``, the ``[Unreleased]``
    section is returned.  Otherwise the ``[<version>]`` section.
    """
    if not CHANGELOG.exists():
        return ""

    text = CHANGELOG.read_text(encoding="utf-8")

    target = "Unreleased"
    if version and version.lower() != "unreleased":
        target = version.lstrip("vV")

    # Find the start of the target section
    for m in _SECTION_RE.finditer(text):
        if m.group(1).lower() == target.lower():
            start = m.end()
            # Find the next ## heading (= next version section)
            nxt = _SECTION_RE.search(text, start)
            body = text[start:nxt.start()] if nxt else text[start:]
            return body.strip()

    return ""


def main():
    version = None
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--unreleased":
            version = None
        else:
            version = arg

    body = extract(version)
    if body:
        print(body)


if __name__ == "__main__":
    main()
