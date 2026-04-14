#!/usr/bin/env python
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
URL route handlers for TireStorageManager.

All route functions are defined at module level and registered in
``register_routes(app)`` via ``app.add_url_rule()``.  This keeps each
handler independently importable and directly testable.

Dark mode is cached in ``app.config["_TSM_DARK_MODE"]`` and refreshed
via ``_refresh_dark_mode()`` at startup and after every settings save.
"""
# ========================================================
# IMPORTS
# ========================================================
import logging as _logging
import os
from collections import defaultdict
from datetime import datetime

from flask import (
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from sqlalchemy.exc import IntegrityError

from config import BACKUP_DIR
from tsm.backup_manager import export_csv_snapshot
from tsm.db import SessionLocal, get_or_create_settings, log_action
from tsm.i18n import gettext as _
from tsm.models import AuditLog, Settings, WheelSet
from tsm.positions import (
    RE_CONTAINER,
    RE_GARAGE,
    SORTED_POSITIONS,
    first_free_position,
    free_positions,
    get_disabled_positions,
    get_effective_positions,
    get_occupied_positions,
    is_usable_position,
    is_valid_position,
    position_sort_key,
    reset_custom_positions,
    save_custom_positions,
)
from tsm.self_update import (
    _is_frozen,
    check_for_update,
    get_update_info,
    invalidate_update_cache,
)
from tsm.utils import (
    is_valid_license_plate,
    normalize_license_plate,
    overdue_season,
    validate_csrf,
)

_log = _logging.getLogger("TSM.routes")


# ========================================================
# DARK-MODE CACHE HELPER
# ========================================================

def _refresh_dark_mode() -> None:
    """Sync the dark-mode flag from the DB into ``current_app.config``.

    Safe to call both at startup (inside an ``app.app_context()``) and
    from within request handlers (where ``current_app`` is available).
    """
    db = SessionLocal()
    try:
        s = db.query(Settings).first()
        current_app.config["_TSM_DARK_MODE"] = s.dark_mode if s else False
    except Exception:
        current_app.config.setdefault("_TSM_DARK_MODE", False)
    finally:
        SessionLocal.remove()


# ========================================================
# ROUTE HANDLERS
# ========================================================

def index():
    db = SessionLocal()
    try:
        total_positions = len(get_effective_positions(db))
        disabled = get_disabled_positions(db)
        occupied = get_occupied_positions(db)
        free_pos = free_positions(db)
        total_wheelsets = db.query(WheelSet).count()
        usable_positions = total_positions - len(disabled)
        occupancy_pct = (
            round(total_wheelsets / usable_positions * 100)
            if usable_positions > 0 else 0
        )
        recent_activity = (
            db.query(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(5)
            .all()
        )
        from sqlalchemy import func
        top_cars = (
            db.query(WheelSet.car_type,
                     func.count(WheelSet.id).label("cnt"))
            .group_by(WheelSet.car_type)
            .order_by(func.count(WheelSet.id).desc())
            .limit(3)
            .all()
        )
        nf = first_free_position(db)
        return render_template(
            "index.html",
            total=total_wheelsets,
            total_positions=total_positions,
            usable_positions=usable_positions,
            occupied_count=len(occupied),
            free_count=len(free_pos),
            free_positions=free_pos,
            occupancy_pct=occupancy_pct,
            recent_activity=recent_activity,
            top_cars=top_cars,
            next_free=nf,
            active="home",
        )
    finally:
        SessionLocal.remove()


def list_wheelsets():
    db = SessionLocal()
    try:
        q = request.args.get("q", "").strip()
        sort = request.args.get("sort", "updated_desc")
        filter_pos = request.args.get("filter_pos", "")
        filter_season = request.args.get("filter_season", "")

        query = db.query(WheelSet)
        if q:
            like = f"%{q}%"
            query = query.filter(
                (WheelSet.customer_name.ilike(like)) |
                (WheelSet.license_plate.ilike(like)) |
                (WheelSet.car_type.ilike(like)) |
                (WheelSet.note.ilike(like))
            )
        if filter_pos == "container":
            query = query.filter(WheelSet.storage_position.like("C%"))
        elif filter_pos == "garage":
            query = query.filter(WheelSet.storage_position.like("GR%"))
        if filter_season:
            query = query.filter(WheelSet.season == filter_season)

        sort_map = {
            "updated_desc":  WheelSet.updated_at.desc(),
            "updated_asc":   WheelSet.updated_at.asc(),
            "customer_asc":  WheelSet.customer_name.asc(),
            "customer_desc": WheelSet.customer_name.desc(),
            "plate_asc":     WheelSet.license_plate.asc(),
            "plate_desc":    WheelSet.license_plate.desc(),
            "position_asc":  WheelSet.storage_position.asc(),
            "position_desc": WheelSet.storage_position.desc(),
        }
        order = sort_map.get(sort, WheelSet.updated_at.desc())
        items = query.order_by(order).all()
        s = get_or_create_settings(db)

        overdue_ids: set[int] = set()
        if s.enable_tire_details:
            month = datetime.now().month
            due_season = overdue_season(month)
            if due_season is not None:
                for w in items:
                    if w.season == due_season:
                        overdue_ids.add(w.id)

        return render_template(
            "wheelsets_list.html",
            items=items,
            settings=s,
            overdue_ids=overdue_ids,
            active="wheelsets",
            sort=sort,
            filter_pos=filter_pos,
            filter_season=filter_season,
        )
    finally:
        SessionLocal.remove()


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
        s = get_or_create_settings(db)

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
            if s.enable_tire_details:
                w.tire_manufacturer = (
                    request.form.get("tire_manufacturer", "")
                    .strip() or None
                )
                w.tire_size = (
                    request.form.get("tire_size", "").strip() or None
                )
                w.tire_age = (
                    request.form.get("tire_age", "").strip() or None
                )
                season = request.form.get("season", "").strip()
                w.season = season if season in (
                    "sommer", "winter", "allwetter") else None
                rim = request.form.get("rim_type", "").strip()
                w.rim_type = rim if rim in ("stahl", "alu") else None
                w.exchange_note = (
                    request.form.get("exchange_note", "")
                    .strip() or None
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
                       f"Angelegt @ {w.storage_position} fuer "
                       f"{w.customer_name} [{w.license_plate}]")
            flash(_("wheelset_created"), "success")
            return redirect(url_for("list_wheelsets"))

        return render_template("wheelset_form.html", w=None, editing=False,
                               positions=pos_choices, suggested=suggested,
                               settings=s, active="wheelsets")
    finally:
        SessionLocal.remove()


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
        pos_choices = [
            p for p in effective if
            (p not in occupied)
            and (p not in disabled
                 or p == w.storage_position)
        ]
        s = get_or_create_settings(db)
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

            if s.enable_tire_details:
                w.tire_manufacturer = (
                    request.form.get("tire_manufacturer", "")
                    .strip() or None
                )
                w.tire_size = (
                    request.form.get("tire_size", "").strip() or None
                )
                w.tire_age = (
                    request.form.get("tire_age", "").strip() or None
                )
                season = request.form.get("season", "").strip()
                w.season = season if season in (
                    "sommer", "winter", "allwetter") else None
                rim = request.form.get("rim_type", "").strip()
                w.rim_type = rim if rim in ("stahl", "alu") else None
                w.exchange_note = (
                    request.form.get("exchange_note", "")
                    .strip() or None
                )

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash(_("data_conflict"), "error")
                return redirect(url_for("edit_wheelset", wid=wid))

            log_action(db, "update", w.id,
                       f"Geaendert: {old_pos} -> {w.storage_position}")
            flash(_("wheelset_updated"), "success")
            return redirect(url_for("list_wheelsets"))

        return render_template("wheelset_form.html", w=w, editing=True,
                               positions=pos_choices, suggested=None,
                               settings=s, active="wheelsets")
    finally:
        SessionLocal.remove()


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
        log_action(db, "delete", wid, f"Geloescht @ {pos}")
        flash(_("wheelset_deleted"), "success")
        return redirect(url_for("list_wheelsets"))
    finally:
        SessionLocal.remove()


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
                s.enable_tire_details = (
                    request.form.get("enable_tire_details") == "1"
                )
                s.enable_seasonal_tracking = (
                    request.form.get(
                        "enable_seasonal_tracking") == "1"
                    and s.enable_tire_details
                )
                db.commit()
                g._tsm_locale = s.language
                _refresh_dark_mode()
                flash(_("settings_saved"), "success")
            except Exception:
                _log.exception("Error saving settings")
                db.rollback()
                flash(_("settings_error"), "error")
        return render_template(
            "settings.html", s=s, active="settings")
    finally:
        SessionLocal.remove()


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


def impressum():
    return render_template("impressum.html", active="impressum")


def backups():
    seen: dict = {}
    try:
        entries = os.listdir(BACKUP_DIR)
    except FileNotFoundError:
        entries = []
    for f in entries:
        if not f.startswith("wheel_storage_"):
            continue
        for ext in (".db", ".csv", ".xlsx"):
            if f.endswith(ext):
                p = os.path.join(BACKUP_DIR, f)
                try:
                    size_kb = max(1, os.path.getsize(p) // 1024)
                    mtime = datetime.fromtimestamp(
                        os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
                    ts = f[len("wheel_storage_"):f.rfind(".")]
                    ftype = ext.lstrip(".")
                    if ts not in seen:
                        seen[ts] = {"ts": ts, "mtime": mtime, "files": []}
                    seen[ts]["files"].append(
                        {"name": f, "type": ftype, "size_kb": size_kb}
                    )
                except Exception:
                    _log.exception("Error reading backup file %s", f)
    type_order = {"db": 0, "csv": 1, "xlsx": 2}
    groups = sorted(seen.values(), key=lambda grp: grp["ts"], reverse=True)
    for grp in groups:
        grp["files"].sort(key=lambda x: type_order.get(x["type"], 9))
    return render_template(
        "backups.html", backup_groups=groups, active="backups"
    )


def inventory_print():
    db = SessionLocal()
    try:
        rows = db.query(WheelSet).all()
        rows = sorted(rows,
                      key=lambda r: position_sort_key(r.storage_position))
    finally:
        SessionLocal.remove()

    groups_map: dict = defaultdict(list)
    for r in rows:
        m = RE_CONTAINER.match(r.storage_position)
        if m:
            key = ("container", int(m.group(1)),
                   f"Container {m.group(1)}")
        else:
            m2 = RE_GARAGE.match(r.storage_position)
            if m2:
                key = ("garage", int(m2.group(1)),
                       f"Garage \u2013 Regal {m2.group(1)}")
            else:
                key = ("other", 0, "Sonstige Positionen")
        groups_map[key].append(r)

    sorted_keys = sorted(
        groups_map.keys(),
        key=lambda x: (
            0 if x[0] == "container" else 1 if x[0] == "garage" else 2,
            x[1]
        )
    )
    groups = [
        {"label": k[2], "type": k[0], "rows": groups_map[k]}
        for k in sorted_keys
    ]
    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    return render_template(
        "inventory_print.html",
        groups=groups,
        generated_at=generated_at,
        total=len(rows),
    )


def download_backup(filename):
    if ("/" in filename or "\\" in filename or ".." in filename):
        abort(403)
    if not (filename.startswith("wheel_storage_")
            and (filename.endswith(".db")
                 or filename.endswith(".csv")
                 or filename.endswith(".xlsx"))):
        abort(403)
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)


def export_csv_now():
    validate_csrf()
    try:
        export_csv_snapshot()
        flash(_("csv_created"), "success")
    except Exception as e:
        _log.exception("CSV export failed")
        flash(_("csv_failed", e=e), "error")
    return redirect(url_for("backups"))


def run_backup():
    validate_csrf()
    from tsm.backup_manager import BackupManager
    from tsm.db import engine
    try:
        mgr = BackupManager(engine, BACKUP_DIR)
        mgr.perform_backup()
        flash(_("backup_created"), "success")
    except Exception as e:
        _log.exception("Manual backup failed")
        flash(_("backup_failed", e=e), "error")
    return redirect(url_for("backups"))


def favicon():
    return send_from_directory(
        current_app.static_folder, "favicon.ico",
        mimetype="image/vnd.microsoft.icon"
    )


def api_update_check():
    """Return update availability as JSON."""
    info = get_update_info()
    return jsonify(info)


def api_update_check_refresh():
    """Force-refresh the cached update info and return new state."""
    validate_csrf()
    invalidate_update_cache()
    info = get_update_info()
    return jsonify(info)


def update_now():
    """Trigger an immediate self-update (frozen EXE only)."""
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
        _log.exception("Update-now failed")
        flash(_("update_failed", e=e), "error")

    return redirect(url_for("settings"))


# ========================================================
# REGISTRATION
# ========================================================

def register_routes(app) -> None:
    """Register all route handlers and the dark-mode context processor."""
    with app.app_context():
        _refresh_dark_mode()

    @app.context_processor
    def inject_dark_mode():
        return {"dark_mode": app.config.get("_TSM_DARK_MODE", False)}

    # Wheelsets
    app.add_url_rule("/", "index", index)
    app.add_url_rule("/wheelsets", "list_wheelsets", list_wheelsets)
    app.add_url_rule("/wheelsets/new", "create_wheelset", create_wheelset,
                     methods=["GET", "POST"])
    app.add_url_rule("/wheelsets/<int:wid>/edit", "edit_wheelset",
                     edit_wheelset, methods=["GET", "POST"])
    app.add_url_rule("/wheelsets/<int:wid>/delete", "delete_wheelset_confirm",
                     delete_wheelset_confirm)
    app.add_url_rule("/wheelsets/<int:wid>/delete", "delete_wheelset",
                     delete_wheelset, methods=["POST"])

    # Positions
    app.add_url_rule("/positions", "positions", positions)
    app.add_url_rule("/settings/positions", "settings_positions",
                     settings_positions, methods=["GET", "POST"])

    # Settings
    app.add_url_rule("/settings", "settings", settings,
                     methods=["GET", "POST"])

    # Backups
    app.add_url_rule("/backups", "backups", backups)
    app.add_url_rule("/backups/inventory", "inventory_print", inventory_print)
    app.add_url_rule("/backups/download/<path:filename>", "download_backup",
                     download_backup)
    app.add_url_rule("/backups/export_csv", "export_csv_now", export_csv_now,
                     methods=["POST"])
    app.add_url_rule("/backups/run", "run_backup", run_backup,
                     methods=["POST"])

    # Misc
    app.add_url_rule("/impressum", "impressum", impressum)
    app.add_url_rule("/favicon.ico", "favicon", favicon)

    # Update API
    app.add_url_rule("/api/update-check", "api_update_check",
                     api_update_check)
    app.add_url_rule("/api/update-check", "api_update_check_refresh",
                     api_update_check_refresh, methods=["POST"])
    app.add_url_rule("/settings/update-now", "update_now", update_now,
                     methods=["POST"])
