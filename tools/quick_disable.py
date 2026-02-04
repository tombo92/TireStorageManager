#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Enable/disable/list storage positions.

Usage:
  python tools/quick_disable.py --disable C1ROLR --reason "Shelf damaged"
  python tools/quick_disable.py --enable C1ROLR
  python tools/quick_disable.py --list
"""

# ========================================================
# IMPORTS
# ========================================================

from __future__ import annotations

import sys
from pathlib import Path
import argparse

# Ensure repo root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tsm.db import SessionLocal
from tsm.positions import (disable_position, enable_position,
                           get_disabled_positions, is_valid_position,
                           position_sort_key)

# ========================================================
# MAIN
# ========================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Manage disabled storage positions.")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--disable", metavar="CODE", help="Disable a position code (e.g., C1ROLR, GR1OM)")
    g.add_argument("--enable",  metavar="CODE", help="Enable (re-allow) a position code")
    g.add_argument("--list", action="store_true", help="List all disabled positions")
    parser.add_argument("--reason", help="Optional reason when disabling", default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.list or (not args.disable and not args.enable):
            disabled = sorted(get_disabled_positions(db), key=position_sort_key)
            if not disabled:
                print("No disabled positions.")
            else:
                print("Disabled positions:")
                for code in disabled:
                    print("  ", code)
            return 0

        if args.disable:
            code = args.disable.strip().upper()
            if not is_valid_position(code):
                print(f"ERROR: '{code}' is not a structurally valid position code.")
                return 2
            created = disable_position(db, code, args.reason)
            if created:
                print(f"OK: disabled {code}" + (f" ({args.reason})" if args.reason else ""))
            else:
                print(f"INFO: {code} was already disabled.")
            return 0

        if args.enable:
            code = args.enable.strip().upper()
            if not is_valid_position(code):
                print(f"ERROR: '{code}' is not a structurally valid position code.")
                return 2
            removed = enable_position(db, code)
            if removed:
                print(f"OK: enabled {code}")
            else:
                print(f"INFO: {code} is not currently disabled.")
            return 0

        return 0
    finally:
        db.close()

if __name__ == "__main__":
    raise SystemExit(main())
