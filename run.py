#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Entry point
"""
# ========================================================
# IMPORTS
# ========================================================
# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from tsm.app import create_app
from tsm.backup_manager import BackupManager
from tsm.db import engine
from config import BACKUP_DIR, HOST, PORT, APP_NAME, VERSION


# ========================================================
# MAIN
# ========================================================
if __name__ == "__main__":
    app = create_app()

    # Start the backup thread once
    backup_manager = BackupManager(engine, BACKUP_DIR)
    backup_manager.start()

    print(f"{APP_NAME} v{VERSION} läuft auf http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
