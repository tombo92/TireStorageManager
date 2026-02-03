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
import sqlite3
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from config import DB_PATH
from models import Base  # ensure models import happens before create_all

# ========================================================
# GLOABALS
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
