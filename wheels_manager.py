# wheels_manager.py
# -*- coding: utf-8 -*-
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
from jinja2 import DictLoader

# ------------------------------------------------------------
# Konfiguration
# ------------------------------------------------------------
VERSION = "1.0.3"
APP_NAME = "Brandherm - Reifenmanager"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "wheel_storage.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

SECRET_KEY = os.environ.get("WHEELS_SECRET_KEY", "change-me-please")  # In Produktion via ENV setzen!
HOST = "0.0.0.0"
PORT = 5000

# ------------------------------------------------------------
# Flask-App
# ------------------------------------------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY

# ------------------------------------------------------------
# DB / SQLAlchemy
# ------------------------------------------------------------
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},  # Threads erlauben
)

Base = declarative_base()
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))

# SQLite Pragmas for durability/concurrency/security
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA secure_delete=ON;")
    finally:
        cursor.close()

# ------------------------------------------------------------
# Modelle
# ------------------------------------------------------------
class WheelSet(Base):
    __tablename__ = "wheel_sets"

    id = Column(Integer, primary_key=True)
    customer_name = Column(String(200), nullable=False, index=True)  # Kundenname
    license_plate = Column(String(50), nullable=False, index=True)   # Kennzeichen
    car_type = Column(String(200), nullable=False, index=True)       # Fahrzeugtyp
    note = Column(Text, nullable=True)                               # Notiz
    storage_position = Column(String(20), nullable=False, unique=True, index=True)  # Lagerposition

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("storage_position", name="uq_storage_position"),
    )


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    backup_interval_minutes = Column(Integer, nullable=False, default=60)  # Intervall in Minuten
    backup_copies = Column(Integer, nullable=False, default=10)            # wie viele Sicherungen behalten
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    action = Column(String(50), nullable=False)  # 'create', 'update', 'delete', 'backup'
    wheelset_id = Column(Integer, nullable=True) # optional (bei backup None)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


Base.metadata.create_all(bind=engine)

# ------------------------------------------------------------
# Positionslogik (Validierung & Liste)
# ------------------------------------------------------------
CONTAINER_NUMBERS = [1, 2, 3, 4]
CONTAINER_SIDES = ["R", "L"]
LEVELS = ["O", "M", "U"]
CONTAINER_POSITIONS = ["LL", "L", "MM", "M", "RR", "R"]

GARAGE_SHELVES = list(range(1, 9))  # 1..8
GARAGE_POSITIONS = ["L", "M", "R"]  # Annahme: 3 Positionen

RE_CONTAINER = re.compile(r"^C([1-4])([RL])([OMU])(LL|L|MM|M|RR|R)$")
RE_GARAGE = re.compile(r"^GR([1-8])([OMU])([LMR])$")

def all_valid_positions():
    pos = []
    for c in CONTAINER_NUMBERS:
        for side in CONTAINER_SIDES:
            for lvl in LEVELS:
                for p in CONTAINER_POSITIONS:
                    pos.append(f"C{c}{side}{lvl}{p}")
    for g in GARAGE_SHELVES:
        for lvl in LEVELS:
            for p in GARAGE_POSITIONS:
                pos.append(f"GR{g}{lvl}{p}")
    return pos

ALL_POSITIONS = all_valid_positions()

def is_valid_position(code: str) -> bool:
    return bool(RE_CONTAINER.match(code) or RE_GARAGE.match(code))

def position_sort_key(code: str):
    if code.startswith("C"):
        m = RE_CONTAINER.match(code)
        if not m:
            return (0, 999, 9, 9, 9)
        c = int(m.group(1))
        side = m.group(2)
        lvl = m.group(3)
        p = m.group(4)
        side_order = {"R": 0, "L": 1}[side]
        lvl_order = {"O": 0, "M": 1, "U": 2}[lvl]
        pos_order = {v: i for i, v in enumerate(CONTAINER_POSITIONS)}[p]
        return (0, c, side_order, lvl_order, pos_order)
    else:
        m = RE_GARAGE.match(code)
        if not m:
            return (1, 999, 9, 9)
        g = int(m.group(1))
        lvl = m.group(2)
        p = m.group(3)
        lvl_order = {"O": 0, "M": 1, "U": 2}[lvl]
        pos_order = {v: i for i, v in enumerate(GARAGE_POSITIONS)}[p]
        return (1, g, lvl_order, pos_order)

