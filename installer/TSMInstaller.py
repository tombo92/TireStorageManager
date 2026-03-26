#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-03-25
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
TSM Installer GUI  -  Windows installer for TireStorageManager

Produces a single EXE via PyInstaller that:

  INSTALL:
  1. Asks for install dir, data dir, HTTP port
  2. Shows a loading screen with progress bar + log
  3. Copies app EXE + NSSM into install dir
  4. Creates db/, backups/, logs/ in data dir
  5. Seeds the database from a bundled template (if present)
  6. Opens Windows Firewall for the chosen port
  7. Installs a Windows Service (auto-start) via NSSM
  8. Starts the service immediately
  9. Creates a daily Scheduled Task for update checks

  UNINSTALL:
  1. Stops the Windows Service
  2. Removes the Windows Service (via NSSM or sc.exe)
  3. Removes the scheduled daily task
  4. Removes firewall rules
  5. Deletes the install directory (EXE + NSSM)
  6. Optionally deletes the data directory (DB, backups, logs)

Build:
  pyinstaller installer/TSM-Installer.spec
"""
from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
import time
import winreg
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from installer import installer_logic as logic

# ========================================================
# CONSTANTS
# ========================================================
APP_NAME = "TireStorageManager"
SERVICE_NAME = "TireStorageManager"
DEFAULT_DISPLAY_NAME = "Reifenmanager"
DEFAULT_PORT = 5000

PAYLOAD_APP = Path("payload") / f"{APP_NAME}.exe"
PAYLOAD_NSSM = Path("payload") / "nssm.exe"
PAYLOAD_SEED_DB = Path("payload") / "db" / "wheel_storage.db"
PAYLOAD_PRERELEASE_MARKER = Path("payload") / "PRERELEASE"

# Registry key for persisting installer settings (HKCU)
REGISTRY_KEY = r"Software\TireStorageManager\Installer"

# Colours for the themed UI
BG_DARK = "#1e293b"
BG_CARD = "#334155"
FG_TEXT = "#f8fafc"
ACCENT = "#3b82f6"
SUCCESS = "#22c55e"
ERROR_CLR = "#ef4444"


# ========================================================
# UTILITY HELPERS
# ========================================================
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    params = " ".join([f'"{a}"' for a in sys.argv])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1)
    sys.exit(0)


def resource_path(rel: Path) -> Path:
    base = Path(getattr(sys, "_MEIPASS",
                        Path(__file__).resolve().parent))
    return (base / rel).resolve()


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


def open_url(url: str) -> None:
    """Open *url* in the default browser.

    webbrowser.open() silently fails when the calling process is elevated
    (admin) because browsers refuse to run as Administrator.
    ShellExecuteW delegates the launch to Explorer which runs at normal
    user privilege and opens the URL correctly.
    """
    try:
        ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "open", url, None, None, 1
        )
    except Exception:
        pass  # fallback: silently ignore on non-Windows or unexpected error


def is_prerelease_build() -> bool:
    """Return True if a PRERELEASE marker was bundled into the payload."""
    return resource_path(PAYLOAD_PRERELEASE_MARKER).exists()


# ========================================================
# INSTALLER GUI
# ========================================================
class InstallerApp(tk.Tk):
    """Main installer window with modern dark theme."""

    def __init__(self):
        super().__init__()
        self.title(f"{DEFAULT_DISPLAY_NAME} – Installer")
        self.geometry("720x680")
        self.minsize(720, 680)
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        # Window icon
        ico = resource_path(Path("assets") / "installer.ico")
        if ico.exists():
            self.iconbitmap(str(ico))

        # Require admin
        if not is_admin():
            if messagebox.askyesno(
                "Administrator erforderlich",
                "Dieses Installationsprogramm benötigt "
                "Administratorrechte.\n\n"
                "Jetzt mit erhöhten Rechten neu starten?"):
                relaunch_as_admin()
            else:
                self.destroy()
                sys.exit(1)

        # Variables
        default_install = str(
            Path(os.environ.get(
                "ProgramFiles", r"C:\Program Files")) / APP_NAME)
        default_data = str(
            Path(os.environ.get(
                "PROGRAMDATA", r"C:\ProgramData")) / APP_NAME)

        self.var_install = tk.StringVar(value=default_install)
        self.var_data = tk.StringVar(value=default_data)
        self.var_port = tk.StringVar(value=str(DEFAULT_PORT))
        self.var_display_name = tk.StringVar(value=DEFAULT_DISPLAY_NAME)
        self.var_secret_key = tk.StringVar(value="")
        self.var_shortcut = tk.BooleanVar(value=True)

        self._load_settings()  # overwrite defaults with saved values

        self.nssm: Optional[Path] = None
        self.app_exe: Optional[Path] = None

        self._build_ui()

    # --------------------------------------------------------
    # Registry persistence
    # --------------------------------------------------------
    def _load_settings(self) -> None:
        """Read previously saved installer inputs from the registry."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0,
                winreg.KEY_READ,
            )
            with key:
                def _str(name: str, var: tk.StringVar) -> None:
                    try:
                        val, _ = winreg.QueryValueEx(key, name)
                        if val:
                            var.set(val)
                    except FileNotFoundError:
                        pass

                def _bool(name: str, var: tk.BooleanVar) -> None:
                    try:
                        val, _ = winreg.QueryValueEx(key, name)
                        var.set(bool(val))
                    except FileNotFoundError:
                        pass

                _str("InstallDir",   self.var_install)
                _str("DataDir",      self.var_data)
                _str("Port",         self.var_port)
                _str("DisplayName",  self.var_display_name)
                # secret key intentionally NOT loaded for security
                _bool("Shortcut",   self.var_shortcut)
        except FileNotFoundError:
            pass  # key doesn't exist yet — first run

    def _save_settings(self) -> None:
        """Persist current installer inputs to the registry (HKCU)."""
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0,
                winreg.KEY_WRITE,
            )
            with key:
                winreg.SetValueEx(key, "InstallDir",  0,
                                  winreg.REG_SZ, self.var_install.get())
                winreg.SetValueEx(key, "DataDir",     0,
                                  winreg.REG_SZ, self.var_data.get())
                winreg.SetValueEx(key, "Port",        0,
                                  winreg.REG_SZ, self.var_port.get())
                winreg.SetValueEx(key, "DisplayName", 0,
                                  winreg.REG_SZ,
                                  self.var_display_name.get())
                winreg.SetValueEx(key, "Shortcut",    0,
                                  winreg.REG_DWORD,
                                  int(self.var_shortcut.get()))
                # secret key intentionally NOT saved for security
        except OSError:
            pass  # silently ignore — registry write failed

    # --------------------------------------------------------
    # UI Construction
    # --------------------------------------------------------
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=ACCENT, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text=f"  {DEFAULT_DISPLAY_NAME}  –  Installer",
            bg=ACCENT, fg="white",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=12, pady=10)

        # Pre-release warning banner
        if is_prerelease_build():
            warn = tk.Frame(self, bg="#eab308")
            warn.pack(fill="x")
            tk.Label(
                warn,
                text="⚠  TEST-VERSION  –  Nicht für den produktiven Einsatz geeignet",
                bg="#eab308", fg="#1e293b",
                font=("Segoe UI", 9, "bold"),
            ).pack(pady=4)

        # Body card
        body = tk.Frame(self, bg=BG_CARD, padx=24, pady=18)
        body.pack(fill="both", expand=True, padx=20, pady=(16, 8))

        # --- Install dir ---
        tk.Label(
            body, text="Installationsverzeichnis (EXE + NSSM):",
            bg=BG_CARD, fg=FG_TEXT, font=("Segoe UI", 10),
        ).pack(anchor="w")
        row0 = tk.Frame(body, bg=BG_CARD)
        row0.pack(fill="x", pady=(2, 10))
        tk.Entry(
            row0, textvariable=self.var_install,
            font=("Consolas", 10), bg="#475569", fg=FG_TEXT,
            insertbackground=FG_TEXT, relief="flat",
        ).pack(side="left", fill="x", expand=True, ipady=4)
        tk.Button(
            row0, text="…", width=3,
            command=self._pick_install,
            bg=ACCENT, fg="white", relief="flat",
        ).pack(side="left", padx=(6, 0))

        # --- Data dir ---
        tk.Label(
            body, text="Datenverzeichnis (DB, Backups, Logs):",
            bg=BG_CARD, fg=FG_TEXT, font=("Segoe UI", 10),
        ).pack(anchor="w")
        row1 = tk.Frame(body, bg=BG_CARD)
        row1.pack(fill="x", pady=(2, 10))
        tk.Entry(
            row1, textvariable=self.var_data,
            font=("Consolas", 10), bg="#475569", fg=FG_TEXT,
            insertbackground=FG_TEXT, relief="flat",
        ).pack(side="left", fill="x", expand=True, ipady=4)
        tk.Button(
            row1, text="…", width=3,
            command=self._pick_data,
            bg=ACCENT, fg="white", relief="flat",
        ).pack(side="left", padx=(6, 0))

        # --- Port ---
        tk.Label(
            body, text="HTTP Port:", bg=BG_CARD,
            fg=FG_TEXT, font=("Segoe UI", 10),
        ).pack(anchor="w")
        tk.Entry(
            body, textvariable=self.var_port, width=8,
            font=("Consolas", 10), bg="#475569", fg=FG_TEXT,
            insertbackground=FG_TEXT, relief="flat",
        ).pack(anchor="w", pady=(2, 10), ipady=4)

        # --- Display name ---
        tk.Label(
            body, text="Programmtitel (wird in der Oberfläche angezeigt):",
            bg=BG_CARD, fg=FG_TEXT, font=("Segoe UI", 10),
        ).pack(anchor="w")
        tk.Entry(
            body, textvariable=self.var_display_name,
            font=("Consolas", 10), bg="#475569", fg=FG_TEXT,
            insertbackground=FG_TEXT, relief="flat",
        ).pack(fill="x", pady=(2, 10), ipady=4)

        # --- Secret key ---
        tk.Label(
            body, text="Geheimer Schlüssel (für Sitzungssicherheit):",
            bg=BG_CARD, fg=FG_TEXT, font=("Segoe UI", 10),
        ).pack(anchor="w")
        tk.Entry(
            body, textvariable=self.var_secret_key, show="•",
            font=("Consolas", 10), bg="#475569", fg=FG_TEXT,
            insertbackground=FG_TEXT, relief="flat",
        ).pack(fill="x", pady=(2, 10), ipady=4)

        # Hint
        tk.Label(
            body,
            text="Tipp: Verwenden Sie einen DNS-Namen im "
                 "Intranet statt einer reinen IP-Adresse.",
            bg=BG_CARD, fg="#94a3b8", font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(4, 0))

        # --- Desktop shortcut ---
        tk.Checkbutton(
            body,
            text="Desktop-Verknüpfung erstellen"
                 " (öffnet die Web-Oberfläche im Browser)",
            variable=self.var_shortcut,
            bg=BG_CARD, fg=FG_TEXT,
            selectcolor=BG_CARD,
            activebackground=BG_CARD,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(10, 0))

        # --- Buttons ---
        bar = tk.Frame(self, bg=BG_DARK)
        bar.pack(fill="x", padx=20, pady=(0, 16))

        self.btn_install = tk.Button(
            bar, text="  Installieren  ",
            font=("Segoe UI", 11, "bold"),
            bg=SUCCESS, fg="white", relief="flat",
            activebackground="#16a34a", activeforeground="white",
            command=self._on_install,
        )
        self.btn_install.pack(side="right", padx=(8, 0))

        self.btn_uninstall = tk.Button(
            bar, text="  Deinstallieren  ",
            font=("Segoe UI", 10),
            bg=ERROR_CLR, fg="white", relief="flat",
            activebackground="#dc2626", activeforeground="white",
            command=self._on_uninstall,
        )
        self.btn_uninstall.pack(side="right", padx=(8, 0))

        tk.Button(
            bar, text="  Beenden  ",
            font=("Segoe UI", 10),
            bg="#64748b", fg="white", relief="flat",
            command=self.destroy,
        ).pack(side="right")

    # --------------------------------------------------------
    # Browse helpers
    # --------------------------------------------------------
    def _pick_install(self):
        d = filedialog.askdirectory(
            initialdir=self.var_install.get(), mustexist=False)
        if d:
            self.var_install.set(d)

    def _pick_data(self):
        d = filedialog.askdirectory(
            initialdir=self.var_data.get(), mustexist=False)
        if d:
            self.var_data.set(d)

    # --------------------------------------------------------
    # Install kick-off
    # --------------------------------------------------------
    def _on_install(self):
        # Validate port
        try:
            port = int(self.var_port.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Ungültiger Port",
                "Port muss zwischen 1 und 65535 liegen.")
            return

        install_dir = Path(self.var_install.get()).resolve()
        data_dir = Path(self.var_data.get()).resolve()

        if not str(install_dir).strip() or not str(data_dir).strip():
            messagebox.showerror(
                "Verzeichnis fehlt",
                "Bitte beide Verzeichnisse angeben.")
            return

        display_name = self.var_display_name.get().strip() or DEFAULT_DISPLAY_NAME
        secret_key = self.var_secret_key.get().strip()
        shortcut = self.var_shortcut.get()

        self._save_settings()
        self.btn_install.configure(state="disabled")
        self.btn_uninstall.configure(state="disabled")
        ProgressWindow(self, install_dir, data_dir, port,
                       display_name, secret_key, shortcut)

    # --------------------------------------------------------
    # Uninstall kick-off
    # --------------------------------------------------------
    def _on_uninstall(self):
        install_dir = Path(self.var_install.get()).resolve()
        data_dir = Path(self.var_data.get()).resolve()

        if not str(install_dir).strip():
            messagebox.showerror(
                "Verzeichnis fehlt",
                "Bitte das Installationsverzeichnis angeben.")
            return

        # Ask for confirmation
        keep_data = messagebox.askyesno(
            "Daten behalten?",
            "Sollen die Benutzerdaten (Datenbank, Backups, Logs) "
            "erhalten bleiben?\n\n"
            "  Ja  →  Nur Programm und Dienst entfernen\n"
            "  Nein →  ALLES löschen (unwiderruflich!)",
            icon="warning",
        )

        confirm = messagebox.askyesno(
            "Deinstallation bestätigen",
            f"Folgendes wird entfernt:\n\n"
            f"  • Windows-Dienst: {SERVICE_NAME}\n"
            f"  • Firewall-Regel\n"
            f"  • Geplanter Task\n"
            f"  • Installationsverzeichnis:\n"
            f"    {install_dir}\n"
            + (f"  • Datenverzeichnis:\n"
               f"    {data_dir}\n"
               if not keep_data else "") +
            "\nFortfahren?",
            icon="warning",
        )
        if not confirm:
            return

        self.btn_install.configure(state="disabled")
        self.btn_uninstall.configure(state="disabled")
        display_name = self.var_display_name.get().strip() or DEFAULT_DISPLAY_NAME
        self._save_settings()
        UninstallProgressWindow(
            self, install_dir, data_dir,
            keep_data=keep_data,
            display_name=display_name)


