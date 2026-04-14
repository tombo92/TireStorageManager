#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Release Acceptance Test – customer-facing master branch gate.

Orchestrates a comprehensive end-to-end verification of both
TireStorageManager.exe and TSM-Installer.exe against the real
Windows environment, covering happy paths, edge cases and resilience
scenarios that matter for a production deployment.

Run order:
  Phase 1  – App EXE standalone checks
  Phase 2  – Installer end-to-end
  Phase 3  – Update flow (repeated N times)
  Phase 4  – Installer upgrade (in-place update via installer)
  Phase 5  – Installer headless update-check

Usage (CI):
    python tools/release_acceptance_test.py \\
        --app-exe  dist/TireStorageManager.exe \\
        --inst-exe dist/TSM-Installer.exe \\
        --install-dir %RUNNER_TEMP%/tsm_rat_install \\
        --data-dir    %RUNNER_TEMP%/tsm_rat_data \\
        --app-port    59300 \\
        --inst-port   59301 \\
        --task-repeats 3 \\
        --update-repeats 3

Exit 0 = all phases passed.
Exit 1 = one or more checks failed.

Implementation:
  The test logic is split into small focused modules under tools/rat/:
    helpers.py   – HTTP/OS/SQLite infrastructure, test reporter
    phase1.py    – App EXE standalone (CRUD, settings, backup, security, …)
    phase2.py    – Installer end-to-end
    phase345.py  – Update flow, installer upgrade, headless update-check
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ── Ensure tools/ is on the path so `rat.*` is importable ────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── UTF-8 stdout (CI runners may default to cp1252) ───────────────────
import io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace")

from rat.helpers import _counters, _failures, _warnings
from rat.phase1 import phase1_app
from rat.phase2 import phase2_installer
from rat.phase345 import (
    phase3_update,
    phase4_installer_upgrade,
    phase5_installer_update_check,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Release acceptance test -- master branch gate")
    parser.add_argument("--app-exe", required=True,
                        help="Path to TireStorageManager.exe")
    parser.add_argument("--inst-exe", required=True,
                        help="Path to TSM-Installer.exe")
    parser.add_argument(
        "--install-dir", required=True, dest="install_dir",
        help="Temporary installer target (will be deleted)",
    )
    parser.add_argument(
        "--data-dir", required=True, dest="data_dir",
        help="Temporary data directory (will be deleted)",
    )
    parser.add_argument(
        "--app-port", type=int, default=59300, dest="app_port",
        help="Port for standalone app EXE (default: 59300)",
    )
    parser.add_argument(
        "--inst-port", type=int, default=59301, dest="inst_port",
        help="Port for installed service (default: 59301)",
    )
    parser.add_argument(
        "--task-repeats", type=int, default=3, dest="task_repeats",
        help="Scheduler-restart cycles in Phase 2g (default: 3)",
    )
    parser.add_argument(
        "--update-repeats", type=int, default=3, dest="update_repeats",
        help="Update-flow cycles in Phase 3 (default: 3)",
    )
    parser.add_argument("--skip-phase1", action="store_true",
                        help="Skip Phase 1 (app EXE standalone)")
    parser.add_argument("--skip-phase2", action="store_true",
                        help="Skip Phase 2 (installer end-to-end)")
    parser.add_argument("--skip-phase3", action="store_true",
                        help="Skip Phase 3 (update flow)")
    parser.add_argument("--skip-phase4", action="store_true",
                        help="Skip Phase 4 (installer upgrade)")
    parser.add_argument("--skip-phase5", action="store_true",
                        help="Skip Phase 5 (installer update check)")
    args = parser.parse_args()

    app_exe = Path(args.app_exe).resolve()
    inst_exe = Path(args.inst_exe).resolve()
    install_dir = Path(args.install_dir).resolve()
    data_dir = Path(args.data_dir).resolve()

    print("=" * 60, flush=True)
    print("  Release Acceptance Test (RAT)", flush=True)
    print(f"  app-exe:      {app_exe}", flush=True)
    print(f"  inst-exe:     {inst_exe}", flush=True)
    print(f"  app-port:     {args.app_port}", flush=True)
    print(f"  inst-port:    {args.inst_port}", flush=True)
    print(f"  task-repeats: {args.task_repeats}", flush=True)
    print(f"  upd-repeats:  {args.update_repeats}", flush=True)
    print("=" * 60, flush=True)

    if not app_exe.exists():
        print(f"ERROR: app-exe not found: {app_exe}", flush=True)
        return 1
    if not inst_exe.exists():
        print(f"ERROR: inst-exe not found: {inst_exe}", flush=True)
        return 1

    try:
        if not args.skip_phase1:
            phase1_app(app_exe, args.app_port, data_dir)
        if not args.skip_phase2:
            phase2_installer(
                inst_exe, install_dir, data_dir, args.inst_port,
                task_repeats=args.task_repeats,
            )
        if not args.skip_phase3:
            phase3_update(
                app_exe, args.app_port, data_dir,
                repeats=args.update_repeats,
            )
        if not args.skip_phase4:
            phase4_installer_upgrade(
                inst_exe, install_dir, data_dir,
                args.inst_port, app_exe,
            )
        if not args.skip_phase5:
            phase5_installer_update_check(inst_exe)
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
        return 1

    print("\n" + "=" * 60, flush=True)
    print(f"  Checks run:  {_counters['total']}", flush=True)
    if _warnings:
        print(f"  Warnings:    {len(_warnings)}", flush=True)
        for w in _warnings:
            print(f"    WARN  {w}", flush=True)
    if _failures:
        print(f"  FAILED:      {len(_failures)}", flush=True)
        for f in _failures:
            print(f"    FAIL  {f}", flush=True)
        return 1

    print("  ALL CHECKS PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