SORTED_POSITIONS = sorted(ALL_POSITIONS, key=position_sort_key)

def get_occupied_positions(db) -> set[str]:
    rows = db.query(WheelSet.storage_position).all()  # list of tuples [(pos,), ...]
    return {r[0] for r in rows}

def first_free_position(db):
    occupied = get_occupied_positions(db)
    for code in SORTED_POSITIONS:
        if code not in occupied:
            return code
    return None

def free_positions(db):
    occupied = get_occupied_positions(db)
    return [code for code in SORTED_POSITIONS if code not in occupied]

# ------------------------------------------------------------
# CSRF (leichter eigener Schutz)
# ------------------------------------------------------------
def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(16)
        session["_csrf_token"] = token
    return token

def validate_csrf():
    token = session.get("_csrf_token")
    form_token = request.form.get("_csrf_token")
    if not token or not form_token or token != form_token:
        abort(400, description="Ungültiges CSRF-Token.")

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
TPL_BASE = """
<!doctype html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <title>{{ APP_NAME }} – v{{ APP_VERSION }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <!-- Bootstrap 5 & Icons -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
    <style>
      body { padding-bottom: 60px; }
      .version-badge { font-size: .85rem; opacity: .8; }
      .pos-badge { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
    </style>
</head>
<body>
<nav class="navbar navbar-expand-lg bg-dark navbar-dark">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">
      <i class="bi bi-speedometer2 me-1"></i> {{ APP_NAME }}
      <span class="badge text-bg-secondary ms-2 version-badge">v{{ APP_VERSION }}</span>
    </a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nbar">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="nbar">
      <ul class="navbar-nav me-auto mb-2 mb-lg-0">
        <li class="nav-item"><a class="nav-link {% if active=='wheelsets' %}active{% endif %}" href="{{ url_for('list_wheelsets') }}"><i class="bi bi-list-ul me-1"></i> Radsätze</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='positions' %}active{% endif %}" href="{{ url_for('positions') }}"><i class="bi bi-grid-3x3-gap me-1"></i> Positionen</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='backups' %}active{% endif %}" href="{{ url_for('backups') }}"><i class="bi bi-hdd-network me-1"></i> Backups</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='settings' %}active{% endif %}" href="{{ url_for('settings') }}"><i class="bi bi-gear me-1"></i> Einstellungen</a></li>
      </ul>
      <form class="d-flex" role="search" method="get" action="{{ url_for('list_wheelsets') }}">
        <input class="form-control me-2" type="search" placeholder="Suche (Name, Kennzeichen, Fahrzeug)" aria-label="Suche" name="q" value="{{ request.args.get('q','') }}">
        <button class="btn btn-outline-light" type="submit"><i class="bi bi-search"></i></button>
      </form>
    </div>
  </div>
</nav>

<main class="container my-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'danger' if cat=='error' else cat }} alert-dismissible fade show" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  {% block content %}{% endblock %}
</main>

<footer class="text-center text-muted">
  <small>&copy; {{ now().year }} – {{ APP_NAME }} – v{{ APP_VERSION }}</small>
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

TPL_INDEX = """
{% extends 'base.html' %}
{% block content %}
<div class="row g-3">
  <div class="col-12 col-lg-4">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title"><i class="bi bi-archive"></i> Schnellübersicht</h5>
        <ul class="list-group">
          <li class="list-group-item d-flex justify-content-between align-items-center">
            Gesamtanzahl Radsätze
            <span class="badge text-bg-primary rounded-pill">{{ total }}</span>
          </li>
          <li class="list-group-item d-flex justify-content-between align-items-center">
            Belegte Positionen
            <span class="badge text-bg-warning rounded-pill">{{ total }}</span>
          </li>
          <li class="list-group-item d-flex justify-content-between align-items-center">
            Freie Positionen
            <span class="badge text-bg-success rounded-pill">{{ free_count }}</span>
          </li>
        </ul>
        <a class="btn btn-primary mt-3" href="{{ url_for('create_wheelset') }}"><i class="bi bi-plus-circle"></i> Neuen Radsatz anlegen</a>
      </div>
    </div>
  </div>
  <div class="col-12 col-lg-8">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title"><i class="bi bi-lightbulb"></i> Nächste freie Position</h5>
        {% if next_free %}
          <p>Vorschlag: <span class="badge text-bg-success pos-badge">{{ next_free }}</span></p>
          <a class="btn btn-success" href="{{ url_for('create_wheelset', suggested=next_free) }}"><i class="bi bi-plus-lg"></i> Radsatz hier anlegen</a>
        {% else %}
          <p class="text-danger">Keine freien Positionen verfügbar.</p>
        {% endif %}
        <hr>
        <h6>Kurzübersicht freie Positionen (erste 30)</h6>
        {% if free_positions %}
          {% for p in free_positions[:30] %}
            <span class="badge text-bg-secondary pos-badge me-1 mb-1">{{ p }}</span>
          {% endfor %}
          {% if free_positions|length > 30 %}
            <div class="mt-2"><a href="{{ url_for('positions') }}">Alle anzeigen…</a></div>
          {% endif %}
        {% else %}
          <p>Keine freien Positionen.</p>
        {% endif %}
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""

