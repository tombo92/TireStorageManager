# TireStorage Manager (Reifenmanager)

A lightweight, single‑file Flask web app to manage customer tire sets (Sommer/Winter) with a modern German UI, safe SQLite database, automatic backups, and CSV export.

> App name: **Brandherm – Reifenmanager**, default host/port: **0.0.0.0:5000**, DB file: **`wheel_storage.db`**, backups in **`backups/`**. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)

---

## Features

- **Simple single‑file app** (Flask + SQLAlchemy + Jinja2) with Bootstrap 5 UI (navbar shows version). [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)
- **Manage wheel sets**: add, edit, safe delete (with confirmation), search by customer/plate/car, and audit logs. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)
- **Positions logic** with validation & sorting (containers + shelves) and “next free position” suggestion. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)
- **Automated backups** (configurable interval & retention) + **on‑demand backups** from the UI. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)
- **CSV snapshots** (UTF‑8 with BOM; Excel‑friendly) and download view for DB/CSV backups. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)
- **SQLite safety**: WAL mode, foreign keys, secure_delete. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)

### Project Structure

```plaintext
├─ app.py               (app factory)
├─ routes.py            (all Flask routes)
├─ quick_disable.py     (small tool to enable/disable positions)
├─ backup_manager.py    (background thread)
├─ config.py
├─ db.py
├─ models.py
├─ positions.py
├─ utils.py
├─ run.py               (entry point)
├─ templates/
│  ├─ base.html
│  ├─ index.html
│  ├─ wheelsets_list.html
│  ├─ wheelset_form.html
│  ├─ delete_confirm.html
│  ├─ positions.html
│  ├─ settings.html
│  └─ backups.html
└─ backups/             (auto-created)
```

---

## Quick Start (Windows)

1. **Clone or unzip** the repository (see GitHub repo). [2](https://github.com/tombo92/TireStorageManager)
2. **Double‑click `wheels_app.bat`** (safe start):

   - Creates `.venv`, upgrades `pip`, installs `requirements.txt`, then starts `wheels_manager.py`.
3. Open the app in a browser: `http://<SERVER-IP>:5000`. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)

> **Tip (secret key):** For production, set a strong environment variable before starting:

> `set WHEELS_SECRET_KEY=SuperStrongRandomValue`

> The app reads `WHEELS_SECRET_KEY` or falls back to a dev default. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)

---

## Configuration

- **Database**: `wheel_storage.db` in the app directory. Backups live in `backups/`. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)
- **Host/Port**: Defaults to `0.0.0.0:5000`. Change in `wheels_manager.py` if needed. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)
- **Backups**: Configure interval (minutes) and how many copies to keep in **Einstellungen**. [1](https://msasafety-my.sharepoint.com/personal/03brandhet37_msasafety_com/Documents/Microsoft%20Copilot-Chatdateien/wheels_manager.py)

---

## Update

- **Manual**: Pull/replace the latest files from the repo and restart. Repo: [https://github.com/tombo92/TireStorageManager](https://github.com/tombo92/TireStorageManager) (no releases yet).
- **Automated**: See **Daily Auto‑Update** section below for a Windows Task that checks daily, updates if a new version exists, and restarts the app.

---

## Development

- Stack: Python, Flask 2.x, SQLAlchemy 2.x, Jinja2, Bootstrap 5.
- Run locally:

  ```bash

  # Windows (PowerShell or cmd)

  .\.venv\Scripts\python.exe wheels_manager.py
  ```
