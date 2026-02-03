#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
disable/enable positions
"""
# ========================================================
# IMPORTS
# ========================================================
from db import SessionLocal
from positions import disable_position, enable_position

# ========================================================
# MAIN
# ========================================================
db = SessionLocal()
try:
    print(disable_position(db, "C1ROL", reason="Shelf damaged"))  # True on first time
    print(enable_position(db, "C1ROL"))                           # True when removed
finally:
    db.close()
