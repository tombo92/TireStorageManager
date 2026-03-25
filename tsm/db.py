#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
DB
"""
# ========================================================
# IMPORTS
# ========================================================
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, scoped_session
# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from config import DB_PATH
from tsm.models import Base  # ensure models import happens before create_all

# ========================================================
# GLOBALS
# ========================================================
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False,
                                           autocommit=False))


# ========================================================
# EVENT LISTENER
# ========================================================
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA secure_delete=ON;")
    finally:
        cursor.close()


# ========================================================
# Create tables
# ========================================================
Base.metadata.create_all(bind=engine)


# ========================================================
# Lightweight schema migration (add new columns to existing DBs)
# ========================================================
def _migrate():
    """Add columns that may be missing from older database versions."""
    insp = inspect(engine)
    existing = {c["name"] for c in insp.get_columns("settings")}
    with engine.begin() as conn:
        if "dark_mode" not in existing:
            conn.execute(text(
                "ALTER TABLE settings "
                "ADD COLUMN dark_mode BOOLEAN NOT NULL DEFAULT 0"
            ))
        if "custom_positions_json" not in existing:
            conn.execute(text(
                "ALTER TABLE settings "
                "ADD COLUMN custom_positions_json TEXT"
            ))


_migrate()
