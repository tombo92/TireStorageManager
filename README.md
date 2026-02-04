# Tire Storage Manager (Brandherm – Reifenmanager)

A lightweight, single-node **Flask + SQLAlchemy** web app to manage tire sets (Sommer/Winter) with a modern Bootstrap UI, secure SQLite storage, automatic backups, and CSV exports. Designed for small workshops or private use—simple to run on Windows, Linux, or Raspberry Pi.

- **UI**: Bootstrap 5, clean German interface
- **Data**: SQLite (WAL + secure_delete)
- **Features**: add/edit/search tire sets, **position scheme** (container/garage), **disabled positions**, CSV snapshots, **automatic scheduled backups**, **audit log**
- **Security**: simple CSRF protection; secret key via env var
- **Maintenance**: **auto-version bump** on `develop` via GitHub Actions; optional **updater** script

---

## 📦 Repository Layout

```
.
├─ db/                  # (optional) db utilities if you keep them here
├─ static/              # CSS, JS and assets served at /static
│  ├─ css/
│  │  └─ style.css
│  └─ js/
│     └─ script.js
├─ templates/           # Jinja2 templates
│  ├─ base.html
│  ├─ index.html
│  ├─ positions.html
│  ├─ wheelsets_list.html
│  ├─ wheelset_form.html
│  ├─ delete_confirm.html
│  ├─ backups.html
│  └─ settings.html
├─ tools/               # developer/admin tools
│  ├─ bump_version.py   # bumps VERSION in config.py (used by CI)
│  └─ quick_disable.py  # CLI to disable/enable/list positions
├─ tsm/                 # application package
│  ├─ __init__.py
│  ├─ app.py            # create_app()
│  ├─ routes.py         # all Flask routes
│  ├─ db.py             # SQLAlchemy engine + SessionLocal
│  ├─ models.py         # ORM models (WheelSet/Settings/AuditLog/DisabledPosition)
│  ├─ positions.py      # position scheme, validation, free/disabled logic
│  ├─ utils.py          # CSRF helpers
│  └─ backup_manager.py # background backup + CSV snapshot
├─ config.py            # app config (VERSION, HOST/PORT, paths, etc.)
├─ run.py               # entry point (`python run.py`)
├─ requirements.txt
├─ pyproject.toml       # package metadata (optional dev)
└─ .github/
   └─ workflows/
      └─ bump-version.yml
```

> **Note:** You can keep `templates/` and `static/` at repo root or under `tsm/`; just ensure `Flask(__name__, template_folder=..., static_folder=...)` points to them in `tsm/app.py`.

---

## ✅ Features

- Add / edit / delete tire sets (**Kunde**, **Kennzeichen**, **Fahrzeug**, **Position**, **Notiz**)
- Powerful **positioning scheme**:
  - Containers: `C[1-4][R|L][O|M|U][LL|L|MM|M|RR|R]`
  - Garage: `GR[1-8][O|M|U][L|M|R]`
  - **Disabled positions**: mark unusable spots; excluded from suggestions and dropdowns
- **Search** by name, plate, vehicle
- **Backups**: automatic SQLite backups + **CSV snapshots** with retention
- **Audit log** for create/update/delete/backup events
- **CSRF** protection for forms
- **Nice UI controls**:
  - Click **free position buttons** to preselect a new wheel set
  - **A− / A+** in navbar to adjust position size persistently (localStorage)

---

## 🧩 Requirements

- **Python** ≥ 3.10
- Pip / venv
- Windows 10/11, Linux (Ubuntu/Debian), or Raspberry Pi OS
- (Optional) GitHub account if you use the CI bump workflow

---

## 🚀 Installation & First Run

### 1) Clone & create a virtual environment

```bash
git clone https://github.com/<YOUR-ORG-OR-USER>/TireStorageManager.git
cd TireStorageManager

# Create and activate venv
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2) Configure secrets (recommended)

Set the Flask secret key via environment variable:

- **Windows PowerShell**

  ```powershell
  $env:WHEELS_SECRET_KEY = "<a-long-random-secret>"
  ```
- **Linux**

  ```bash
  export WHEELS_SECRET_KEY="<a-long-random-secret>"
  ```

> You can also edit `config.py` for `HOST`, `PORT`, `BACKUP_DIR`, etc.

### 3) Run the app

```bash
python run.py
```

Open: `http://<SERVER-IP>:5000`

> DB tables are created automatically on first run.

---

## 🔧 Configuration

`config.py` is the canonical place for:

- `VERSION` — app version (auto-bumped by CI on `develop`)
- `APP_NAME`
- `DB_PATH` — SQLite file path
- `BACKUP_DIR` — where `.db` and `.csv` backups land
- `SECRET_KEY` — taken from `WHEELS_SECRET_KEY` env if set
- `HOST` / `PORT` — default `0.0.0.0:5000`

**Environment variables**

- `WHEELS_SECRET_KEY` — (recommended) secret key for session/CSRF
- Updater (optional):
  - `TSM_GH_OWNER`, `TSM_GH_REPO`, `TSM_GH_BRANCH`
  - `GITHUB_TOKEN` (to avoid API rate limits)

---

## 🧭 Using the Tools

### Disable / enable unusable positions

```bash
# List disabled positions
python tools/quick_disable.py --list

# Disable a position with a reason
python tools/quick_disable.py --disable C1ROLR --reason "Shelf damaged"

# Enable again
python tools/quick_disable.py --enable C1ROLR
```

> If you see `ModuleNotFoundError: No module named 'tsm'`, run from the repo root **or** add:
>
> ```python
> # inside tools/quick_disable.py, before imports
> import sys
> from pathlib import Path
> ROOT = Path(__file__).resolve().parents[1]
> sys.path.insert(0, str(ROOT))
> ```

