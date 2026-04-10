#!/usr/bin/env python
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
from sqlalchemy.orm import scoped_session, sessionmaker

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
    # Override SQLite's ASCII-only lower() with Python's Unicode-aware version
    # so that ilike/LIKE queries work correctly with German umlauts etc.
    dbapi_connection.create_function(
        "lower", 1,
        lambda s: s.lower() if isinstance(s, str) else s
    )
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
        if "auto_update" not in existing:
            conn.execute(text(
                "ALTER TABLE settings "
                "ADD COLUMN auto_update BOOLEAN NOT NULL DEFAULT 1"
            ))
        if "language" not in existing:
            conn.execute(text(
                "ALTER TABLE settings "
                "ADD COLUMN language VARCHAR(10) NOT NULL DEFAULT 'de'"
            ))
        if "enable_tire_details" not in existing:
            conn.execute(text(
                "ALTER TABLE settings "
                "ADD COLUMN enable_tire_details BOOLEAN NOT NULL DEFAULT 0"
            ))
        if "enable_seasonal_tracking" not in existing:
            conn.execute(text(
                "ALTER TABLE settings "
                "ADD COLUMN enable_seasonal_tracking "
                "BOOLEAN NOT NULL DEFAULT 0"
            ))

    if "wheel_sets" in insp.get_table_names():
        ws_existing = {c["name"] for c in insp.get_columns("wheel_sets")}
        with engine.begin() as conn:
            for col, typ in [
                ("tire_manufacturer", "VARCHAR(100)"),
                ("tire_size",         "VARCHAR(50)"),
                ("tire_age",          "VARCHAR(20)"),
                ("season",            "VARCHAR(20)"),
                ("rim_type",          "VARCHAR(20)"),
                ("exchange_note",     "TEXT"),
            ]:
                if col not in ws_existing:
                    conn.execute(text(
                        f"ALTER TABLE wheel_sets ADD COLUMN {col} {typ}"
                    ))


_migrate()
