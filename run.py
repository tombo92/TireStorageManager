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
  set TSM_HOST=0.0.0.0 & set TSM_PORT=5000 & python run.py
"""

# ========================================================
# IMPORTS
# ========================================================
import logging
import os
import signal
import argparse
from typing import Optional
# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from tsm.app import create_app
from tsm.backup_manager import BackupManager
from tsm.db import engine
from config import BACKUP_DIR, HOST, PORT, APP_NAME, VERSION, LOG_LEVEL

# Configure basic logging early (service-friendly)
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
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

    # ---- Backup lifecycle ----------------------------------------------------
    def start_backup(self):
        log.info("Starting BackupManager...")
        self._backup = BackupManager(engine, BACKUP_DIR)
        # If your BackupManager accepts config, pass it here (paths, intervals, etc.)
        self._backup.start()
        log.info("BackupManager started.")

    def stop_backup(self):
        if self._backup:
            log.info("Stopping BackupManager...")
            # Implement stop() in BackupManager to set an event/flag & let thread exit
            stop = getattr(self._backup, "stop", None)
            join = getattr(self._backup, "join", None)
            try:
                if callable(stop):
                    stop()
                if callable(join):
                    join(timeout=10)
            except Exception as e:
                log.warning("BackupManager stop/join raised: %s", e, exc_info=True)
            finally:
                self._backup = None
                log.info("BackupManager stopped.")

    # ---- Signal handling (CTRL+C, service stop) ------------------------------
    def _handle_signal(self, signum, frame):
        if self._stopping:
            return
        self._stopping = True
        log.info("Signal %s received. Shutting down...", signum)
        # In dev mode Flask reloader spawns a child; signals may behave differently.
        # We only ensure backup stops here; servers exit via their own mechanisms.
        self.stop_backup()

    def _install_signal_handlers(self):
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(s, self._handle_signal)
            except Exception:
                pass  # may fail on Windows for some signals; ok

    # ---- Run modes -----------------------------------------------------------
    def run(self):
        self._install_signal_handlers()
        self.start_backup()
        if self.dev:
            self._run_dev()
        else:
            self._run_prod()

    def _run_dev(self):
        """
        Development: Flask built-in server with debug & reloader.
        Note: BackupManager will start in the *parent* process; on reload,
        you may get two processes. To avoid double backups, consider:
          - Disable backup in dev OR
          - Only start backup if os.environ.get("WERKZEUG_RUN_MAIN") == "true"
        """
        # If you want to run backup only in the reloader's child:
        # if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        #     return

        log.info("Starting Flask dev server on http://%s:%s ...", self.host, self.port)
        try:
            self.app.run(host=self.host, port=self.port, debug=True)
        finally:
            self.stop_backup()

    def _run_prod(self):
        """
        Production: Waitress WSGI server (Windows-friendly).
        Binds to 0.0.0.0 by default so other LAN clients can reach it.
        """
        from waitress import create_server # local import so dev envs don’t need waitress
        log.info("Starting Waitress on http://%s:%s ...", self.host, self.port)
        self._server = create_server(self.app, host=self.host, port=self.port)
        try:
            # Tip: tune threads via env TSM_THREADS (default waitress=4)
            threads_env = os.getenv("TSM_THREADS")
            threads = int(threads_env) if threads_env else None
            self._server.run()
        finally:
            self.stop_backup()
            log.info("PROD server stopped.")
            # self._server.wait()
            self._server.close()


# ========================================================
# FUNCTIONS
# ========================================================
def parse_args():
    parser = argparse.ArgumentParser(description="Run TireStorageManager.")
    parser.add_argument("--dev", action="store_true", help="Run Flask dev server")
    parser.add_argument("--host", default=os.getenv("TSM_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("TSM_PORT", "5000")))
    return parser.parse_args()


def main():
    args = parse_args()
    Runner(host=args.host, port=args.port, dev=args.dev).run()


# ========================================================
# MAIN
# ========================================================
if __name__ == "__main__":
    main()
