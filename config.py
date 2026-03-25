#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
App Configurations

Paths can be overridden via environment variables so that the
PyInstaller EXE + Windows Service can use a separate data directory:
  TSM_DATA_DIR  →  base for db/ and backups/
"""
# ========================================================
# IMPORTS
# ========================================================
import os
from pathlib import Path

# ========================================================
# GLOBALS
# ========================================================
VERSION = "1.4.2"
APP_NAME = os.environ.get("TSM_APP_NAME", "Reifenmanager")

# Set to "1" by the CI on develop builds — signals a pre-release/test build
IS_PRERELEASE: bool = os.environ.get("TSM_PRERELEASE", "0") == "1"

BASE_DIR = Path(__file__).resolve().parent

# Data directory: default = repo root, override with TSM_DATA_DIR
DATA_DIR = Path(os.environ.get("TSM_DATA_DIR", str(BASE_DIR)))

DB_DIR = DATA_DIR / "db"
DB_PATH = str(DB_DIR / "wheel_storage.db")
BACKUP_DIR = str(DATA_DIR / "backups")
LOG_DIR = str(DATA_DIR / "logs")
LOG_LEVEL = os.getenv("TSM_LOG_LEVEL", "INFO").upper()

os.makedirs(str(DB_DIR), exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Set Production via ENV!
SECRET_KEY = os.environ.get("TSM_SECRET_KEY", "change-me-please")
HOST = "0.0.0.0"
PORT = 5000
