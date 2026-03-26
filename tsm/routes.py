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
import json
import os
from datetime import datetime
from flask import (
    request, redirect, url_for, flash, render_template, abort,
    send_from_directory, jsonify, g
)
from sqlalchemy.exc import IntegrityError

# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from tsm.db import SessionLocal
from tsm.models import WheelSet, Settings, AuditLog
from tsm.positions import (
    is_valid_position, get_occupied_positions,
    first_free_position, free_positions, get_disabled_positions,
    is_usable_position, position_sort_key, get_effective_positions,
    save_custom_positions, reset_custom_positions,
    SORTED_POSITIONS,
)
from tsm.utils import (
    validate_csrf,
    is_valid_license_plate,
    normalize_license_plate,
)
from tsm.i18n import gettext as _
# for route use (CSV)
from tsm.backup_manager import export_csv_snapshot
from tsm.self_update import (
    get_update_info, invalidate_update_cache,
    check_for_update, _is_frozen,
)
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
    # ---- dark-mode context processor (shared everywhere) ----
    # Cache the value in app.config to avoid a DB query on every request.
    # Refreshed when settings are saved.
    def _refresh_dark_mode():
        db = SessionLocal()
        try:
            s = db.query(Settings).first()
            app.config["_TSM_DARK_MODE"] = s.dark_mode if s else False
        except Exception:
            app.config.setdefault("_TSM_DARK_MODE", False)
        finally:
            SessionLocal.remove()

    _refresh_dark_mode()

    @app.context_processor
    def inject_dark_mode():
        return {"dark_mode": app.config.get("_TSM_DARK_MODE", False)}

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
            SessionLocal.remove()

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
            SessionLocal.remove()

    @app.route("/wheelsets/new", methods=["GET", "POST"])
    def create_wheelset():
        db = SessionLocal()
        try:
            suggested = request.args.get("suggested") \
                if request.method == "GET" else None
            occupied = get_occupied_positions(db)
            disabled = get_disabled_positions(db)
            effective = get_effective_positions(db)
            pos_choices = [p for p in effective
                           if p not in occupied and p not in disabled]

            if request.method == "POST":
                validate_csrf()
                customer_name = request.form.get("customer_name", "").strip()
                license_plate = normalize_license_plate(
                    request.form.get("license_plate", ""))
                car_type = request.form.get("car_type", "").strip()
                note = (request.form.get("note", "") or "").strip() or None
                storage_position = request.form.get(
                    "storage_position", "").strip()

                if not (customer_name and license_plate and car_type and
                        storage_position):
                    flash(_("fill_required_fields"), "error")
                    return redirect(url_for("create_wheelset"))

                if not is_valid_license_plate(license_plate):
                    flash(_("invalid_plate"), "error")
                    return redirect(url_for("create_wheelset"))

                if not is_valid_position(storage_position):
                    flash(_("invalid_position"), "error")
                    return redirect(url_for("create_wheelset"))

                if not is_usable_position(db, storage_position):
                    flash(_("position_disabled"), "error")
                    return redirect(url_for("create_wheelset"))

                if storage_position in occupied:
                    flash(_("position_occupied"), "error")
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
                    flash(_("position_conflict"), "error")
                    return redirect(url_for("create_wheelset"))

                log_action(db,
                           "create",
                           w.id,
                           f"Angelegt @ {w.storage_position} für " +
                           f"{w.customer_name} [{w.license_plate}]")
                flash(_("wheelset_created"), "success")
                return redirect(url_for("list_wheelsets"))

            return render_template("wheelset_form.html", w=None, editing=False,
                                   positions=pos_choices, suggested=suggested,
                                   active="wheelsets")
        finally:
            SessionLocal.remove()

    @app.route("/wheelsets/<int:wid>/edit", methods=["GET", "POST"])
    def edit_wheelset(wid):
        db = SessionLocal()
        try:
            w = db.get(WheelSet, wid)
            if not w:
                abort(404, description="Radsatz nicht gefunden.")

            occupied = get_occupied_positions(db)
            occupied.discard(w.storage_position)
            disabled = get_disabled_positions(db)
            effective = get_effective_positions(db)
            # Current position may be disabled later;
            # keep it selectable for editing,
            # but disallow changing to other disabled ones.
            pos_choices = [
                p for p in effective if
                (p not in occupied)
                and (p not in disabled
                     or p == w.storage_position)
            ]
            if request.method == "POST":
                validate_csrf()
                customer_name = request.form.get("customer_name", "").strip()
                license_plate = normalize_license_plate(
                    request.form.get("license_plate", ""))
                car_type = request.form.get("car_type", "").strip()
                note_input = (request.form.get("note") or "").strip()
                note = None if (not note_input or note_input.lower() == "none") else note_input
                storage_position = request.form.get(
                    "storage_position", "").strip()

                if not (customer_name and license_plate and car_type and
                        storage_position):
                    flash(_("fill_required_fields"), "error")
                    return redirect(url_for("edit_wheelset", wid=wid))

                if not is_valid_license_plate(license_plate):
                    flash(_("invalid_plate"), "error")
                    return redirect(url_for("edit_wheelset", wid=wid))

                if not is_valid_position(storage_position):
                    flash(_("invalid_position"), "error")
                    return redirect(url_for("edit_wheelset", wid=wid))

                if storage_position in occupied:
                    flash(_("position_occupied"), "error")
                    return redirect(url_for("edit_wheelset", wid=wid))

                # Allow keeping current position even if disabled after assignment;
                # block switching to any disabled position
                if ((storage_position != w.storage_position) and
                        not is_usable_position(db, storage_position)):
                    flash(_("target_position_disabled"), "error")
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
                    flash(_("data_conflict"), "error")
                    return redirect(url_for("edit_wheelset", wid=wid))

                log_action(db, "update", w.id,
                           f"Geändert: {old_pos} -> {w.storage_position}")
                flash(_("wheelset_updated"), "success")
                return redirect(url_for("list_wheelsets"))

            return render_template("wheelset_form.html", w=w, editing=True,
                                   positions=pos_choices, suggested=None,
                                   active="wheelsets")
        finally:
            SessionLocal.remove()

    @app.route("/wheelsets/<int:wid>/delete", methods=["GET"])
    def delete_wheelset_confirm(wid):
        db = SessionLocal()
        try:
            w = db.get(WheelSet, wid)
            if not w:
                abort(404, description="Radsatz nicht gefunden.")
            return render_template("delete_confirm.html", w=w,
                                   active="wheelsets")
        finally:
            SessionLocal.remove()

    @app.route("/wheelsets/<int:wid>/delete", methods=["POST"])
    def delete_wheelset(wid):
        validate_csrf()
        db = SessionLocal()
        try:
            w = db.get(WheelSet, wid)
            if not w:
                abort(404, description="Radsatz nicht gefunden.")
            confirm_plate = (
                request.form.get("confirm_plate", "") or "").strip()
            if confirm_plate != w.license_plate:
                flash(_("confirm_failed"), "error")
                return redirect(url_for("delete_wheelset_confirm", wid=wid))

            pos = w.storage_position
            db.delete(w)
            db.commit()
            log_action(db, "delete", wid, f"Gelöscht @ {pos}")
            flash(_("wheelset_deleted"), "success")
            return redirect(url_for("list_wheelsets"))
        finally:
            SessionLocal.remove()

    @app.route("/positions")
    def positions():
        db = SessionLocal()
        try:
            nf = first_free_position(db)
            fp = free_positions(db)
            disabled = sorted(get_disabled_positions(db), key=position_sort_key)
            return render_template("positions.html",
                                   next_free=nf,
                                   free_positions=fp,
                                   disabled_positions=disabled,
                                   active="positions")
        finally:
            SessionLocal.remove()

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
                    copies = int(
                        request.form.get("backup_copies", "10"))
                    s.backup_interval_minutes = max(1, interval)
                    s.backup_copies = max(1, copies)
                    s.dark_mode = (
                        request.form.get("dark_mode") == "1"
                    )
                    s.auto_update = (
                        request.form.get("auto_update") == "1"
                    )
                    from tsm.i18n import SUPPORTED_LOCALES
                    lang = request.form.get("language", "de")
                    s.language = lang if lang in SUPPORTED_LOCALES else "de"
                    db.commit()
                    g._tsm_locale = s.language
                    _refresh_dark_mode()
                    flash(_("settings_saved"), "success")
                except Exception:
                    db.rollback()
                    flash(_("settings_error"), "error")
            return render_template(
                "settings.html", s=s, active="settings")
        finally:
            SessionLocal.remove()

    # ---- Position editor routes ----
    @app.route(
        "/settings/positions", methods=["GET", "POST"]
    )
    def settings_positions():
        from tsm.positions import disable_position, enable_position
        db = SessionLocal()
        try:
            effective = get_effective_positions(db)
            defaults = list(SORTED_POSITIONS)
            is_custom = effective != defaults
            disabled = get_disabled_positions(db)
            if request.method == "POST":
                validate_csrf()
                action = request.form.get("action")
                if action == "reset":
                    reset_custom_positions(db)
                    flash(_("positions_reset"), "success")
                    return redirect(
                        url_for("settings_positions"))
                if action == "save":
                    raw = request.form.get("positions_text", "")
                    lines = [
                        ln.strip()
                        for ln in raw.splitlines()
                        if ln.strip()
                    ]
                    if not lines:
                        flash(_("positions_min_one"), "error")
                        return redirect(
                            url_for("settings_positions"))
                    save_custom_positions(db, lines)
                    flash(_("positions_saved", n=len(lines)), "success")
                    return redirect(
                        url_for("settings_positions"))
                if action == "toggle_disabled":
                    code = request.form.get("code", "").strip()
                    if code:
                        if code in disabled:
                            enable_position(db, code)
                        else:
                            disable_position(db, code)
                    return redirect(url_for("settings_positions"))
            return render_template(
                "settings_positions.html",
                positions=effective,
                disabled=disabled,
                is_custom=is_custom,
                active="settings",
            )
        finally:
            SessionLocal.remove()

    # ---- Impressum ----
    @app.route("/impressum")
    def impressum():
        return render_template(
            "impressum.html", active="impressum"
        )

    @app.route("/backups")
    def backups():
        files = []
        try:
            entries = os.listdir(BACKUP_DIR)
        except FileNotFoundError:
            entries = []
        for f in entries:
            if f.startswith("wheel_storage_") and (f.endswith(".db") or
                                                   f.endswith(".csv")):
                p = os.path.join(BACKUP_DIR, f)
                try:
                    size_kb = max(1, os.path.getsize(p)//1024)
                    mtime = datetime.fromtimestamp(
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
        # Block path traversal attempts
        if ("/" in filename or "\\" in filename or ".." in filename):
            abort(403)
        if not (filename.startswith("wheel_storage_")
                and (filename.endswith(".db") or filename.endswith(".csv"))):
            abort(403)
        return send_from_directory(BACKUP_DIR, filename, as_attachment=True)

    @app.route("/backups/export_csv", methods=["POST"])
    def export_csv_now():
        validate_csrf()
        try:
            export_csv_snapshot()
            flash(_("csv_created"), "success")
        except Exception as e:
            flash(_("csv_failed", e=e), "error")
        return redirect(url_for("backups"))

    # We won't start BackupManager here to avoid duplicate threads.
    # The run.py will handle it once.
    @app.route("/backups/run", methods=["POST"])
    def run_backup():
        validate_csrf()
        # local import to avoid early start
        from tsm.backup_manager import BackupManager
        from tsm.db import engine
        try:
            mgr = BackupManager(engine, BACKUP_DIR)
            mgr.perform_backup()
            flash(_("backup_created"), "success")
        except Exception as e:
            flash(_("backup_failed", e=e), "error")
        return redirect(url_for("backups"))

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            app.static_folder, "favicon.ico",
            mimetype="image/vnd.microsoft.icon"
        )

    # ---- Update management API ----
    @app.route("/api/update-check")
    def api_update_check():
        """AJAX endpoint: return update availability as JSON."""
        info = get_update_info()
        return jsonify(info)

    @app.route("/api/update-check", methods=["POST"])
    def api_update_check_refresh():
        """Force-refresh the cached update info."""
        validate_csrf()
        invalidate_update_cache()
        info = get_update_info()
        return jsonify(info)

    @app.route("/settings/update-now", methods=["POST"])
    def update_now():
        """Trigger an immediate update (frozen EXE only)."""
        validate_csrf()
        if not _is_frozen():
            flash(_("update_exe_only"), "info")
            return redirect(url_for("settings"))

        try:
            updated = check_for_update()
            if updated:
                flash(_("update_installed"), "success")
            else:
                flash(_("update_none"), "info")
        except Exception as e:
            flash(_("update_failed", e=e), "error")

        return redirect(url_for("settings"))
