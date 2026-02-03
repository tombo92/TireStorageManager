#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
All routes attached to app
"""
# ========================================================
# IMPORTS
# ========================================================
import os
from flask import (
    request, redirect, url_for, flash, render_template, abort, Response,
    send_from_directory
)
from sqlalchemy.exc import IntegrityError

# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from db import SessionLocal
from models import WheelSet, Settings, AuditLog
from positions import (
    is_valid_position, SORTED_POSITIONS, get_occupied_positions,
    first_free_position, free_positions
)
from utils import validate_csrf
# for route use (CSV)
from backup_manager import BackupManager, export_csv_snapshot

from config import BACKUP_DIR


# ========================================================
# FUNCTIONS
# ========================================================
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


# --------------------------------------------------------
# Routes
# --------------------------------------------------------
def register_routes(app):
    @app.route("/")
    def index():
        db = SessionLocal()
        try:
            total = db.query(WheelSet).count()
            nf = first_free_position(db)
            free_pos = free_positions(db)
            return render_template("index.html", total=total, next_free=nf,
                                   free_positions=free_pos,
                                   free_count=len(free_pos), active="home")
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
            return render_template("wheelsets_list.html", items=items,
                                   active="wheelsets")
        finally:
            db.close()

    @app.route("/wheelsets/new", methods=["GET", "POST"])
    def create_wheelset():
        db = SessionLocal()
        try:
            suggested = request.args.get("suggested") \
                if request.method == "GET" else None
            occupied = get_occupied_positions(db)
            pos_choices = [p for p in SORTED_POSITIONS if p not in occupied]

            if request.method == "POST":
                validate_csrf()
                customer_name = request.form.get("customer_name", "").strip()
                license_plate = request.form.get("license_plate", "").strip()
                car_type = request.form.get("car_type", "").strip()
                note = (request.form.get("note", "") or "").strip() or None
                storage_position = request.form.get(
                    "storage_position", "").strip()

                if not (customer_name and license_plate and car_type and
                        storage_position):
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
                    flash("Position bereits belegt oder Datenkonflikt.",
                          "error")
                    return redirect(url_for("create_wheelset"))

                log_action(db,
                           "create",
                           w.id,
                           f"Angelegt @ {w.storage_position} für" +
                           f"{w.customer_name} [{w.license_plate}]")
                flash("Radsatz wurde angelegt.", "success")
                return redirect(url_for("list_wheelsets"))

            return render_template("wheelset_form.html", w=None, editing=False,
                                   positions=pos_choices, suggested=suggested,
                                   active="wheelsets")
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
            occupied.discard(w.storage_position)
            pos_choices = [p for p in SORTED_POSITIONS if p not in occupied]

            if request.method == "POST":
                validate_csrf()
                customer_name = request.form.get("customer_name", "").strip()
                license_plate = request.form.get("license_plate", "").strip()
                car_type = request.form.get("car_type", "").strip()
                note = (request.form.get("note", "") or "").strip() or None
                storage_position = request.form.get(
                    "storage_position", "").strip()

                if not (customer_name and license_plate and car_type and
                        storage_position):
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

                log_action(db, "update", w.id,
                           f"Geändert: {old_pos} -> {w.storage_position}")
                flash("Radsatz wurde aktualisiert.", "success")
                return redirect(url_for("list_wheelsets"))

            return render_template("wheelset_form.html", w=w, editing=True,
                                   positions=pos_choices, suggested=None,
                                   active="wheelsets")
        finally:
            db.close()

    @app.route("/wheelsets/<int:wid>/delete", methods=["GET"])
    def delete_wheelset_confirm(wid):
        db = SessionLocal()
        try:
            w = db.query(WheelSet).get(wid)
            if not w:
                abort(404, description="Radsatz nicht gefunden.")
            return render_template("delete_confirm.html", w=w,
                                   active="wheelsets")
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
            confirm_plate = (
                request.form.get("confirm_plate", "") or "").strip()
            if confirm_plate != w.license_plate:
                flash("Bestätigung fehlgeschlagen (Kennzeichen stimmt nicht).",
                      "error")
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
            return render_template("positions.html", next_free=nf,
                                   free_positions=fp, active="positions")
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
                    interval = int(request.form.get(
                        "backup_interval_minutes", "60"))
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
            if f.startswith("wheel_storage_") and (f.endswith(".db") or
                                                   f.endswith(".csv")):
                p = os.path.join(BACKUP_DIR, f)
                try:
                    size_kb = max(1, os.path.getsize(p)//1024)
                    mtime = __import__("datetime").datetime.fromtimestamp(
                        os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
                    ftype = "csv" if f.endswith(".csv") else "db"
                    files.append(
                        {"name": f,
                         "size_kb": size_kb,
                         "mtime": mtime,
                         "type": ftype})
                except Exception:
                    pass
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
            export_csv_snapshot()
            flash("CSV-Export wurde erstellt.", "success")
        except Exception as e:
            flash(f"CSV-Export fehlgeschlagen: {e}", "error")
        return redirect(url_for("backups"))

    # We won't start BackupManager here to avoid duplicate threads.
    # The run.py will handle it once.
    @app.route("/backups/run")
    def run_backup():
        # local import to avoid early start
        from backup_manager import BackupManager
        from db import engine
        try:
            mgr = BackupManager(engine, BACKUP_DIR)
            mgr.perform_backup()
            flash("Backup wurde erstellt.", "success")
        except Exception as e:
            flash(f"Backup fehlgeschlagen: {e}", "error")
        return redirect(url_for("backups"))

    @app.route("/favicon.ico")
    def favicon():
        return Response(status=204)