# ========================================================
# PROGRESS / LOADING SCREEN
# ========================================================
class ProgressWindow(tk.Toplevel):
    """Modal loading screen with animated progress bar and log."""

    def __init__(self, parent: InstallerApp,
                 install_dir: Path, data_dir: Path, port: int,
                 display_name: str, secret_key: str,
                 shortcut: bool = True):
        super().__init__(parent)
        self.parent_app = parent
        self.install_dir = install_dir
        self.data_dir = data_dir
        self.port = port
        self.display_name = display_name
        self.secret_key = secret_key
        self.shortcut = shortcut

        self.title("Installation läuft …")
        self.geometry("660x400")
        self.resizable(False, False)
        self.configure(bg=BG_DARK)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # block close

        self._build()
        self._start_worker()

    def _build(self):
        tk.Label(
            self, text=f"{self.display_name} wird installiert …",
            bg=BG_DARK, fg=FG_TEXT,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=20, pady=(18, 6))

        # Progress bar
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "install.Horizontal.TProgressbar",
            troughcolor=BG_CARD,
            background=ACCENT,
            thickness=22,
        )
        self.progress = ttk.Progressbar(
            self, style="install.Horizontal.TProgressbar",
            orient="horizontal", length=610,
            mode="determinate", maximum=100,
        )
        self.progress.pack(padx=20, pady=(0, 10))

        # Step label
        self.step_label = tk.Label(
            self, text="Vorbereitung …", bg=BG_DARK,
            fg="#94a3b8", font=("Segoe UI", 9),
        )
        self.step_label.pack(anchor="w", padx=20)

        # Log text
        self.log_text = tk.Text(
            self, height=12, wrap="word",
            bg="#0f172a", fg="#e2e8f0",
            font=("Consolas", 9),
            relief="flat", borderwidth=0,
            insertbackground=FG_TEXT,
        )
        self.log_text.pack(fill="both", expand=True,
                           padx=20, pady=(8, 12))
        self.log_text.configure(state="disabled")

        # Button row (hidden until done)
        self.btn_frame = tk.Frame(self, bg=BG_DARK)
        self.btn_frame.pack(fill="x", padx=20, pady=(0, 14))

    # ---- Logging helpers (thread-safe via after) ----
    def _log(self, line: str):
        self.after(0, self._log_ui, line)

    def _log_ui(self, line: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_progress(self, pct: int, label: str = ""):
        self.after(0, self._set_progress_ui, pct, label)

    def _set_progress_ui(self, pct: int, label: str):
        self.progress["value"] = min(pct, 100)
        if label:
            self.step_label.configure(text=label)

    def _show_result_buttons(self, success: bool, url: str = ""):
        self.after(0, self._show_buttons_ui, success, url)

    def _show_buttons_ui(self, success: bool, url: str):
        self.protocol("WM_DELETE_WINDOW", self._close)
        if success and url:
            tk.Button(
                self.btn_frame, text="  Im Browser öffnen  ",
                font=("Segoe UI", 10, "bold"),
                bg=ACCENT, fg="white", relief="flat",
                command=lambda: open_url(url),
            ).pack(side="left")
        tk.Button(
            self.btn_frame, text="  Schließen  ",
            font=("Segoe UI", 10),
            bg="#64748b", fg="white", relief="flat",
            command=self._close,
        ).pack(side="right")

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self.parent_app.btn_install.configure(state="normal")
        self.parent_app.btn_uninstall.configure(state="normal")

    # ---- Worker thread ----
    def _start_worker(self):
        threading.Thread(
            target=self._worker, daemon=True).start()

    def _worker(self):
        steps = [
            ("Verzeichnisse anlegen",         self._step_dirs),
            ("NSSM bereitstellen",            self._step_nssm),
            ("Anwendung kopieren",            self._step_app),
            ("Datenbank vorbereiten",         self._step_db),
            ("Firewall-Regel erstellen",      self._step_firewall),
            ("Windows-Dienst installieren",   self._step_service),
            ("Dienst starten",                self._step_start),
            ("Tägliches Update einrichten",   self._step_update_task),
        ]
        if self.shortcut:
            steps.append(
                ("Desktop-Verknüpfung erstellen", self._step_shortcut)
            )
        total = len(steps)
        try:
            for i, (title, fn) in enumerate(steps):
                pct = int((i / total) * 100)
                self._set_progress(pct, title)
                self._log(f"[{i+1}/{total}] {title} …")
                fn()
                time.sleep(0.15)  # small delay for visual feedback

            self._set_progress(100, "Installation abgeschlossen ✓")
            self._log("")
            ip = get_primary_ipv4() or "localhost"
            url = f"http://{ip}:{self.port}/"
            self._log("═" * 50)
            self._log("  Installation erfolgreich!")
            self._log(f"  Installationsverzeichnis: {self.install_dir}")
            self._log(f"  Datenverzeichnis:         {self.data_dir}")
            self._log(f"  Dienst:                   {SERVICE_NAME}")
            self._log(f"  URL:  {url}")
            self._log("═" * 50)
            self._show_result_buttons(True, url)

        except Exception as ex:
            self._log(f"\n✗ FEHLER: {ex}")
            self._set_progress(0, "Installation fehlgeschlagen")
            self._show_result_buttons(False)

    # ---- Individual install steps ----
    def _step_dirs(self):
        logic.create_directories(
            self.install_dir, self.data_dir, log=self._log)

    def _step_nssm(self):
        src = resource_path(PAYLOAD_NSSM)
        target = logic.deploy_nssm(src, self.install_dir, log=self._log)
        self.parent_app.nssm = target

    def _step_app(self):
        src = resource_path(PAYLOAD_APP)
        target = logic.deploy_app_exe(src, self.install_dir, log=self._log)
        self.parent_app.app_exe = target

    def _step_db(self):
        seed = resource_path(PAYLOAD_SEED_DB)
        logic.seed_database(seed, self.data_dir, log=self._log)

    def _step_firewall(self):
        logic.add_firewall_rule(self.port, log=self._log)

    def _step_service(self):
        nssm = self.parent_app.nssm
        app_exe = self.parent_app.app_exe
        logic.install_service(
            nssm, app_exe, self.data_dir, self.port,
            self.install_dir,
            display_name=self.display_name,
            secret_key=self.secret_key,
            log=self._log)

    def _step_start(self):
        logic.start_service(self.parent_app.nssm, log=self._log)

    def _step_update_task(self):
        logic.create_update_task(log=self._log)

    def _step_shortcut(self):
        ip = get_primary_ipv4() or "localhost"
        url = f"http://{ip}:{self.port}/"
        logic.create_desktop_shortcut(url, self.display_name, log=self._log)


# ========================================================
# UNINSTALL PROGRESS SCREEN
# ========================================================
class UninstallProgressWindow(tk.Toplevel):
    """Modal window that reverses all installation steps."""

    def __init__(self, parent: InstallerApp,
                 install_dir: Path, data_dir: Path,
                 keep_data: bool, display_name: str = "Reifenmanager"):
        super().__init__(parent)
        self.parent_app = parent
        self.install_dir = install_dir
        self.data_dir = data_dir
        self.keep_data = keep_data
        self.display_name = display_name

        self.title("Deinstallation läuft …")
        self.geometry("660x400")
        self.resizable(False, False)
        self.configure(bg=BG_DARK)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        self._build()
        self._start_worker()

    def _build(self):
        tk.Label(
            self, text=f"{self.display_name} wird deinstalliert …",
            bg=BG_DARK, fg=FG_TEXT,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=20, pady=(18, 6))

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "uninstall.Horizontal.TProgressbar",
            troughcolor=BG_CARD,
            background=ERROR_CLR,
            thickness=22,
        )
        self.progress = ttk.Progressbar(
            self, style="uninstall.Horizontal.TProgressbar",
            orient="horizontal", length=610,
            mode="determinate", maximum=100,
        )
        self.progress.pack(padx=20, pady=(0, 10))

        self.step_label = tk.Label(
            self, text="Vorbereitung …", bg=BG_DARK,
            fg="#94a3b8", font=("Segoe UI", 9),
        )
        self.step_label.pack(anchor="w", padx=20)

        self.log_text = tk.Text(
            self, height=12, wrap="word",
            bg="#0f172a", fg="#e2e8f0",
            font=("Consolas", 9),
            relief="flat", borderwidth=0,
            insertbackground=FG_TEXT,
        )
        self.log_text.pack(fill="both", expand=True,
                           padx=20, pady=(8, 12))
        self.log_text.configure(state="disabled")

        self.btn_frame = tk.Frame(self, bg=BG_DARK)
        self.btn_frame.pack(fill="x", padx=20, pady=(0, 14))

    # ---- Thread-safe UI helpers ----
    def _log(self, line: str):
        self.after(0, self._log_ui, line)

    def _log_ui(self, line: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_progress(self, pct: int, label: str = ""):
        self.after(0, self._set_progress_ui, pct, label)

    def _set_progress_ui(self, pct: int, label: str):
        self.progress["value"] = min(pct, 100)
        if label:
            self.step_label.configure(text=label)

    def _show_result_buttons(self, success: bool):
        self.after(0, self._show_buttons_ui, success)

    def _show_buttons_ui(self, success: bool):
        self.protocol("WM_DELETE_WINDOW", self._close)
        tk.Button(
            self.btn_frame, text="  Schließen  ",
            font=("Segoe UI", 10),
            bg="#64748b", fg="white", relief="flat",
            command=self._close,
        ).pack(side="right")

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self.parent_app.btn_install.configure(state="normal")
        self.parent_app.btn_uninstall.configure(state="normal")

    # ---- Worker thread ----
    def _start_worker(self):
        threading.Thread(
            target=self._worker, daemon=True).start()

    def _worker(self):
        steps = [
            ("Dienst stoppen",              self._step_stop_service),
            ("Windows-Dienst entfernen",    self._step_remove_service),
            ("Geplanten Task entfernen",    self._step_remove_task),
            ("Firewall-Regel entfernen",    self._step_remove_firewall),
            ("Programmdateien entfernen",   self._step_remove_install),
            ("Desktop-Verknüpfung entfernen", self._step_remove_shortcut),
        ]
        if not self.keep_data:
            steps.append(
                ("Datenverzeichnis entfernen", self._step_remove_data))

        total = len(steps)
        try:
            for i, (title, fn) in enumerate(steps):
                pct = int((i / total) * 100)
                self._set_progress(pct, title)
                self._log(f"[{i+1}/{total}] {title} …")
                fn()
                time.sleep(0.15)

            self._set_progress(100, "Deinstallation abgeschlossen ✓")
            self._log("")
            self._log("═" * 50)
            self._log("  Deinstallation erfolgreich!")
            if self.keep_data:
                self._log(f"  Daten erhalten in: {self.data_dir}")
            self._log("═" * 50)
            self._show_result_buttons(True)

        except Exception as ex:
            self._log(f"\n✗ FEHLER: {ex}")
            self._set_progress(0, "Deinstallation fehlgeschlagen")
            self._show_result_buttons(False)

    # ---- Individual uninstall steps ----
    def _step_stop_service(self):
        logic.stop_service(self.install_dir, log=self._log)
        # stop_service already waits for the process to exit;
        # add a small extra buffer before file deletion begins.
        time.sleep(2)

    def _step_remove_service(self):
        logic.remove_service(self.install_dir, log=self._log)

    def _step_remove_task(self):
        logic.remove_scheduled_task(log=self._log)

    def _step_remove_firewall(self):
        try:
            ui_port = int(self.parent_app.var_port.get())
        except (ValueError, AttributeError):
            ui_port = None
        logic.remove_firewall_rules(extra_port=ui_port, log=self._log)

    def _step_remove_install(self):
        logic.remove_install_dir(self.install_dir, log=self._log)

    def _step_remove_data(self):
        logic.remove_data_dir(self.data_dir, log=self._log)

    def _step_remove_shortcut(self):
        logic.remove_desktop_shortcut(self.display_name, log=self._log)


# ========================================================
# ENTRY POINT
# ========================================================
def main():
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()