TPL_WHEELSETS_LIST = """
{% extends 'base.html' %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h3><i class="bi bi-list-ul"></i> Radsätze</h3>
  <a class="btn btn-primary" href="{{ url_for('create_wheelset') }}"><i class="bi bi-plus-circle"></i> Neu</a>
</div>

<form class="row g-2 mb-3" method="get">
  <div class="col-sm-10">
    <input type="text" class="form-control" name="q" placeholder="Suche nach Name, Kennzeichen, Fahrzeug…" value="{{ request.args.get('q','') }}">
  </div>
  <div class="col-sm-2 d-grid">
    <button class="btn btn-primary"><i class="bi bi-search"></i> Suchen</button>
  </div>
</form>

<div class="table-responsive">
<table class="table table-striped table-hover align-middle">
  <thead class="table-dark">
    <tr>
      <th>#</th>
      <th>Kunde</th>
      <th>Kennzeichen</th>
      <th>Fahrzeug</th>
      <th>Position</th>
      <th>Notiz</th>
      <th>Aktionen</th>
    </tr>
  </thead>
  <tbody>
    {% for w in items %}
    <tr>
      <td>{{ w.id }}</td>
      <td>{{ w.customer_name }}</td>
      <td><span class="badge text-bg-primary">{{ w.license_plate }}</span></td>
      <td>{{ w.car_type }}</td>
      <td><code>{{ w.storage_position }}</code></td>
      <td>{{ w.note or "" }}</td>
      <td class="text-nowrap">
        <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('edit_wheelset', wid=w.id) }}"><i class="bi bi-pencil-square"></i></a>
        <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete_wheelset_confirm', wid=w.id) }}"><i class="bi bi-trash"></i></a>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>
{% if not items %}
<div class="alert alert-info">Keine Einträge gefunden.</div>
{% endif %}
{% endblock %}
"""

