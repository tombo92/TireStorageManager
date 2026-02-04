#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
App Configurations
"""
# ========================================================
# IMPORTS
# ========================================================
import os
from pathlib import Path

# ========================================================
# GLOABALS
# ========================================================
VERSION = "1.1.4"
APP_NAME = "Brandherm - Reifenmanager"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "db/wheel_storage.db")
BACKUP_DIR = str(BASE_DIR / "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# Set Production via ENV!
SECRET_KEY = os.environ.get("WHEELS_SECRET_KEY", "change-me-please")
HOST = "0.0.0.0"
PORT = 5000
