#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Unified runner for TireStorageManager:
- Dev mode: Flask's built-in server (debug, reload)
- Prod mode: Waitress WSGI server (Windows-friendly)
- Starts the BackupManager in both modes
- Handles clean shutdown for interactive run and Windows service

Usage:
  python run.py                 # default: prod mode on 0.0.0.0:5000
  python run.py --dev           # dev mode with Flask reloader
  python run.py --host 0.0.0.0 --port 8080
  python run.py --data-dir C:\\ProgramData\\TireStorageManager
"""

# ========================================================
# IMPORTS  (pre-parse --data-dir BEFORE importing config)
# ========================================================
import argparse
import logging
import logging.handlers
import os
import signal
import sys
from typing import Optional

# --- Early parse: extract --data-dir so env is set before config loads ---
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--data-dir", default=None)
_pre.add_argument("--no-update", action="store_true", default=False)
_early, _ = _pre.parse_known_args()
if _early.data_dir:
    os.environ["TSM_DATA_DIR"] = _early.data_dir

# Now safe to import config and app modules
from tsm.app import create_app                          # noqa: E402
from tsm.backup_manager import BackupManager            # noqa: E402
from tsm.self_update import check_for_update            # noqa: E402
from tsm.db import engine                               # noqa: E402
from config import BACKUP_DIR, LOG_LEVEL, LOG_DIR       # noqa: E402

# ========================================================
# LOGGING
# ========================================================
log_formatter = logging.Formatter(
    "%(asctime)s %(levelname)s [%(name)s] %(message)s")

# Console handler
_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(log_formatter)

# Rotating file handler (in data dir)
_file = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, "tsm.log"),
    maxBytes=2 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_file.setFormatter(log_formatter)

logging.basicConfig(level=LOG_LEVEL, handlers=[_console, _file])
log = logging.getLogger("TSM.run")


# ========================================================
# CLASSES
# ========================================================
class Runner:
    """Runner Class"""
    def __init__(self, host: str, port: int, dev: bool):
        self.host = host
        self.port = port
        self.dev = dev
        self.app = create_app()
        self._backup: Optional[BackupManager] = None
        self._stopping = False
        self._server = None

    # ---- Backup lifecycle ----
    def start_backup(self):
        log.info("Starting BackupManager...")
        self._backup = BackupManager(engine, BACKUP_DIR)
        self._backup.start()
        log.info("BackupManager started.")

    def stop_backup(self):
        bm = self._backup
        if bm is None:
            return
        self._backup = None
        log.info("Stopping BackupManager...")
        try:
            bm.stop()          # signal the thread to exit its loop
            bm.join(timeout=5)  # wait briefly for it to finish
        except Exception as e:
            log.warning(
                "BackupManager stop/join raised: %s",
                e, exc_info=True)
        log.info("BackupManager stopped.")

    # ---- Signal handling (CTRL+C, service stop) ----
    def _handle_signal(self, signum, frame):
        if self._stopping:
            return
        self._stopping = True
        log.info("Signal %s received. Shutting down...", signum)
        self.stop_backup()
        if self._server:
            self._server.close()

    def _install_signal_handlers(self):
        """Install signal handlers for prod mode only.

        In dev mode Flask's reloader manages SIGINT itself — installing
        a custom handler swallows the KeyboardInterrupt that Werkzeug
        needs to shut down cleanly, so we skip it.
        """
        if self.dev:
            return
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(s, self._handle_signal)
            except Exception:
                pass  # may fail on Windows for some signals

    # ---- Run modes ----
    def run(self):
        self._install_signal_handlers()
        self.start_backup()
        if self.dev:
            self._run_dev()
        else:
            self._run_prod()

    def _run_dev(self):
        """Development: Flask built-in server with debug & reloader."""
        # Werkzeug's server thread may raise OSError (WinError 10038) on
        # Windows when the socket is closed during Ctrl+C shutdown.
        # Suppress that specific noise via a custom threading excepthook.
        import threading as _th
        _orig_excepthook = getattr(_th, "excepthook", None)

        def _quiet_excepthook(args):
            if (self._stopping
                    and isinstance(args.exc_value, OSError)
                    and getattr(args.exc_value, "winerror", None) == 10038):
                return  # expected during shutdown — ignore
            if _orig_excepthook:
                _orig_excepthook(args)

        _th.excepthook = _quiet_excepthook

        log.info(
            "Starting Flask dev server on http://%s:%s ...",
            self.host, self.port)
        try:
            self.app.run(
                host=self.host, port=self.port, debug=True,
                use_reloader=True)
        except KeyboardInterrupt:
            pass  # expected
        finally:
            self._stopping = True
            self.stop_backup()
            _th.excepthook = _orig_excepthook or _th.excepthook
            log.info("DEV server stopped.")

    def _run_prod(self):
        """Production: Waitress WSGI server (Windows-friendly)."""
        from waitress import create_server
        log.info(
            "Starting Waitress on http://%s:%s ...",
            self.host, self.port)
        threads_env = os.getenv("TSM_THREADS")
        kwargs = {}
        if threads_env:
            kwargs["threads"] = int(threads_env)
        self._server = create_server(
            self.app, host=self.host, port=self.port,
            **kwargs)
        try:
            self._server.run()
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt — stopping prod server.")
        finally:
            self.stop_backup()
            log.info("PROD server stopped.")
            if self._server:
                self._server.close()


# ========================================================
# FUNCTIONS
# ========================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Run TireStorageManager.")
    parser.add_argument(
        "--dev", action="store_true",
        help="Run Flask dev server")
    parser.add_argument(
        "--host",
        default=os.getenv("TSM_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int,
        default=int(os.getenv("TSM_PORT", "5000")))
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override data directory (db, backups, logs)")
    parser.add_argument(
        "--no-update", action="store_true",
        default=False,
        help="Skip self-update check on startup")
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Self-update check (only for frozen EXE, unless --no-update) ──
    if not args.no_update and not args.dev:
        try:
            updated = check_for_update()
            if updated:
                log.info("Update applied — service will restart. "
                         "Exiting current process.")
                sys.exit(0)
        except Exception as e:
            log.warning("Self-update check failed: %s", e,
                        exc_info=True)

    Runner(
        host=args.host, port=args.port, dev=args.dev
    ).run()


# ========================================================
# MAIN
# ========================================================
if __name__ == "__main__":
    main()
