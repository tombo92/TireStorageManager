
# 🚗 TireStorage Manager

**Keep your customers’ tires organized — hassle-free.**

TireStorage Manager is a Python-based desktop application for small car shops to manage tire storage. It supports  **winter, summer, and all-season tires** , allows multiple PCs to access a shared SQLite database safely, and offers Excel import/export and automatic backups.

---

## 📝 Features

* **Customer & storage tracking**

  Track customer names, storage locations (shelf/position), and tire seasons.
* **Search & manage records**

  Quickly find, add, edit, or delete tire records via a user-friendly GUI.
* **Excel integration**

  * Import customer tire lists from Excel (.xlsx/.xls)
  * Export current records to Excel for reporting or printing
* **Centralized SQLite database**

  * Multi-PC access via network share
  * WAL mode + file locking ensures safe concurrent writes
* **Automatic and manual backups**

  * Regular backup interval (default: every 6 hours)
  * One-click manual backup for extra security
* **Self-update mechanism**

  * Checks GitHub for newer versions on startup
  * Prompts user to download and install updates safely
* **Cross-platform GUI**

  * Built with Tkinter for lightweight, native-feeling windows

---

## 🛠 Technology Stack

* **Python 3** (tested with 3.11+)
* **SQLite** (WAL mode for multi-user access)
* **Tkinter** GUI
* **Pandas + openpyxl** for Excel import/export
* **FileLock** for cross-process write safety
* Packaged as **Windows `.exe`** using PyInstaller

---

## ⚡ Getting Started

### 1. Download

Download the latest release `.exe` from the [Releases](https://chatgpt.com/c/releases) page.

### 2. Place Database

* Place `tire_storage.db` in a shared folder accessible to all shop PCs.
* By default, the app will create it if it doesn’t exist.

### 3. Run Application

* Simply run `TireStorage.exe` — no Python installation required.
* Multiple PCs can run the app concurrently and safely.

### 4. First Use

* Optionally import an Excel file with customer records.
* Use the GUI to add new tire sets manually.

---

## 💻 Excel Format

* Required columns: `customer_name`, `location`, `season`
* Season values (case-insensitive):
  * `winter`, `summer`, `allseason`
  * Short forms like `w`, `s`, `as` are also accepted

---

## 🔄 Updates

* On startup, the app checks the `latest.json` hosted on GitHub.
* If a newer version is available, a prompt appears.
* If the user agrees:
  1. Download the new `.exe` to a temporary location
  2. Close the current app
  3. Replace the old `.exe` with the new one
  4. Restart automatically

> **Important:** Updates always require user confirmation for safety.

---

## 💾 Backups

* Backups are stored in a folder alongside the database:
  ```
  tire_storage_backups/
  ```
* Each backup is timestamped, e.g., `tire_storage_backup_20250915_143200.db`.
* Manual backup: click “Backup Now” in the GUI.
* Automatic backup interval can be adjusted in `app/config.py`.

---

## 🔧 Building from Source

1. **Install dependencies** :

```bash
pip install -r requirements.txt
```

2. **Build `.exe` with PyInstaller** :

```bash
pyinstaller --onefile --noconsole --name TireStorage app/main.py
```

3. `.exe` will be in the `dist/` folder. Copy to PCs as needed.

---

## 🧩 Project Structure

```
tire_storage_app/
│   README.md
│   requirements.txt
│   setup.spec              # for PyInstaller build
│
└───app/
    │   main.py
    │   config.py
    │
    ├───model/
    │     entities.py
    │     db.py
    │     repository.py
    │
    ├───controller/
    │     app_controller.py
    │
    ├───view/
    │     gui.py
    │
    └───utils/
          locking.py
          excel_io.py
          scheduler.py
          auto_update.py
```

---

## ✅ License

MIT License — free to use and modify for personal or commercial use.