TPL_WHEELSET_FORM = """
{% extends 'base.html' %}
{% block content %}
<h3>{{ 'Radsatz bearbeiten' if editing else 'Neuen Radsatz anlegen' }}</h3>
<form method="post" class="row g-3">
  <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
  <div class="col-md-6">
    <label class="form-label">Kundenname *</label>
    <input type="text" class="form-control" name="customer_name" required value="{{ w.customer_name if w else '' }}">
  </div>
  <div class="col-md-6">
    <label class="form-label">Kennzeichen *</label>
    <input type="text" class="form-control" name="license_plate" required value="{{ w.license_plate if w else '' }}">
  </div>
  <div class="col-md-6">
    <label class="form-label">Fahrzeugtyp *</label>
    <input type="text" class="form-control" name="car_type" required value="{{ w.car_type if w else '' }}">
  </div>
  <div class="col-md-6">
    <label class="form-label">Position *</label>
    <select class="form-select" name="storage_position" required>
      {% if suggested and not editing %}
        <option value="{{ suggested }}">{{ suggested }} (Vorschlag)</option>
      {% endif %}
      <optgroup label="Container">
        {% for p in positions if p.startswith('C') %}
          <option value="{{ p }}" {% if w and w.storage_position==p %}selected{% endif %}>{{ p }}</option>
        {% endfor %}
      </optgroup>
      <optgroup label="Garage">
        {% for p in positions if p.startswith('GR') %}
          <option value="{{ p }}" {% if w and w.storage_position==p %}selected{% endif %}>{{ p }}</option>
        {% endfor %}
      </optgroup>
    </select>
    <div class="form-text">Nur gültige, freie Positionen auswählen.</div>
  </div>
  <div class="col-12">
    <label class="form-label">Notiz (optional)</label>
    <textarea class="form-control" name="note" rows="3">{{ w.note if w else '' }}</textarea>
  </div>
  <div class="col-12 d-flex gap-2">
    <button class="btn btn-primary" type="submit"><i class="bi bi-check2-circle"></i> Speichern</button>
    <a class="btn btn-outline-secondary" href="{{ url_for('list_wheelsets') }}">Abbrechen</a>
  </div>
</form>
{% endblock %}
"""

TPL_DELETE_CONFIRM = """
{% extends 'base.html' %}
{% block content %}
<h3 class="text-danger"><i class="bi bi-exclamation-triangle-fill"></i> Radsatz sicher löschen</h3>
<div class="card border-danger">
  <div class="card-body">
    <p>Bitte bestätigen Sie die Löschung des folgenden Radsatzes. Dieser Vorgang kann nicht rückgängig gemacht werden.</p>
    <ul>
      <li><strong>Kunde:</strong> {{ w.customer_name }}</li>
      <li><strong>Kennzeichen:</strong> <span class="badge text-bg-primary">{{ w.license_plate }}</span></li>
      <li><strong>Fahrzeug:</strong> {{ w.car_type }}</li>
      <li><strong>Position:</strong> <code>{{ w.storage_position }}</code></li>
    </ul>
    <form method="post" class="mt-3">
      <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
      <div class="mb-3">
        <label class="form-label">Zur Bestätigung geben Sie das Kennzeichen ein:</label>
        <input type="text" class="form-control" name="confirm_plate" required placeholder="Kennzeichen eingeben">
      </div>
      <button class="btn btn-danger"><i class="bi bi-trash"></i> Endgültig löschen</button>
      <a class="btn btn-outline-secondary" href="{{ url_for('list_wheelsets') }}">Abbrechen</a>
      <div class="form-text mt-2">
        Sichere Löschung ist aktiviert (<code>PRAGMA secure_delete=ON</code>), und es wird ein Audit-Eintrag erzeugt.
      </div>
    </form>
  </div>
</div>
{% endblock %}
"""