---

## 🔁 Automatic Version Bump on `develop`

This repo includes a GitHub Actions workflow that **increments the PATCH** version on every push to `develop`.

- Script: `tools/bump_version.py` — bumps `VERSION="x.y.z"` in `config.py` and prints it
- Workflow: `.github/workflows/bump-version.yml` — commits the change and tags `vX.Y.Z`

> The job is skipped for the bot’s own commit to avoid loops and uses concurrency to avoid racing bumps.

---

## 💾 Backups & CSV Exports

- The **Backup Manager** runs in the background and:
  - Creates a timestamped **`.db` backup** via SQLite online backup API
  - Creates a matching **CSV snapshot**
  - Enforces retention (`Settings` → **Backup copies**)
- You can also trigger:
  - **Backup now**: _Backups_ → **Backup jetzt erstellen**
  - **CSV now**: _Backups_ → **CSV jetzt exportieren**

---

## 🌐 Static IP (so others in your LAN can reach it)

To ensure the server is reachable at a fixed address like `http://192.168.1.50:5000`, set a **static IP** or a **DHCP reservation**.
Do **one** of the following:

### Option A — DHCP Reservation (recommended)

- Go to your router/admin UI
- Find your server’s MAC address (in OS network settings)
- Create a **DHCP reservation** → always assign the same IP to this MAC

> This keeps central control and avoids conflicts. Each router UI differs (search your router model for exact steps).

### Option B — Static IP on Windows 10/11

**GUI**

1. _Settings_ → **Network & Internet** → **Change adapter options**
2. Right-click your Ethernet/Wi‑Fi → **Properties**
3. Select **Internet Protocol Version 4 (TCP/IPv4)** → **Properties**
4. Choose **Use the following IP address**
   - IP address: e.g. `192.168.1.50`
   - Subnet mask: `255.255.255.0` (typical)
   - Default gateway: your router, e.g. `192.168.1.1`
   - DNS: use router (`192.168.1.1`) or public (`1.1.1.1`, `8.8.8.8`)
5. Save and reconnect.

**PowerShell**

```powershell
# Replace with your interface alias and desired config
$if = "Ethernet"                   # use Get-NetAdapter to list
$ip = "192.168.1.50"
$prefix = 24                       # 255.255.255.0
$gw = "192.168.1.1"
$dns = @("1.1.1.1","8.8.8.8")

# Remove DHCP IPv4 if present
Set-NetIPInterface -InterfaceAlias $if -Dhcp Disabled -AddressFamily IPv4
Remove-NetIPAddress -InterfaceAlias $if -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue

# Set static
New-NetIPAddress -InterfaceAlias $if -IPAddress $ip -PrefixLength $prefix -DefaultGateway $gw
Set-DnsClientServerAddress -InterfaceAlias $if -ServerAddresses $dns
```

### Option C — Static IP on Ubuntu/Debian (netplan)

Edit `/etc/netplan/*.yaml` (create one if empty):

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      dhcp4: no
      addresses: [192.168.1.50/24]
      gateway4: 192.168.1.1
      nameservers:
        addresses: [1.1.1.1,8.8.8.8]
```

Apply:

```bash
sudo netplan apply
```

> Replace `enp3s0` with your NIC (`ip link`), and the IP/gateway/DNS to your network.

### Open Firewall

- **Windows**: allow inbound TCP **5000** (or your configured port)
- **Linux** (ufw):
  ```bash
  sudo ufw allow 5000/tcp
  ```

Now others on the LAN can use: `http://<static-ip>:5000`

---

## 🛠️ Production (optional)

For a more resilient setup:

- **systemd** service (Linux):

  `/etc/systemd/system/tsm.service`

  ```ini
  [Unit]
  Description=Tire Storage Manager
  After=network.target

  [Service]
  WorkingDirectory=/opt/TireStorageManager
  Environment=WHEELS_SECRET_KEY=<your-secret>
  ExecStart=/opt/TireStorageManager/.venv/bin/python run.py
  Restart=on-failure
  User=tsm
  Group=tsm

  [Install]
  WantedBy=multi-user.target
  ```

  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable --now tsm.service
  ```
- **Windows**: run via **Task Scheduler** at logon or use **NSSM** to create a service that starts `python run.py` in your repo directory with the venv.

---

## 🧪 Troubleshooting

- **`TemplateNotFound: wheelsets_list.html`**Your `templates` folder is not where Flask expects it.Fix by either:

  - Move `templates/` under `tsm/` and use `app = Flask(__name__)`, **or**
  - Point Flask explicitly:
    ```python
    # tsm/app.py
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(ROOT/"templates"), static_folder=str(ROOT/"static"))
    ```

  Restart after changes.
- **Static 404 (`/static/css/style.css`)**Ensure `static/css/style.css` exists and your `base.html` uses:

  ```jinja2
  <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}?v={{ APP_VERSION }}">
  <script src="{{ url_for('static', filename='js/script.js') }}?v={{ APP_VERSION }}"></script>
  ```
- **`ModuleNotFoundError: No module named 'tsm'` (tools)**Run from repo root or add:

  ```python
  import sys, pathlib
  ROOT = pathlib.Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(ROOT))
  ```
- **Note field shows “None” on edit**
  Use Jinja `{{ w.note|default('', true) }}` and normalize on POST:

  ```python
  note_input = (request.form.get("note") or "").strip()
  note = None if (not note_input or note_input.lower() == "none") else note_input
  ```

---

## 📄 License

Add your license here (e.g., MIT).

---

## 🙌 Acknowledgements

- Flask, SQLAlchemy, Bootstrap
