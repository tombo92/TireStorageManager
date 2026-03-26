# TireStorageManager

> **Sprache / Language:** The UI supports **German** and **English**. The language can be changed in the Settings page.

A lightweight web application for managing tire and wheel storage in workshops.
Customers' wheel sets are tracked by storage position, vehicle, and season.
The application runs as a **Windows Service** and is accessible from any device in the local network via a browser — no installation required on client machines.

---

## Features

- 📦 Manage wheel sets with customer name, vehicle, position, and notes
- 🔢 **German licence-plate validation** — enforces the standard format (`ORT KK 1234`) in the browser and on the server; auto-formats on blur, rejects invalid entries before saving
- � **Extended tire details** _(optional)_ — store tyre manufacturer, size, age/DOT, season (Sommer/Winter/Allwetter), rim type (Stahl/Alu), and exchange note per wheel set; enabled via a toggle in Settings
- ⚠️ **Seasonal overdue detection** _(optional)_ — wheel sets past their seasonal exchange window are highlighted with a pulsing row and warning icon (Sommer tyres: Jan–Apr; Winter tyres: Jul–Sep; swap windows are not flagged)
- 🏷️ Season badges with icons (☀ Sommer, ❄ Winter, 🌦 Allwetter) on the wheel set list; exchange note shown as tooltip
- �🗺️ Visual storage position overview with free/occupied status
- 🔍 Full-text search and filter by customer / vehicle
- 🌙 **Dark mode** — toggled from Settings, shared across all clients
- 🗂️ **Customizable storage positions** — define your own positions from scratch via the Settings UI
- 🔄 Automatic daily database backups with configurable retention
- ♻️ Self-update mechanism via GitHub Releases
- 🖥️ Runs as a Windows Service (via [NSSM](https://nssm.cc/))
- 🖱️ Graphical installer/uninstaller — no Python required on the target machine
- 🔗 Optional desktop shortcut created during installation
- 📜 Impressum page with developer info and project links
- 🔏 Optional EXE code signing (self-signed or CA certificate)

---

## Licence Plate Format

All licence plates must follow the **German standard format**:

```text
B-TB 3005          → standard plate
LOS-ZE 123         → standard plate
M-AB 1234 H        → Oldtimer (Historisch)
MIL-XY 99 E        → Electric vehicle
```

| Part | Length | Examples |
|---|---|---|
| Unterscheidungszeichen | 1–3 letters | `B`, `LOS`, `MIL` |
| Erkennungsbuchstaben | 1–2 letters | `A`, `TB`, `ZE` |
| Erkennungsziffern | 1–4 digits | `1`, `99`, `3005` |
| Suffix (optional) | `E` or `H` | Electric / Oldtimer |

**Canonical storage format:** `ORT-KK 1234` — hyphen between the two letter groups, space before the digits.

The input field auto-uppercases while typing, auto-formats on blur (inserts canonical hyphen and space), and shows a live ✓/✗ indicator.
Invalid plates are also rejected on the server before they can be saved.

---

## Quick Start (Developer)

### Prerequisites

- Python 3.10+
- Windows (or Linux/macOS for development; service features are Windows-only)

### Setup

```bash
git clone https://github.com/tombo92/TireStorageManager.git
cd TireStorageManager
python -m venv .venv
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-test.txt
```

### Run in development mode

```bash
python run.py --dev
```

The app will be available at `http://localhost:5000`.

### Run in production mode (Waitress)

```bash
python run.py
```

---

## Environment Variables

| Variable           | Default              | Description                                                 |
| ------------------ | -------------------- | ----------------------------------------------------------- |
| `TSM_APP_NAME`   | `Reifenmanager`    | Application title shown in the UI                           |
| `TSM_SECRET_KEY` | `change-me-please` | Flask session secret key —**change in production**   |
| `TSM_DATA_DIR`   | _(repo root)_      | Base directory for `db/`, `backups/`, `logs/`         |
| `TSM_PORT`       | `5000`             | HTTP port the server listens on                             |
| `TSM_LOG_LEVEL`  | `INFO`             | Python logging level (`DEBUG`, `INFO`, `WARNING`, …) |
| `TSM_PRERELEASE` | `0`                | Set to `1` on develop CI builds to mark as test version   |

---

## Windows Installer

The project ships a standalone **`TSM-Installer.exe`** built with PyInstaller.
It requires no Python installation on the target machine.

### Installer fields

| Field                          | Description                                                              |
| ------------------------------ | ------------------------------------------------------------------------ |
| Installationsverzeichnis       | Directory for `TireStorageManager.exe` and `nssm.exe`                |
| Datenverzeichnis               | Directory for the database, backups, and log files                       |
| HTTP Port                      | Port the web server listens on (default:`5000`)                        |
| Programmtitel                  | Custom application title shown in the UI                                 |
| Geheimer Schlüssel            | Flask session secret key for session security                            |
| Desktop-Verknüpfung erstellen | Creates a `.url` shortcut on the desktop pointing to the web interface |

The installer:

1. Creates all required directories
2. Deploys `nssm.exe` and `TireStorageManager.exe`
3. Seeds the database (if not present)
4. Adds a Windows Firewall inbound rule
5. Registers and starts a Windows Service (auto-start)
6. Creates a scheduled daily service restart at 03:00
7. Optionally creates a desktop shortcut (All Users Desktop)

The uninstaller reverses all steps and optionally keeps the data directory.
Settings (directories, port, display name) are persisted in the Windows Registry between sessions.

---

## Building the EXE

```bash
# Install build dependencies
pip install pyinstaller

# Build the main application EXE
pyinstaller TireStorageManager.spec --noconfirm

# Copy into payload so the installer can bundle it
copy dist\TireStorageManager.exe payload\TireStorageManager.exe

# Build the installer EXE
pyinstaller installer/TSM-Installer.spec --noconfirm
# → dist\TSM-Installer.exe
```

### Code Signing (optional)

```powershell
# Create a self-signed certificate (once, as Administrator)
powershell -ExecutionPolicy Bypass -File tools\create_codesign_cert.ps1

# Install on target machines to trust the certificate
powershell -ExecutionPolicy Bypass -File tools\install_codesign_cert.ps1
```

CI signing is automatic when the `CODE_SIGN_PFX_BASE64` and `CODE_SIGN_PASSWORD` secrets are set in the GitHub repository.

---

## Running Tests

```bash
pytest tests/ -v --tb=short
```

---

## Manual Testing (Smoke Test)

`tools/smoke_test.py` is a self-contained integration test script that runs against a **live application instance** (dev server or built EXE). It covers 10 suites and 39+ checks without needing pytest.

### Quickstart — against the dev server

```bash
# 1. Start the app in one terminal
python run.py --dev

# 2. Run the smoke test in another terminal
python tools/smoke_test.py --base-url http://127.0.0.1:5000
```

### Against the built EXE

```bash
python tools/smoke_test.py \
    --base-url   http://127.0.0.1:59123 \
    --exe-path   dist\TireStorageManager.exe \
    --data-dir   C:\Temp\tsm_smoke
```

The `--exe-path` argument enables two additional suites:

| Suite | What it tests |
|---|---|
| **9 – Update + restart** | Triggers `POST /settings/update-now`, waits for the process to respawn, verifies liveness |
| **10 – Concurrency** | 20 parallel readers, 10 concurrent writers to the same position, 100-user load with latency metrics |

### Test suites

| # | Suite | Key checks |
|---|---|---|
| 1 | Core pages | HTTP 200 for every navigable page |
| 2 | Wheelset CRUD | Create / edit / delete via web UI |
| 3 | Settings | Read/write, dark-mode toggle, auto-update toggle |
| 4 | Update check API | `/api/update-check` returns valid JSON |
| 5 | Positions | Page loads, grid content present |
| 6 | Backups | Page loads, run backup, export CSV |
| 7 | Impressum | Page loads, easter-egg element present |
| 8 | Error handling | 404 on unknown ID, path traversal blocked |
| 9 | Update + restart | _(EXE mode only)_ |
| 10 | Concurrency | _(EXE mode only or `--concurrency` flag)_ |

Exit code `0` = all checks passed. Exit code `1` = one or more failures (details printed to stdout).

---

## CI/CD

GitHub Actions pipeline (`.github/workflows/ci.yml`) — single workflow, 4 jobs:

| Job | Runner | Trigger | What it does |
| --- | --- | --- | --- |
| `bump` | `ubuntu-latest` | push to **master/develop** only | Bumps VERSION (patch on develop, minor on master) |
| `test` | `ubuntu-latest` | **every push & PR** (all branches) | Runs the full pytest suite |
| `build` | `windows-latest` | **every push** (all branches) after `test` passes | Builds both EXEs, smoke test, optional code signing |
| `release` | `ubuntu-latest` | after `build` succeeds on **master/develop** only | Creates GitHub Release (official on master, pre-release on develop) |

---

## Project Structure

```
TireStorageManager/
├── tsm/                    # Application package
│   ├── app.py              # Flask app factory
│   ├── models.py           # SQLAlchemy models (WheelSet, Settings, AuditLog, …)
│   ├── routes.py           # URL routes
│   ├── db.py               # Database engine, session & auto-migration
│   ├── backup_manager.py   # Automatic backup logic
│   ├── positions.py        # Storage position helpers & custom position support
│   ├── utils.py            # CSRF, resource path helpers
│   └── self_update.py      # Self-update via GitHub Releases
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS and JavaScript
├── tests/                  # pytest test suite
├── tools/                  # Developer utilities (version bump, code signing, …)
├── payload/                # Bundled assets for the installer (nssm.exe, seed DB)
├── installer/              # Installer package
│   ├── installer_logic.py  # Pure-logic install/uninstall steps (no Tkinter)
│   ├── TSMInstaller.py     # Tkinter installer/uninstaller GUI
│   └── TSM-Installer.spec  # PyInstaller spec for the installer EXE
├── config.py               # Central configuration (reads env vars)
├── run.py                  # Application entry point (dev + prod)
└── TireStorageManager.spec # PyInstaller spec for the app EXE
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

<!-- ↑↑↓↓←→←→BA -->
