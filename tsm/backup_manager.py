#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Backup Manager
"""
# ========================================================
# IMPORTS
# ========================================================
import os
import csv
import time
import threading
import sqlite3
from datetime import datetime, timezone, timedelta
# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from config import BACKUP_DIR
from tsm.db import engine, SessionLocal
from tsm.models import WheelSet, Settings, AuditLog


# ========================================================
# CLASSES
# ========================================================
class BackupManager(threading.Thread):
    daemon = True

    def __init__(self, engine, backup_dir):
        super().__init__()
        self.engine = engine
        self.backup_dir = backup_dir
        self._stop = threading.Event()
        self._last_run = None

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                db = SessionLocal()
                settings = db.query(Settings).first()
                if settings is None:
                    settings = Settings(backup_interval_minutes=60,
                                        backup_copies=10)
                    db.add(settings)
                    db.commit()
                interval = max(1, int(settings.backup_interval_minutes))
                due = False
                if self._last_run is None:
                    self._last_run = datetime.now(timezone.utc)
                else:
                    if ((datetime.now(timezone.utc) - self._last_run) >=
                        timedelta(minutes=interval)):
                        due = True
                db.close()
                if due:
                    self.perform_backup()
                    self._last_run = datetime.now(timezone.utc)
            except Exception:
                pass
            time.sleep(30)

    def perform_backup(self):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        bfile = os.path.join(self.backup_dir, f"wheel_storage_{ts}.db")

        raw = engine.raw_connection()
        try:
            src = raw.connection  # sqlite3.Connection
            dest = sqlite3.connect(bfile)
            try:
                with dest:
                    src.backup(dest)
            finally:
                dest.close()
        finally:
            raw.close()

        csvfile = os.path.join(self.backup_dir, f"wheel_storage_{ts}.csv")
        export_csv_snapshot(csvfile)

        db = SessionLocal()
        try:
            db.add(AuditLog(action="backup",
                            details=f"Backup erstellt: {os.path.basename(
                                bfile)}"))
            db.commit()

            settings = db.query(Settings).first()
            keep = max(1, settings.backup_copies if settings else 10)

            backups_db = sorted(
                [f for f in os.listdir(self.backup_dir)
                 if f.startswith("wheel_storage_") and f.endswith(".db")]
            )
            if len(backups_db) > keep:
                for f in backups_db[0:len(backups_db)-keep]:
                    try:
                        os.remove(os.path.join(self.backup_dir, f))
                    except Exception:
                        pass

            backups_csv = sorted(
                [f for f in os.listdir(self.backup_dir)
                 if f.startswith("wheel_storage_") and f.endswith(".csv")]
            )
            if len(backups_csv) > keep:
                for f in backups_csv[0:len(backups_csv)-keep]:
                    try:
                        os.remove(os.path.join(self.backup_dir, f))
                    except Exception:
                        pass
        finally:
            db.close()


# ========================================================
# FUNCTIONS
# ========================================================
def export_csv_snapshot(target_path: str | None = None) -> str:
    db = SessionLocal()
    try:
        rows = db.query(WheelSet).order_by(
            WheelSet.storage_position.asc()).all()
        if target_path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            target_path = os.path.join(BACKUP_DIR, f"wheel_storage_{ts}.csv")
        with open(target_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(["customer_name", "license_plate", "car_type", "note",
                        "storage_position", "created_at", "updated_at"])
            for r in rows:
                w.writerow([
                    r.customer_name,
                    r.license_plate,
                    r.car_type,
                    r.note or "",
                    r.storage_position,
                    (r.created_at.isoformat() if r.created_at else ""),
                    (r.updated_at.isoformat() if r.updated_at else ""),
                ])
        db.add(AuditLog(action="backup_csv",
                        details=f"CSV exportiert: {os.path.basename(
                            target_path)}"))
        db.commit()
        return target_path
    finally:
        db.close()
