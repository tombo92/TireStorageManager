#!/usr/bin/env python
"""
detect_bump_type.py — decide whether a merge to master should bump the
major, minor, or patch version component, based on the merged branch's
name.

Convention (see README.md "Versioning" section):
    major/**, breaking/**          -> major bump   (x+1.0.0)
    feat/**, feature/**            -> minor bump   (x.y+1.0)
    fix/**, bugfix/**, hotfix/**   -> patch bump   (x.y.z+1)
    anything else / no PR merge    -> minor bump   (safe default —
                                       matches the behaviour that existed
                                       before this branch-aware detection
                                       was introduced)

Use the `major/**` or `breaking/**` prefix deliberately and sparingly —
for breaking changes, a major UI overhaul, or any release that isn't
safe to auto-update into without the user's attention. A major bump
resets both MINOR and PATCH to 0.

Branch detection relies on GitHub's default "Create a merge commit" PR
merge strategy, whose first commit line looks like::

    Merge pull request #25 from tombo92/fix-release-testing

Squash-merge commits and direct pushes to master have no such line, so
detection falls back to "minor" (the previous, always-minor behaviour).

Usage (CI):
    python tools/detect_bump_type.py "$(git log -1 --format=%s)"
    -> prints "major", "minor", or "patch" to stdout
"""
from __future__ import annotations

import re
import sys

_MERGE_RX = re.compile(r"^Merge pull request #\d+ from [^/\s]+/(\S+)\s*$")

_MAJOR_PREFIXES = ("major/", "breaking/")
_PATCH_PREFIXES = ("fix/", "bugfix/", "hotfix/")
_MINOR_PREFIXES = ("feat/", "feature/")


def extract_branch_name(commit_message: str) -> str | None:
    """Return the source branch name from a GitHub merge-commit message.

    Only the first line of *commit_message* is considered (the summary
    line). Returns ``None`` if it doesn't match the "Merge pull request
    #N from owner/branch" pattern (e.g. squash merges, direct pushes).
    """
    stripped = commit_message.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0]
    m = _MERGE_RX.match(first_line)
    return m.group(1) if m else None


def detect_bump_type(commit_message: str) -> str:
    """Return ``"major"``, ``"minor"``, or ``"patch"`` for a master merge
    commit message."""
    branch = extract_branch_name(commit_message)
    if branch is None:
        return "minor"  # not a recognised PR merge — safe default
    if branch.startswith(_MAJOR_PREFIXES):
        return "major"
    if branch.startswith(_PATCH_PREFIXES):
        return "patch"
    # _MINOR_PREFIXES and any unrecognised prefix both fall through here —
    # minor is the safe default when we can't positively identify a bugfix
    # or breaking change.
    return "minor"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    message = argv[0] if argv else ""
    print(detect_bump_type(message))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
