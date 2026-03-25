# TireStorageManager

> **Hinweis:** Die Benutzeroberfläche dieser Anwendung ist ausschließlich auf Deutsch verfügbar.

A lightweight web application for managing tire and wheel storage in workshops.
Customers' wheel sets are tracked by storage position, vehicle, and season.
The application runs as a **Windows Service** and is accessible from any device in the local network via a browser — no installation required on client machines.

---

## Features

- 📦 Manage wheel sets with customer name, vehicle, position, and notes
- 🗺️ Visual storage position overview with free/occupied status
- 🔍 Full-text search and filter by season / customer
- 🌙 **Dark mode** — toggled from Settings, shared across all clients
- � **Customizable storage positions** — define your own positions from scratch via the Settings UI
- 🀽� Automatic daily database backups with configurable retention
- 🔄 Self-update mechanism via GitHub Releases
- 🖥️ Runs as a Windows Service (via [NSSM](https://nssm.cc/))
- 🖱️ Graphical installer/uninstaller — no Python required on the target machine
- 🔗 Optional desktop shortcut created during installation
- 📜 Impressum page with developer info and project links
- 🔏 Optional EXE code signing (self-signed or CA certificate)

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
pyinstaller TSM-Installer.spec --noconfirm
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

## CI/CD

GitHub Actions pipeline (`.github/workflows/ci.yml`) — single workflow, 4 jobs:

| Job         | Runner             | Trigger                  | What it does                                                        |
| ----------- | ------------------ | ------------------------ | ------------------------------------------------------------------- |
| `bump`    | `ubuntu-latest`  | push to master/develop   | Bumps VERSION (minor on master, patch on develop)                   |
| `test`    | `ubuntu-latest`  | every push / PR          | Runs the full pytest suite                                          |
| `build`   | `windows-latest` | after `test` passes    | Builds both EXEs, smoke test, optional code signing                 |
| `release` | `ubuntu-latest`  | after `build` succeeds | Creates GitHub Release (official on master, pre-release on develop) |

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
├── config.py               # Central configuration (reads env vars)
├── run.py                  # Application entry point (dev + prod)
├── installer_logic.py      # Pure-logic install/uninstall steps (no Tkinter)
├── TSMInstaller.py         # Tkinter installer/uninstaller GUI
├── TireStorageManager.spec # PyInstaller spec for the app EXE
└── TSM-Installer.spec      # PyInstaller spec for the installer EXE
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

<!-- ↑↑↓↓←→←→BA -->