TPL_POSITIONS = """
{% extends 'base.html' %}
{% block content %}
<h3><i class="bi bi-grid-3x3-gap"></i> Positionen</h3>

<div class="card mb-3">
  <div class="card-body">
    <h5 class="card-title">Freie Position finden</h5>
    {% if next_free %}
      <p>Nächste freie Position: <span class="badge text-bg-success pos-badge">{{ next_free }}</span></p>
      <a class="btn btn-success" href="{{ url_for('create_wheelset', suggested=next_free) }}"><i class="bi bi-plus-lg"></i> Radsatz hier anlegen</a>
    {% else %}
      <p class="text-danger">Keine freien Positionen vorhanden.</p>
    {% endif %}
  </div>
</div>

<div class="card">
  <div class="card-body">
    <h5 class="card-title">Alle freien Positionen ({{ free_positions|length }})</h5>
    {% if free_positions %}
      {% for p in free_positions %}
        <span class="badge text-bg-secondary pos-badge me-1 mb-1">{{ p }}</span>
      {% endfor %}
    {% else %}
      <p>Keine freien Positionen.</p>
    {% endif %}
  </div>
</div>
{% endblock %}
"""

TPL_SETTINGS = """
{% extends 'base.html' %}
{% block content %}
<h3><i class="bi bi-gear"></i> Einstellungen</h3>
<form method="post" class="row g-3">
  <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
  <div class="col-md-4">
    <label class="form-label">Backup-Intervall (Minuten)</label>
    <input type="number" min="1" class="form-control" name="backup_interval_minutes" value="{{ s.backup_interval_minutes }}">
  </div>
  <div class="col-md-4">
    <label class="form-label">Anzahl Sicherungskopien</label>
    <input type="number" min="1" class="form-control" name="backup_copies" value="{{ s.backup_copies }}">
  </div>
  <div class="col-12 d-flex gap-2">
    <button class="btn btn-primary"><i class="bi bi-save2"></i> Speichern</button>
    <a class="btn btn-outline-secondary" href="{{ url_for('run_backup') }}"><i class="bi bi-hdd-stack"></i> Backup jetzt erstellen</a>
  </div>
</form>
{% endblock %}
"""

TPL_BACKUPS = """
{% extends 'base.html' %}
{% block content %}
<h3><i class="bi bi-hdd-network"></i> Backups</h3>
<div class="mb-3 d-flex gap-2">
  <a class="btn btn-outline-primary" href="{{ url_for('run_backup') }}">
    <i class="bi bi-cloud-arrow-up"></i> Backup jetzt erstellen
  </a>
  <!-- NEW -->
  <a class="btn btn-outline-success" href="{{ url_for('export_csv_now') }}">
    <i class="bi bi-filetype-csv"></i> CSV jetzt exportieren
  </a>
</div>
<div class="table-responsive">
<table class="table table-striped">
  <thead class="table-dark">
    <tr>
      <th>Datei</th>
      <th>Typ</th>
      <th>Größe</th>
      <th>Erstellt</th>
      <th>Aktion</th>
    </tr>
  </thead>
  <tbody>
    {% for b in backups %}
    <tr>
      <td><code>{{ b.name }}</code></td>
      <td class="text-nowrap">
        {% if b.type == 'csv' %}
          <span class="badge text-bg-success"><i class="bi bi-filetype-csv"></i> CSV</span>
        {% else %}
          <span class="badge text-bg-secondary"><i class="bi bi-hdd"></i> DB</span>
        {% endif %}
      </td>
      <td>{{ b.size_kb }} KB</td>
      <td>{{ b.mtime }}</td>
      <td><a class="btn btn-sm btn-outline-primary" href="{{ url_for('download_backup', filename=b.name) }}"><i class="bi bi-download"></i> Herunterladen</a></td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>
{% if not backups %}
<div class="alert alert-info">Noch keine Backups vorhanden.</div>
{% endif %}
{% endblock %}
"""

# Jinja Loader registrieren
app.jinja_loader = DictLoader({
    "base.html": TPL_BASE,
    "index.html": TPL_INDEX,
    "wheelsets_list.html": TPL_WHEELSETS_LIST,
    "wheelset_form.html": TPL_WHEELSET_FORM,
    "delete_confirm.html": TPL_DELETE_CONFIRM,
    "positions.html": TPL_POSITIONS,
    "settings.html": TPL_SETTINGS,
    "backups.html": TPL_BACKUPS,
})

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
