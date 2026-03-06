# TSMInstallerGUI.py
# GUI installer for TireStorageManager (Windows).
# - Choose install dir, data dir, port
# - Creates DB/backups/logs (seeds DB if payload contains tires_seed.db)
# - Uses NSSM (bundled or from PATH) to install/start a Windows Service (auto-start on boot)
# - Opens Windows Firewall inbound rule for the chosen port
#
# Build the installer as a single EXE via PyInstaller (see instructions below).

from __future__ import annotations
import os
import sys
import shutil
import socket
import ctypes
import subprocess
import threading
from pathlib import Path
from typing import Optional, Callable

# --- UI (Tkinter) ---
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "TireStorageManager"
SERVICE_NAME = "TireStorageManager"
DEFAULT_PORT = 5000

# Payloads to bundle with PyInstaller
PAYLOAD_APP        = Path("payload") / f"{APP_NAME}.exe"
PAYLOAD_NSSM       = Path("payload") / "nssm.exe"
PAYLOAD_SEED_DB    = Path("payload") / "db" / "wheel_storage.db"

# -------------------- Utility helpers --------------------
def is_admin() -> bool:
    return True
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def relaunch_as_admin():
    params = " ".join([f'"{arg}"' for arg in sys.argv])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)

def resource_path(rel: Path) -> Path:
    """Return absolute path to a payload in both dev and PyInstaller one-file modes."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return (base / rel).resolve()

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def run_cmd(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    # print(">", " ".join(cmd))  # uncomment for debugging
    return subprocess.run(cmd, check=check, capture_output=True, text=True, shell=False)

def which(exe_name: str) -> Optional[Path]:
    # Prefer shutil.which, fallback to "where" for robustness
    from shutil import which as swhich
    path = swhich(exe_name)
    if path:
        return Path(path)
    try:
        cp = run_cmd(["where", exe_name], check=False)
        if cp.returncode == 0 and cp.stdout:
            first = cp.stdout.splitlines()[0].strip()
            if first and Path(first).exists():
                return Path(first)
    except Exception:
        pass
    return None

def copy_payload(src_rel: Path, dest: Path, overwrite: bool = False) -> bool:
    src = resource_path(src_rel)
    if not src.exists():
        return False
    if dest.exists() and not overwrite:
        return True
    ensure_dir(dest.parent)
    shutil.copy2(src, dest)
    return True

def open_firewall(port: int):
    name = f"{APP_NAME} {port}"
    _ = run_cmd(["netsh", "advfirewall", "firewall", "add", "rule",
                 f"name={name}", "dir=in", "action=allow",
                 "protocol=TCP", f"localport={port}"], check=False)

def get_primary_ipv4() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return None

# -------------------- GUI --------------------
class InstallerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} Installer")
        self.geometry("640x360")
        self.minsize(640, 360)
        self.configure(padx=18, pady=18)

        if not is_admin():
            if messagebox.askyesno("Administrator required",
                                   "This installer needs administrative privileges.\n\n"
                                   "Click Yes to restart with elevation."):
                relaunch_as_admin()
            else:
                self.destroy()
                sys.exit(1)

        self.var_install = tk.StringVar(value=str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / APP_NAME))
        self.var_data    = tk.StringVar(value=str(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / APP_NAME))
        self.var_port    = tk.StringVar(value=str(DEFAULT_PORT))

        self._build_form()
        self._build_actions()
        self._build_footer()

        # Splash/loading dialog will be created on demand
        self.splash: Optional[tk.Toplevel] = None
        self.progress = None  # type: Optional[ttk.Progressbar]
        self.log_text = None  # type: Optional[tk.Text]

    # ------------- UI construction -------------
    def _build_form(self):
        frm = ttk.LabelFrame(self, text="Configuration")
        frm.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Install dir
        ttk.Label(frm, text="Install directory (Program Files):").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 0))
        row0 = ttk.Frame(frm)
        row0.grid(row=1, column=0, sticky="ew", padx=8)
        row0.columnconfigure(0, weight=1)
        ttk.Entry(row0, textvariable=self.var_install).grid(row=0, column=0, sticky="ew")
        ttk.Button(row0, text="Browse...", command=self._pick_install_dir).grid(row=0, column=1, padx=(6, 0))

        # Data dir
        ttk.Label(frm, text="Data directory (DB, backups, logs):").grid(row=2, column=0, sticky="w", padx=8, pady=(12, 0))
        row1 = ttk.Frame(frm)
        row1.grid(row=3, column=0, sticky="ew", padx=8)
        row1.columnconfigure(0, weight=1)
        ttk.Entry(row1, textvariable=self.var_data).grid(row=0, column=0, sticky="ew")
        ttk.Button(row1, text="Browse...", command=self._pick_data_dir).grid(row=0, column=1, padx=(6, 0))

        # Port
        ttk.Label(frm, text="HTTP port:").grid(row=4, column=0, sticky="w", padx=8, pady=(12, 0))
        row2 = ttk.Frame(frm)
        row2.grid(row=5, column=0, sticky="w", padx=8)
        ttk.Entry(row2, width=10, textvariable=self.var_port).grid(row=0, column=0, sticky="w")

        # Hint
        ttk.Label(frm, text="Tip: Use a DNS name on your intranet rather than a raw IP for clients.").grid(
            row=6, column=0, sticky="w", padx=8, pady=(12, 12))

        for i in range(7):
            frm.rowconfigure(i, weight=0)
        frm.columnconfigure(0, weight=1)

    def _build_actions(self):
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        bar.columnconfigure(0, weight=1)

        self.btn_install = ttk.Button(bar, text="Install", command=self._on_install)
        self.btn_install.grid(row=0, column=1, sticky="e", padx=(0, 6))
        ttk.Button(bar, text="Exit", command=self.destroy).grid(row=0, column=2, sticky="e")

    def _build_footer(self):
        sep = ttk.Separator(self, orient="horizontal")
        sep.grid(row=2, column=0, sticky="ew", pady=(12, 6))
        ttk.Label(self, text=f"{APP_NAME} Installer", foreground="#666").grid(row=3, column=0, sticky="w")

    # ------------- Browse handlers -------------
    def _pick_install_dir(self):
        d = filedialog.askdirectory(initialdir=self.var_install.get(), mustexist=False)
        if d:
            self.var_install.set(d)

    def _pick_data_dir(self):
        d = filedialog.askdirectory(initialdir=self.var_data.get(), mustexist=False)
        if d:
            self.var_data.set(d)

    # ------------- Install workflow -------------
    def _on_install(self):
        try:
            port = int(self.var_port.get())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be an integer between 1 and 65535.")
            return

        install_dir = Path(self.var_install.get()).resolve()
        data_dir    = Path(self.var_data.get()).resolve()
        if str(install_dir).strip() == "" or str(data_dir).strip() == "":
            messagebox.showerror("Invalid directories", "Please choose both install and data directories.")
            return

        # Disable UI
        self.btn_install.configure(state="disabled")

        # Show splash/progress modal
        self._show_splash()

        # Run the installation in a worker thread
        worker = threading.Thread(
            target=self._install_worker,
            args=(install_dir, data_dir, port),
            daemon=True
        )
        worker.start()


    def _show_splash(self):
        self.splash = tk.Toplevel(self)
        self.splash.title("Installing...")
        self.splash.geometry("580x260+100+100")
        self.splash.resizable(False, False)
        self.splash.transient(self)
        self.splash.grab_set()

        # Content
        wrapper = ttk.Frame(self.splash, padding=16)
        wrapper.pack(fill="both", expand=True)

        ttk.Label(wrapper, text=f"Installing {APP_NAME} ...", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        self.progress = ttk.Progressbar(wrapper, mode="determinate", length=520, maximum=100)
        self.progress.pack(pady=(12, 8), anchor="w")
        self.progress["value"] = 0

        self.log_text = tk.Text(wrapper, height=8, width=70, wrap="word")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

        self.splash.update_idletasks()

    def _log(self, line: str):
        if not self.log_text:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.splash.update_idletasks()

    def _set_progress(self, pct: int):
        if self.progress:
            self.progress["value"] = pct
            self.splash.update_idletasks()

    def _install_worker(self, install_dir: Path, data_dir: Path, port: int):
        steps = [
            ("Creating directories", lambda: self._create_dirs(install_dir, data_dir)),
            ("Unpacking NSSM",      lambda: self._ensure_nssm(install_dir)),
            ("Copying application", lambda: self._copy_app(install_dir)),
            ("Seeding database",    lambda: self._seed_db(data_dir)),
            #("Opening firewall",    lambda: open_firewall(port)),
            #("Installing service",  lambda: self._install_service(install_dir, data_dir, port)),
            #("Starting service",    lambda: self._start_service()),
        ]
        pct_step = int(100 / max(len(steps), 1))
        cur = 0
        try:
            for title, fn in steps:
                self._log(f"[+] {title} ...")
                fn()
                cur += pct_step
                self._set_progress(min(cur, 100))
            # Success
            ip = get_primary_ipv4() or "localhost"
            url = f"http://{ip}:{port}/"
            self._log("")
            self._log(f"=== INSTALL COMPLETE ===")
            self._log(f"Install dir: {install_dir}")
            self._log(f"Data dir:    {data_dir}")
            self._log(f"Service:     {SERVICE_NAME}")
            self._log(f"Open in browser: {url}")

            ttk.Button(self.splash, text="Open in Browser",
                       command=lambda: self._open_url(url)).pack(pady=(8, 0))
            ttk.Button(self.splash, text="Close", command=self._finish_ok).pack(pady=(6, 8))
        except subprocess.CalledProcessError as cpe:
            self._log("")
            self._log(f"ERROR (exit {cpe.returncode}): {cpe.stderr or cpe.stdout}")
            messagebox.showerror("Installation failed", cpe.stderr or cpe.stdout or str(cpe))
            self._finish_fail()
        except Exception as ex:
            self._log("")
            self._log(f"ERROR: {ex}")
            messagebox.showerror("Installation failed", str(ex))
            self._finish_fail()

    def _finish_ok(self):
        try:
            self.splash.grab_release()
        except Exception:
            pass
        self.splash.destroy()
        self.destroy()

    def _finish_fail(self):
        self.btn_install.configure(state="normal")
        try:
            self.splash.grab_release()
        except Exception:
            pass
        # Keep splash open so logs remain visible

    def _open_url(self, url: str):
        import webbrowser
        webbrowser.open(url)

    # ------------- actual step implementations -------------
    def _create_dirs(self, install_dir: Path, data_dir: Path):
        ensure_dir(install_dir)
        ensure_dir(data_dir)
        ensure_dir(data_dir / "backups")
        ensure_dir(data_dir / "logs")

    def _ensure_nssm(self, install_dir: Path):
        found = which("nssm.exe")
        if found:
            self.nssm = found
            self._log(f"Using NSSM in PATH: {found}")
            return
        self._log("Bundled NSSM will be installed.")
        nssm_dir = install_dir / "nssm"
        ensure_dir(nssm_dir)
        target = nssm_dir / "nssm.exe"
        if not copy_payload(PAYLOAD_NSSM, target, overwrite=True):
            raise RuntimeError("Bundled nssm.exe not found in payload; cannot continue.")
        self.nssm = target

    def _copy_app(self, install_dir: Path):
        app_src_rel = PAYLOAD_APP
        app_dst = install_dir / f"{APP_NAME}.exe"
        if not copy_payload(app_src_rel, app_dst, overwrite=True):
            raise RuntimeError(f"Bundled application EXE not found at payload/{APP_NAME}.exe")
        self.app_exe = app_dst

    def _seed_db(self, data_dir: Path):
        db_path = data_dir / "tires.db"
        seed_path = resource_path(PAYLOAD_SEED_DB)
        if not db_path.exists() and seed_path.exists():
            shutil.copy2(seed_path, db_path)
            self._log("Seeded database from payload.")
        else:
            self._log("Database already present (or no seed).")

    def _install_service(self, install_dir: Path, data_dir: Path, port: int):
        # Your app should accept: --host, --port, --data-dir
        svc_cmd = [
            str(self.nssm), "install", SERVICE_NAME,
            str(self.app_exe),
            "--host", "0.0.0.0",
            "--port", str(port),
            "--data-dir", str(data_dir),
        ]
        run_cmd(svc_cmd, check=True)
        # Working dir
        run_cmd([str(self.nssm), "set", SERVICE_NAME, "AppDirectory", str(install_dir)], check=True)
        # Auto-start
        run_cmd([str(self.nssm), "set", SERVICE_NAME, "Start", "SERVICE_AUTO_START"], check=True)
        # Stdout/err logs to DataDir\logs
        run_cmd([str(self.nssm), "set", SERVICE_NAME, "AppStdout", str(data_dir / "logs" / "stdout.log")], check=True)
        run_cmd([str(self.nssm), "set", SERVICE_NAME, "AppStderr", str(data_dir / "logs" / "stderr.log")], check=True)

    def _start_service(self):
        run_cmd(["sc.exe", "start", SERVICE_NAME], check=False)

# -------------------- Entrypoint --------------------
def main():
    app = InstallerGUI()
    app.mainloop()

if __name__ == "__main__":
    main()


