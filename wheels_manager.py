#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Brandherm - Reifenmanager (Sommer/Winter) - Ein-Datei-Web-App
- Deutsche moderne UI (Bootstrap 5), Version im Navbar
- MVC-Architektur in einer Datei:
    * Models: SQLAlchemy ORM
    * Controllers: Flask-Routen
    * Views: Jinja2-Templates als Strings (DictLoader)
- Gemeinsame, sichere DB (SQLite mit WAL & secure_delete)
- Automatische Backups (Intervall & Anzahl in UI konfigurierbar)
- Funktionen: Hinzufügen, Bearbeiten, Sicher Löschen, Suchen, Freie Positionen

Start:
    pip install flask sqlalchemy
    python wheels_manager.py
Zugriff im LAN:
    http://<SERVER-IP>:5000
"""
# ========================================================
# IMPORTS
# ========================================================
import os
import re
import threading
import time
import csv
import sqlite3
from datetime import datetime, timedelta, timezone
import secrets

from flask import (
    Flask, request, redirect, url_for, flash, session,
    send_from_directory, render_template, abort, Response
)
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Text, UniqueConstraint,
    event
)
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session
from sqlalchemy.exc import IntegrityError

# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from config import (VERSION, APP_NAME, DB_PATH, BACKUP_DIR, SECRET_KEY,
                    HOST, PORT)
from db import engine, SessionLocal
from models import WheelSet, Settings, AuditLog
from positions import (is_valid_position, SORTED_POSITIONS,
                       get_occupied_positions, first_free_position,
                       free_positions)
from utils import get_csrf_token, validate_csrf



# ------------------------------------------------------------
# Flask-App
# ------------------------------------------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.jinja_env.globals["csrf_token"] = get_csrf_token
app.jinja_env.globals["APP_VERSION"] = VERSION
app.jinja_env.globals["APP_NAME"] = APP_NAME
app.jinja_env.globals["now"] = lambda: datetime.now(timezone.utc)

# ------------------------------------------------------------
# Backup-Manager (Thread)
# ------------------------------------------------------------
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
                    settings = Settings(backup_interval_minutes=60, backup_copies=10)
                    db.add(settings)
                    db.commit()
                interval = max(1, int(settings.backup_interval_minutes))
                due = False
                if self._last_run is None:
                    self._last_run = datetime.now(timezone.utc)
                else:
                    if datetime.now(timezone.utc) - self._last_run >= timedelta(minutes=interval):
                        due = True
                db.close()
                if due:
                    self.perform_backup()
                    self._last_run = datetime.now(timezone.utc)
            except Exception:
                # In der Praxis: logging einbauen
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

        # === NEW: CSV snapshot with same timestamp ===
        csvfile = os.path.join(self.backup_dir, f"wheel_storage_{ts}.csv")
        export_csv_snapshot(csvfile)

        db = SessionLocal()
        try:
            db.add(AuditLog(action="backup",
                            details=f"Backup erstellt: {os.path.basename(bfile)}"))
            db.commit()

            settings = db.query(Settings).first()
            keep = max(1, settings.backup_copies if settings else 10)

            # Retention DB
            backups_db = sorted(
                [f for f in os.listdir(self.backup_dir)
                if f.startswith("wheel_storage_") and f.endswith(".db")]
            )
            if len(backups_db) > keep:
                for f in backups_db[0:len(backups_db)-keep]:
                    try: os.remove(os.path.join(self.backup_dir, f))
                    except Exception: pass

            # === NEW: Retention CSV ===
            backups_csv = sorted(
                [f for f in os.listdir(self.backup_dir)
                if f.startswith("wheel_storage_") and f.endswith(".csv")]
            )
            if len(backups_csv) > keep:
                for f in backups_csv[0:len(backups_csv)-keep]:
                    try: os.remove(os.path.join(self.backup_dir, f))
                    except Exception: pass
        finally:
            db.close()


def export_csv_snapshot(target_path: str | None = None) -> str:
    """
    Exportiert alle Radsätze als CSV (UTF‑8 mit BOM, Semikolon getrennt) in BACKUP_DIR.
    Gibt den Pfad zur erzeugten Datei zurück.
    """
    db = SessionLocal()
    try:
        rows = db.query(WheelSet).order_by(WheelSet.storage_position.asc()).all()
        if target_path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            target_path = os.path.join(BACKUP_DIR, f"wheel_storage_{ts}.csv")
        # UTF-8 with BOM so Excel on Windows opens umlauts correctly
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
        # Audit
        db.add(AuditLog(action="backup_csv",
                        details=f"CSV exportiert: {os.path.basename(target_path)}"))
        db.commit()
        return target_path
    finally:
        db.close()

backup_manager = BackupManager(engine, BACKUP_DIR)
backup_manager.start()

# ------------------------------------------------------------
# Templates (Jinja2) – In einer Datei mit DictLoader
# ------------------------------------------------------------

# ------------------------------------------------------------
# Hilfsfunktionen
# ------------------------------------------------------------
def get_or_create_settings(db):
    s = db.query(Settings).first()
    if s is None:
        s = Settings(backup_interval_minutes=60, backup_copies=10)
        db.add(s)
        db.commit()
    return s

def log_action(db, action, wheelset_id=None, details=None):
    db.add(AuditLog(action=action, wheelset_id=wheelset_id, details=details))
    db.commit()

# ------------------------------------------------------------
# Controller / Routen
# ------------------------------------------------------------
@app.route("/")
def index():
    db = SessionLocal()
    try:
        total = db.query(WheelSet).count()
        nf = first_free_position(db)
        free_pos = free_positions(db)
        return render_template("index.html", total=total, next_free=nf,
                               free_positions=free_pos, free_count=len(free_pos), active="home")
    finally:
        db.close()

@app.route("/wheelsets")
def list_wheelsets():
    db = SessionLocal()
    try:
        q = request.args.get("q", "").strip()
        query = db.query(WheelSet)
        if q:
            like = f"%{q}%"
            query = query.filter(
                (WheelSet.customer_name.ilike(like)) |
                (WheelSet.license_plate.ilike(like)) |
                (WheelSet.car_type.ilike(like))
            )
        items = query.order_by(WheelSet.updated_at.desc()).all()
        return render_template("wheelsets_list.html", items=items, active="wheelsets")
    finally:
        db.close()

@app.route("/wheelsets/new", methods=["GET", "POST"])
def create_wheelset():
    db = SessionLocal()
    try:
        suggested = request.args.get("suggested") if request.method == "GET" else None

        occupied = get_occupied_positions(db)
        pos_choices = [p for p in SORTED_POSITIONS if p not in occupied]

        if request.method == "POST":
            validate_csrf()
            customer_name = request.form.get("customer_name", "").strip()
            license_plate = request.form.get("license_plate", "").strip()
            car_type = request.form.get("car_type", "").strip()
            note = (request.form.get("note", "") or "").strip() or None
            storage_position = request.form.get("storage_position", "").strip()

            if not (customer_name and license_plate and car_type and storage_position):
                flash("Bitte alle Pflichtfelder ausfüllen.", "error")
                return redirect(url_for("create_wheelset"))

            if not is_valid_position(storage_position):
                flash("Ungültige Position.", "error")
                return redirect(url_for("create_wheelset"))

            if storage_position in occupied:
                flash("Position ist bereits belegt.", "error")
                return redirect(url_for("create_wheelset"))

            w = WheelSet(
                customer_name=customer_name,
                license_plate=license_plate,
                car_type=car_type,
                note=note,
                storage_position=storage_position
            )
            db.add(w)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Position bereits belegt oder Datenkonflikt.", "error")
                return redirect(url_for("create_wheelset"))

            log_action(db, "create", w.id, f"Angelegt @ {w.storage_position} für {w.customer_name} [{w.license_plate}]")
            flash("Radsatz wurde angelegt.", "success")
            return redirect(url_for("list_wheelsets"))

        return render_template("wheelset_form.html", w=None, editing=False,
                               positions=pos_choices, suggested=suggested, active="wheelsets")
    finally:
        db.close()

@app.route("/wheelsets/<int:wid>/edit", methods=["GET", "POST"])
def edit_wheelset(wid):
    db = SessionLocal()
    try:
        w = db.query(WheelSet).get(wid)
        if not w:
            abort(404, description="Radsatz nicht gefunden.")

        occupied = get_occupied_positions(db)
        occupied.discard(w.storage_position)  # eigene Position freigeben
        pos_choices = [p for p in SORTED_POSITIONS if p not in occupied]

        if request.method == "POST":
            validate_csrf()
            customer_name = request.form.get("customer_name", "").strip()
            license_plate = request.form.get("license_plate", "").strip()
            car_type = request.form.get("car_type", "").strip()
            note = (request.form.get("note", "") or "").strip() or None
            storage_position = request.form.get("storage_position", "").strip()

            if not (customer_name and license_plate and car_type and storage_position):
                flash("Bitte alle Pflichtfelder ausfüllen.", "error")
                return redirect(url_for("edit_wheelset", wid=wid))

            if not is_valid_position(storage_position):
                flash("Ungültige Position.", "error")
                return redirect(url_for("edit_wheelset", wid=wid))

            if storage_position in occupied:
                flash("Position ist bereits belegt.", "error")
                return redirect(url_for("edit_wheelset", wid=wid))

            old_pos = w.storage_position
            w.customer_name = customer_name
            w.license_plate = license_plate
            w.car_type = car_type
            w.note = note
            w.storage_position = storage_position

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Datenkonflikt beim Speichern.", "error")
                return redirect(url_for("edit_wheelset", wid=wid))

            log_action(db, "update", w.id, f"Geändert: {old_pos} -> {w.storage_position}")
            flash("Radsatz wurde aktualisiert.", "success")
            return redirect(url_for("list_wheelsets"))

        return render_template("wheelset_form.html", w=w, editing=True,
                               positions=pos_choices, suggested=None, active="wheelsets")
    finally:
        db.close()


@app.route("/wheelsets/<int:wid>/delete", methods=["GET"])
def delete_wheelset_confirm(wid):
    db = SessionLocal()
    try:
        w = db.query(WheelSet).get(wid)
        if not w:
            abort(404, description="Radsatz nicht gefunden.")
        return render_template("delete_confirm.html", w=w, active="wheelsets")
    finally:
        db.close()


@app.route("/wheelsets/<int:wid>/delete", methods=["POST"])
def delete_wheelset(wid):
    validate_csrf()
    db = SessionLocal()
    try:
        w = db.query(WheelSet).get(wid)
        if not w:
            abort(404, description="Radsatz nicht gefunden.")
        confirm_plate = (request.form.get("confirm_plate", "") or "").strip()
        if confirm_plate != w.license_plate:
            flash("Bestätigung fehlgeschlagen (Kennzeichen stimmt nicht).", "error")
            return redirect(url_for("delete_wheelset_confirm", wid=wid))

        pos = w.storage_position
        db.delete(w)
        db.commit()
        log_action(db, "delete", wid, f"Gelöscht @ {pos}")
        flash("Radsatz wurde sicher gelöscht.", "success")
        return redirect(url_for("list_wheelsets"))
    finally:
        db.close()


@app.route("/positions")
def positions():
    db = SessionLocal()
    try:
        nf = first_free_position(db)
        fp = free_positions(db)
        return render_template("positions.html", next_free=nf, free_positions=fp, active="positions")
    finally:
        db.close()


@app.route("/settings", methods=["GET", "POST"])
def settings():
    db = SessionLocal()
    try:
        s = get_or_create_settings(db)
        if request.method == "POST":
            validate_csrf()
            try:
                interval = int(request.form.get("backup_interval_minutes", "60"))
                copies = int(request.form.get("backup_copies", "10"))
                s.backup_interval_minutes = max(1, interval)
                s.backup_copies = max(1, copies)
                db.commit()
                flash("Einstellungen gespeichert.", "success")
            except Exception:
                db.rollback()
                flash("Fehler beim Speichern der Einstellungen.", "error")
        return render_template("settings.html", s=s, active="settings")
    finally:
        db.close()


@app.route("/backups")
def backups():
    files = []
    for f in os.listdir(BACKUP_DIR):
        if f.startswith("wheel_storage_") and (f.endswith(".db") or f.endswith(".csv")):
            p = os.path.join(BACKUP_DIR, f)
            try:
                size_kb = max(1, os.path.getsize(p)//1024)
                mtime = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
                ftype = "csv" if f.endswith(".csv") else "db"
                files.append({"name": f, "size_kb": size_kb, "mtime": mtime, "type": ftype})
            except Exception:
                pass
    # newest first
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return render_template("backups.html", backups=files, active="backups")


@app.route("/backups/download/<path:filename>")
def download_backup(filename):
    if not (filename.startswith("wheel_storage_")
            and (filename.endswith(".db") or filename.endswith(".csv"))):
        abort(403)
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)


@app.route("/backups/export_csv")
def export_csv_now():
    try:
        export_csv_snapshot()  # timestamped file in BACKUP_DIR
        flash("CSV-Export wurde erstellt.", "success")
    except Exception as e:
        flash(f"CSV-Export fehlgeschlagen: {e}", "error")
    return redirect(url_for("backups"))


@app.route("/backups/run")
def run_backup():
    try:
        backup_manager.perform_backup()
        flash("Backup wurde erstellt.", "success")
    except Exception as e:
        flash(f"Backup fehlgeschlagen: {e}", "error")
    return redirect(url_for("backups"))


@app.route("/favicon.ico")
def favicon():
    # Unterdrückt 404 für Favicon
    return Response(status=204)

# ------------------------------------------------------------
# App-Start
# ------------------------------------------------------------
if __name__ == "__main__":
    print(f"{APP_NAME} v{VERSION} läuft auf http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
