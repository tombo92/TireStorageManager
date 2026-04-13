#!/usr/bin/env python
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

import argparse
import ctypes
import json
import os
import socket
import sys
import threading
import time
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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
BG_UPDATE = "#166534"   # dark-green banner for update notification

# Release notes shorter than this many characters are treated as stubs
# (e.g. auto-generated "Siehe Commit-Historie …" bodies) — the details
# dialog then shows extra links to the CHANGELOG and commit history.
_UPDATE_NOTES_STUB_THRESHOLD = 120


# ========================================================
# UTILITY HELPERS
# ========================================================
def is_admin() -> bool:
    """Check if the application is running with administrative privileges.
    """
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


def get_primary_ipv4() -> str | None:
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

    def __init__(self, dev_mode: bool = False):
        super().__init__()
        self.dev_mode = dev_mode
        self.title(f"{DEFAULT_DISPLAY_NAME} – Installer"
                   + ("  [DEV MODE]" if dev_mode else ""))
        self.geometry("720x680")
        self.minsize(720, 680)
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        # Window icon
        ico = resource_path(Path("assets") / "installer.ico")
        if ico.exists():
            self.iconbitmap(str(ico))

        # Require admin (skip in dev mode — no OS actions will be performed)
        if not dev_mode and not is_admin():
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

        self.nssm: Path | None = None
        self.app_exe: Path | None = None
        self._update_info: dict | None = None

        self._build_ui()
        self._start_update_check()

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

        # Dev-mode banner (always visible when --ui-dev is active)
        if self.dev_mode:
            dev_bar = tk.Frame(self, bg="#92400e")
            dev_bar.pack(fill="x")
            tk.Label(
                dev_bar,
                text="🛠  UI-DEV-MODUS  –  Keine echten Aktionen werden ausgeführt",
                bg="#92400e", fg="#fef3c7",
                font=("Segoe UI", 9, "bold"),
            ).pack(pady=4)

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

        # Update notification banner (populated asynchronously when update found)
        self._update_frame = tk.Frame(self, bg=BG_UPDATE)
        self._update_frame.pack(fill="x")  # empty — zero effective height until populated

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
            body,
            text="Geheimer Schlüssel (optional – für Sitzungssicherheit):",
            bg=BG_CARD, fg=FG_TEXT, font=("Segoe UI", 10),
        ).pack(anchor="w")
        tk.Entry(
            body, textvariable=self.var_secret_key, show="•",
            font=("Consolas", 10), bg="#475569", fg=FG_TEXT,
            insertbackground=FG_TEXT, relief="flat",
        ).pack(fill="x", pady=(2, 4), ipady=4)
        tk.Label(
            body,
            text="Leer lassen, um den Standard-Schlüssel zu verwenden. "
                 "Empfohlen: eigenen Schlüssel setzen.",
            bg=BG_CARD, fg="#94a3b8", font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 6))

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

        self.btn_restore_db = tk.Button(
            bar, text="  DB wiederherstellen  ",
            font=("Segoe UI", 10),
            bg="#7c3aed", fg="white", relief="flat",
            activebackground="#6d28d9", activeforeground="white",
            command=self._on_restore_db,
        )
        self.btn_restore_db.pack(side="right", padx=(8, 0))

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
    # Async update check
    # --------------------------------------------------------
    def _start_update_check(self) -> None:
        """Launch a background thread to check GitHub for a newer version."""
        threading.Thread(
            target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self) -> None:
        try:
            from config import VERSION  # noqa: PLC0415
            info = logic.fetch_update_info(VERSION)
        except Exception:
            return
        if info.get("update_available"):
            self.after(0, self._show_update_banner, info)

    def _show_update_banner(self, info: dict) -> None:
        """Populate the pre-allocated update banner with version info."""
        self._update_info = info
        rv = info.get("remote_version", "?")
        cv = info.get("current_version", "?")

        # Row 1 – version headline (full width)
        row1 = tk.Frame(self._update_frame, bg=BG_UPDATE)
        row1.pack(fill="x")
        tk.Label(
            row1,
            text=f"  🔔  Version {rv} verfügbar  (aktuell: {cv})",
            bg=BG_UPDATE, fg="white",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=10, pady=(5, 2))

        # Row 2 – data note on the left, action buttons on the right
        row2 = tk.Frame(self._update_frame, bg=BG_UPDATE)
        row2.pack(fill="x")
        tk.Label(
            row2,
            text="  Ihre Daten (DB, Backups, Logs) bleiben vollständig erhalten.",
            bg=BG_UPDATE, fg="#bbf7d0",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=10, pady=(2, 5))
        tk.Button(
            row2, text="Infos & Changelog",
            font=("Segoe UI", 9),
            bg="#15803d", fg="white", relief="flat",
            activebackground="#166534", activeforeground="white",
            command=lambda: self._on_view_update_details(info),
        ).pack(side="right", padx=6, pady=(2, 5))
        # Only shown when a direct installer download is available;
        # without it the user should use the manual download link in the
        # details dialog.
        installer_url = info.get("installer_url")
        if installer_url or self.dev_mode:
            tk.Button(
                row2,
                text="  Neuen Installer laden & starten  ",
                font=("Segoe UI", 9, "bold"),
                bg=SUCCESS, fg="white", relief="flat",
                activebackground="#16a34a", activeforeground="white",
                command=lambda: self._on_do_update(info),
            ).pack(side="right", padx=4, pady=(2, 5))

    def _on_view_update_details(self, info: dict) -> None:
        UpdateDetailsDialog(self, info)

    def _on_do_update(self, info: dict) -> None:
        """Download the new installer and launch it; close current installer."""
        installer_url = info.get("installer_url")
        if not installer_url:
            messagebox.showinfo(
                "Kein Installer-Asset",
                f"Für Version {info.get('remote_version')} ist noch kein "
                "Download-Asset auf GitHub verfügbar.\n\n"
                "Bitte laden Sie die neue Version manuell herunter:\n"
                f"{info.get('release_url', '')}",
            )
            return
        if self.dev_mode:
            messagebox.showinfo(
                "DEV-MODUS",
                f"DEV: Würde Installer von\n{installer_url}\nherunterladen"
                " und starten.\nKeine echte Aktion im UI-Dev-Modus.",
            )
            return
        UpdateDownloadWindow(self, installer_url, info)

    # --------------------------------------------------------
    # Install kick-off
    # --------------------------------------------------------
    def _on_install(self):
        # Validate port
        try:
            port = logic.validate_port(self.var_port.get())
        except ValueError as exc:
            messagebox.showerror("Ungültiger Port", str(exc))
            return

        install_dir = Path(self.var_install.get()).resolve()
        data_dir = Path(self.var_data.get()).resolve()

        if not str(install_dir).strip() or not str(data_dir).strip():
            messagebox.showerror(
                "Verzeichnis fehlt",
                "Bitte beide Verzeichnisse angeben.")
            return

        display_name = logic.resolve_display_name(
            self.var_display_name.get())
        secret_key = self.var_secret_key.get().strip()
        shortcut = self.var_shortcut.get()

        # Detect re-install scenario and warn the user.
        if not self.dev_mode and logic.service_exists():
            if not messagebox.askyesno(
                "Bereits installiert",
                f"Der Dienst '{SERVICE_NAME}' ist auf diesem System "
                "bereits registriert.\n\n"
                "Die Installation wird den vorhandenen Dienst aktualisieren "
                "(Neuinstallation über die bestehende Version). "
                "Ihre Datenbank, Backups und Logs bleiben dabei "
                "vollständig erhalten.\n\n"
                "Fortfahren?",
                icon="warning",
            ):
                return

        self._save_settings()
        self.btn_install.configure(state="disabled")
        self.btn_uninstall.configure(state="disabled")
        ProgressWindow(self, install_dir, data_dir, port,
                       display_name, secret_key, shortcut,
                       dev_mode=self.dev_mode)

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

        # Detect nothing-to-uninstall scenario.
        if not self.dev_mode and not logic.service_exists():
            messagebox.showinfo(
                "Dienst nicht gefunden",
                f"Der Dienst '{SERVICE_NAME}' ist auf diesem System "
                "nicht registriert.\n\n"
                "Falls das Programm noch installiert ist, prüfen Sie das "
                "Installationsverzeichnis und stellen Sie sicher, dass Sie "
                "als Administrator ausführen.\n\n"
                "Falls das Programm bereits deinstalliert wurde, ist keine "
                "weitere Aktion notwendig.",
            )
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
        display_name = logic.resolve_display_name(self.var_display_name.get())
        self._save_settings()
        UninstallProgressWindow(
            self, install_dir, data_dir,
            keep_data=keep_data,
            display_name=display_name,
            dev_mode=self.dev_mode)

    # --------------------------------------------------------
    # Restore-DB kick-off
    # --------------------------------------------------------
    def _on_restore_db(self):
        install_dir = Path(self.var_install.get()).resolve()
        data_dir = Path(self.var_data.get()).resolve()

        if not str(install_dir).strip() or not str(data_dir).strip():
            messagebox.showerror(
                "Verzeichnis fehlt",
                "Bitte Installations- und Datenverzeichnis angeben.")
            return

        source = filedialog.askopenfilename(
            title="Datenbank-Backup auswählen",
            filetypes=[("SQLite-Datenbank", "*.db"), ("Alle Dateien", "*.*")],
        )
        if not source:
            return

        source_path = Path(source).resolve()

        # Validate before asking for the heavy confirmation.
        try:
            logic.validate_sqlite_file(source_path)
        except ValueError as exc:
            messagebox.showerror(
                "Ungültige Datenbank",
                f"Die gewählte Datei kann nicht verwendet werden:\n\n"
                f"{exc}",
            )
            return

        if not messagebox.askyesno(
            "Datenbank wiederherstellen?",
            f"Die aktuelle Datenbank wird durch\n\n"
            f"  {source_path.name}\n\n"
            f"ersetzt. Die aktuelle Datenbank wird vorher als Backup\n"
            f"im Backups-Ordner gesichert.\n\n"
            f"Der Dienst wird kurz gestoppt und danach neu gestartet.\n\n"
            f"Fortfahren?",
            icon="warning",
        ):
            return

        self.btn_install.configure(state="disabled")
        self.btn_uninstall.configure(state="disabled")
        self.btn_restore_db.configure(state="disabled")
        RestoreProgressWindow(self, install_dir, data_dir, source_path,
                              dev_mode=self.dev_mode)


# ========================================================
# PROGRESS / LOADING SCREEN
# ========================================================
class ProgressWindow(tk.Toplevel):
    """Modal loading screen with animated progress bar and log."""

    # Bounce animation constants
    _BOUNCE_FRAMES = 20        # steps per up/down cycle
    _BOUNCE_HEIGHT = 18        # pixels of vertical travel
    _BOUNCE_INTERVAL_MS = 30   # ms per frame  (~33 fps)
    _IMG_SIZE = 64             # px to display the avatar at

    def __init__(self, parent: InstallerApp,
                 install_dir: Path, data_dir: Path, port: int,
                 display_name: str, secret_key: str,
                 shortcut: bool = True,
                 dev_mode: bool = False):
        super().__init__(parent)
        self.parent_app = parent
        self.install_dir = install_dir
        self.data_dir = data_dir
        self.port = port
        self.display_name = display_name
        self.secret_key = secret_key
        self.shortcut = shortcut
        self.dev_mode = dev_mode

        self.title("Installation läuft …")
        self.geometry("660x430")
        self.resizable(False, False)
        self.configure(bg=BG_DARK)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # block close

        self._bounce_y = 0
        self._bounce_direction = 1
        self._bounce_frame = 0
        self._avatar_label: tk.Label | None = None
        self._avatar_image = None  # keep reference to prevent GC

        self._build()
        self._load_avatar()
        self._start_worker()

    def _build(self):
        # ── Top row: title + bouncing avatar ────────────────────────
        top_row = tk.Frame(self, bg=BG_DARK)
        top_row.pack(fill="x", padx=20, pady=(18, 6))

        tk.Label(
            top_row, text=f"{self.display_name} wird installiert …",
            bg=BG_DARK, fg=FG_TEXT,
            font=("Segoe UI", 13, "bold"),
        ).pack(side="left")

        # Canvas for the bouncing avatar (fixed size, transparent bg)
        avatar_size = self._IMG_SIZE + self._BOUNCE_HEIGHT + 4
        self._avatar_canvas = tk.Canvas(
            top_row, width=self._IMG_SIZE, height=avatar_size,
            bg=BG_DARK, highlightthickness=0,
        )
        self._avatar_canvas.pack(side="right")

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

    # ---- Avatar bounce animation ----
    def _load_avatar(self):
        """Load assets/dev.png and start the bounce loop."""
        # Resolve path: works both from source and inside a PyInstaller EXE.
        base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
        img_path = Path(base) / "assets" / "dev.png"
        if not img_path.exists():
            return  # silently skip if asset is missing
        try:
            self._avatar_image = tk.PhotoImage(file=str(img_path))
            # Scale down to _IMG_SIZE using subsample if the image is larger
            orig_w = self._avatar_image.width()
            orig_h = self._avatar_image.height()
            factor = max(1, max(orig_w, orig_h) // self._IMG_SIZE)
            if factor > 1:
                self._avatar_image = self._avatar_image.subsample(
                    factor, factor)
        except tk.TclError:
            return  # unsupported format / Tk too old
        self._bounce_tick()

    def _bounce_tick(self):
        """Advance one frame of the sinusoidal bounce."""
        import math
        canvas = self._avatar_canvas
        canvas.delete("avatar")
        t = self._bounce_frame / self._BOUNCE_FRAMES
        # sin curve: 0 → top, 1 → bottom of travel
        offset = int(math.sin(t * math.pi) * self._BOUNCE_HEIGHT)
        canvas_h = self._IMG_SIZE + self._BOUNCE_HEIGHT + 4
        y = (canvas_h - self._IMG_SIZE) - offset   # higher offset = higher up
        canvas.create_image(
            self._IMG_SIZE // 2, y,
            image=self._avatar_image, anchor="n", tags="avatar",
        )
        # Shadow ellipse at the bottom — shrinks as avatar rises
        shadow_scale = 1.0 - (offset / self._BOUNCE_HEIGHT) * 0.6
        sw = int(self._IMG_SIZE * 0.5 * shadow_scale)
        sx = self._IMG_SIZE // 2
        sy = canvas_h - 6
        canvas.create_oval(
            sx - sw, sy - 3, sx + sw, sy + 3,
            fill="#0f172a", outline="", tags="avatar",
        )
        self._bounce_frame = (
            (self._bounce_frame + 1) % (self._BOUNCE_FRAMES * 2)
        )
        self._bounce_job = self.after(
            self._BOUNCE_INTERVAL_MS, self._bounce_tick)

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
        if hasattr(self, "_bounce_job"):
            self.after_cancel(self._bounce_job)
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
                if self.dev_mode:
                    self._log("   [DEV] Simulation – keine echte Aktion.")
                    time.sleep(0.4)
                else:
                    fn()
                    time.sleep(0.15)  # small delay for visual feedback

            self._set_progress(100, "Installation abgeschlossen ✓")
            self._log("")
            ip = get_primary_ipv4() or "localhost"
            url = f"http://{ip}:{self.port}/"
            self._log("═" * 50)
            if self.dev_mode:
                self._log("  DEV-MODUS: Simulation abgeschlossen.")
                self._log("  Keine echten Änderungen vorgenommen.")
            else:
                self._log("  Installation erfolgreich!")
                self._log(f"  Installationsverzeichnis: {self.install_dir}")
                self._log(f"  Datenverzeichnis:         {self.data_dir}")
                self._log(f"  Dienst:                   {SERVICE_NAME}")
                self._log(f"  URL:  {url}")
                self._log("")
                self._log("  DNS-Hinweis für IT / Netzwerkadministrator:")
                self._log(f"    {ip}  →  <wunschname>.ihre-domain.local")
                self._log("  DNS-Eintrag im internen DNS-Server ergänzen,")
                self._log("  damit ein Hostname statt der IP-Adresse")
                self._log("  verwendet werden kann.")
            self._log("═" * 50)
            self._show_result_buttons(True, url if not self.dev_mode else "")

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
        icon = self.install_dir / f"{APP_NAME}.exe"
        logic.create_desktop_shortcut(
            url, self.display_name, icon_path=icon, log=self._log)


# ========================================================
# UNINSTALL PROGRESS SCREEN
# ========================================================
class UninstallProgressWindow(tk.Toplevel):
    """Modal window that reverses all installation steps."""

    def __init__(self, parent: InstallerApp,
                 install_dir: Path, data_dir: Path,
                 keep_data: bool, display_name: str = "Reifenmanager",
                 dev_mode: bool = False):
        super().__init__(parent)
        self.parent_app = parent
        self.install_dir = install_dir
        self.data_dir = data_dir
        self.keep_data = keep_data
        self.display_name = display_name
        self.dev_mode = dev_mode

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
                if self.dev_mode:
                    self._log("   [DEV] Simulation – keine echte Aktion.")
                    time.sleep(0.4)
                else:
                    fn()
                    time.sleep(0.15)

            self._set_progress(100, "Deinstallation abgeschlossen ✓")
            self._log("")
            self._log("═" * 50)
            if self.dev_mode:
                self._log("  DEV-MODUS: Simulation abgeschlossen.")
                self._log("  Keine echten Änderungen vorgenommen.")
            else:
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
# RESTORE-DB PROGRESS WINDOW
# ========================================================
class RestoreProgressWindow(tk.Toplevel):
    """Modal window that restores a backup database."""

    def __init__(self, parent: InstallerApp,
                 install_dir: Path, data_dir: Path,
                 source_db: Path,
                 dev_mode: bool = False):
        super().__init__(parent)
        self.parent_app = parent
        self.install_dir = install_dir
        self.data_dir = data_dir
        self.source_db = source_db
        self.dev_mode = dev_mode

        self.title("Datenbank wird wiederhergestellt …")
        self.geometry("660x340")
        self.resizable(False, False)
        self.configure(bg=BG_DARK)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        self._build()
        self._start_worker()

    def _build(self):
        tk.Label(
            self,
            text="Datenbank wird wiederhergestellt …",
            bg=BG_DARK, fg=FG_TEXT,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=20, pady=(18, 6))

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "restore.Horizontal.TProgressbar",
            troughcolor=BG_CARD,
            background="#7c3aed",
            thickness=22,
        )
        self.progress = ttk.Progressbar(
            self, style="restore.Horizontal.TProgressbar",
            orient="horizontal", length=610,
            mode="indeterminate",
        )
        self.progress.pack(padx=20, pady=(0, 10))
        self.progress.start(15)

        self.step_label = tk.Label(
            self, text="Vorbereitung …", bg=BG_DARK,
            fg="#94a3b8", font=("Segoe UI", 9),
        )
        self.step_label.pack(anchor="w", padx=20)

        self.log_text = tk.Text(
            self, height=10, wrap="word",
            bg="#0f172a", fg="#e2e8f0",
            font=("Consolas", 9),
            relief="flat", borderwidth=0,
        )
        self.log_text.pack(fill="both", expand=True,
                           padx=20, pady=(8, 12))
        self.log_text.configure(state="disabled")

        self.btn_frame = tk.Frame(self, bg=BG_DARK)
        self.btn_frame.pack(fill="x", padx=20, pady=(0, 14))

    def _log(self, line: str):
        self.after(0, self._log_ui, line)

    def _log_ui(self, line: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_step(self, label: str):
        self.after(0, lambda: self.step_label.configure(text=label))

    def _show_result_buttons(self, success: bool):
        self.after(0, self._show_buttons_ui, success)

    def _show_buttons_ui(self, success: bool):
        self.progress.stop()
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
        self.parent_app.btn_restore_db.configure(state="normal")

    def _start_worker(self):
        threading.Thread(
            target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            self._set_step(
                f"Stelle wieder her: {self.source_db.name} …")
            if self.dev_mode:
                self._log(f"[DEV] Simulation: restore_database({self.source_db.name})")
                time.sleep(0.8)
            else:
                logic.restore_database(
                    self.source_db,
                    self.data_dir,
                    self.install_dir,
                    log=self._log,
                )
            self._set_step("Wiederherstellung abgeschlossen ✓")
            self._log("")
            self._log("═" * 50)
            if self.dev_mode:
                self._log("  DEV-MODUS: Simulation abgeschlossen.")
                self._log("  Keine echten Änderungen vorgenommen.")
            else:
                self._log("  Datenbank erfolgreich wiederhergestellt!")
            self._log("═" * 50)
            self._show_result_buttons(True)
        except (ValueError, Exception) as ex:
            self._log(f"\n✗ FEHLER: {ex}")
            self._set_step("Wiederherstellung fehlgeschlagen")
            self._show_result_buttons(False)


# ========================================================
# UPDATE DETAILS DIALOG
# ========================================================
class UpdateDetailsDialog(tk.Toplevel):
    """Modal dialog showing release notes and a download button."""

    def __init__(self, parent: InstallerApp, info: dict):
        super().__init__(parent)
        rv = info.get("remote_version", "?")
        cv = info.get("current_version", "?")
        self.title(f"Version {rv} – Änderungsprotokoll")
        self.geometry("680x540")
        self.resizable(True, True)
        self.configure(bg=BG_DARK)
        self.transient(parent)
        self.grab_set()

        # Header
        hdr = tk.Frame(self, bg=BG_UPDATE, height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text=f"  Version {rv} verfügbar  (aktuell: {cv})",
            bg=BG_UPDATE, fg="white",
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left", padx=12, pady=10)

        # Data preservation note
        note = tk.Frame(self, bg="#1e3a5f", pady=6)
        note.pack(fill="x")
        tk.Label(
            note,
            text="ℹ  Alle Ihre Daten (Datenbank, Backups, Logs, Einstellungen)"
                 " werden beim Update vollständig beibehalten.",
            bg="#1e3a5f", fg="#93c5fd",
            font=("Segoe UI", 9),
            wraplength=660, justify="left",
        ).pack(padx=12, pady=2)

        # Release notes – prefer the parsed CHANGELOG section (rich content),
        # fall back to the GitHub release body (often a stub).
        raw_notes = (
            info.get("changelog_section")
            or info.get("release_notes")
            or ""
        ).strip()
        notes_sparse = len(raw_notes) < _UPDATE_NOTES_STUB_THRESHOLD

        tk.Label(
            self, text="Änderungsprotokoll:",
            bg=BG_DARK, fg="#94a3b8", font=("Segoe UI", 9),
        ).pack(anchor="w", padx=14, pady=(10, 2))

        notes_frame = tk.Frame(self, bg=BG_DARK)
        notes_frame.pack(fill="both", expand=True, padx=14, pady=(0, 4))

        scrollbar = tk.Scrollbar(notes_frame)
        scrollbar.pack(side="right", fill="y")

        notes_text = tk.Text(
            notes_frame, wrap="word",
            bg="#0f172a", fg="#e2e8f0",
            font=("Consolas", 9),
            relief="flat", borderwidth=0,
            yscrollcommand=scrollbar.set,
        )
        notes_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=notes_text.yview)

        if raw_notes:
            notes_text.insert("1.0", raw_notes)
        else:
            notes_text.insert("1.0", "(Keine Beschreibung für diese Version verfügbar.)")
        notes_text.configure(state="disabled")

        # When notes are sparse, add a hint row pointing to external resources.
        if notes_sparse:
            hint = tk.Frame(self, bg="#1e293b")
            hint.pack(fill="x", padx=0, pady=0)
            tk.Label(
                hint,
                text="  Die Release-Beschreibung ist kurz. "
                     "Vollständige Änderungen:",
                bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 9),
            ).pack(side="left", padx=12, pady=4)
            owner = "tombo92"
            repo = "TireStorageManager"
            commits_url = (
                f"https://github.com/{owner}/{repo}/commits/master"
            )
            changelog_url = (
                f"https://github.com/{owner}/{repo}/blob/master/CHANGELOG.md"
            )
            tk.Button(
                hint, text="Commit-Historie",
                font=("Segoe UI", 9), bg="#334155", fg="white",
                relief="flat",
                command=lambda: open_url(commits_url),
            ).pack(side="right", padx=4, pady=3)
            tk.Button(
                hint, text="CHANGELOG.md",
                font=("Segoe UI", 9), bg="#334155", fg="white",
                relief="flat",
                command=lambda: open_url(changelog_url),
            ).pack(side="right", padx=4, pady=3)

        # Buttons
        bar = tk.Frame(self, bg=BG_DARK)
        bar.pack(fill="x", padx=14, pady=(4, 14))

        release_url = info.get("release_url")
        if release_url:
            tk.Button(
                bar, text="  GitHub Release öffnen  ",
                font=("Segoe UI", 9),
                bg=ACCENT, fg="white", relief="flat",
                command=lambda: open_url(release_url),
            ).pack(side="left")

        installer_url = info.get("installer_url")
        if installer_url or parent.dev_mode:
            tk.Button(
                bar, text="  Neuen Installer laden & starten  ",
                font=("Segoe UI", 10, "bold"),
                bg=SUCCESS, fg="white", relief="flat",
                command=lambda: [
                    self.destroy(),
                    parent._on_do_update(info),
                ],
            ).pack(side="right", padx=(8, 0))

        tk.Button(
            bar, text="  Schließen  ",
            font=("Segoe UI", 9),
            bg="#64748b", fg="white", relief="flat",
            command=self.destroy,
        ).pack(side="right")


# ========================================================
# UPDATE DOWNLOAD WINDOW
# ========================================================
class UpdateDownloadWindow(tk.Toplevel):
    """Modal window that downloads the new installer EXE and launches it."""

    def __init__(self, parent: InstallerApp, url: str, info: dict):
        super().__init__(parent)
        self.parent_app = parent
        self.url = url
        self.info = info

        rv = info.get("remote_version", "?")
        self.title(f"Version {rv} wird heruntergeladen …")
        self.geometry("520x220")
        self.resizable(False, False)
        self.configure(bg=BG_DARK)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # block close

        self._build()
        self._start_download()

    def _build(self):
        rv = self.info.get("remote_version", "?")
        tk.Label(
            self, text=f"Neue Installer-Version {rv} wird heruntergeladen …",
            bg=BG_DARK, fg=FG_TEXT,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=20, pady=(18, 6))

        tk.Label(
            self,
            text="Ihre Daten (DB, Backups, Logs) werden nicht verändert.",
            bg=BG_DARK, fg="#94a3b8", font=("Segoe UI", 9),
        ).pack(anchor="w", padx=20)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "dl.Horizontal.TProgressbar",
            troughcolor=BG_CARD, background=SUCCESS, thickness=18,
        )
        self.progress = ttk.Progressbar(
            self, style="dl.Horizontal.TProgressbar",
            orient="horizontal", length=470,
            mode="indeterminate",
        )
        self.progress.pack(padx=20, pady=(12, 6))
        self.progress.start(12)

        self.status_label = tk.Label(
            self, text="Verbindung wird hergestellt …",
            bg=BG_DARK, fg="#94a3b8", font=("Segoe UI", 9),
        )
        self.status_label.pack(anchor="w", padx=20)

        self.btn_frame = tk.Frame(self, bg=BG_DARK)
        self.btn_frame.pack(fill="x", padx=20, pady=(10, 14))

    def _set_status(self, text: str):
        self.after(0, lambda: self.status_label.configure(text=text))

    def _start_download(self):
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        import tempfile
        rv = self.info.get("remote_version", "new")
        dest = Path(tempfile.gettempdir()) / f"TSM-Installer-{rv}.exe"

        def _progress(received: int, total: int) -> None:
            if total > 0:
                mb_r = received / 1_048_576
                mb_t = total / 1_048_576
                self._set_status(
                    f"Heruntergeladen: {mb_r:.1f} MB / {mb_t:.1f} MB")
            else:
                mb_r = received / 1_048_576
                self._set_status(f"Heruntergeladen: {mb_r:.1f} MB …")

        self._set_status("Herunterladen …")
        ok = logic.download_file(self.url, dest, on_progress=_progress)

        if not ok:
            self.after(0, self._on_download_failed)
            return

        self._set_status(f"Download abgeschlossen: {dest.name}")
        self.after(0, self._on_download_done, dest)

    def _on_download_failed(self):
        self.progress.stop()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.status_label.configure(
            text="Download fehlgeschlagen – bitte manuell herunterladen.")
        release_url = self.info.get("release_url", "")
        if release_url:
            tk.Button(
                self.btn_frame, text="  GitHub Release öffnen  ",
                font=("Segoe UI", 9),
                bg=ACCENT, fg="white", relief="flat",
                command=lambda: open_url(release_url),
            ).pack(side="left")
        tk.Button(
            self.btn_frame, text="  Schließen  ",
            font=("Segoe UI", 9),
            bg="#64748b", fg="white", relief="flat",
            command=self.destroy,
        ).pack(side="right")

    def _on_download_done(self, dest: Path):
        self.progress.stop()
        self.status_label.configure(
            text="Installer wird gestartet – dieses Fenster schließt sich.")
        # Launch new installer elevated, then close the current one.
        open_url(str(dest))   # ShellExecuteW "open" triggers UAC elevation
        self.after(1500, self.parent_app.destroy)


# ========================================================
# ENTRY POINT
# ========================================================
def _run_headless(args: argparse.Namespace) -> int:
    """Install, uninstall, or check for updates without a GUI.

    Returns 0 on success, 1 on failure.
    Used by CI smoke tests to verify the compiled EXE end-to-end.
    """
    log_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg, flush=True)
        log_lines.append(msg)

    # check-update does not need install_dir / data_dir
    if args.action == "check-update":
        try:
            from config import VERSION  # type: ignore[import]
        except Exception:
            VERSION = "0.0.0"
        info = logic.fetch_update_info(VERSION)
        print(json.dumps(info, ensure_ascii=False), flush=True)
        return 0

    install_dir = Path(args.install_dir).resolve()
    data_dir = Path(args.data_dir).resolve()

    if args.action == "install":
        port = logic.validate_port(str(args.port))
        display_name = logic.resolve_display_name(args.display_name or "")

        nssm_src = resource_path(PAYLOAD_NSSM)
        app_src = resource_path(PAYLOAD_APP)
        seed_db = resource_path(PAYLOAD_SEED_DB)
        try:
            logic.create_directories(
                install_dir, data_dir, log=log)
            nssm = logic.deploy_nssm(
                nssm_src, install_dir, log=log)
            app_exe = logic.deploy_app_exe(
                app_src, install_dir, log=log)
            logic.seed_database(
                seed_db, data_dir, log=log)
            logic.add_firewall_rule(port, log=log)
            logic.install_service(
                nssm, app_exe, data_dir, port,
                install_dir,
                display_name=display_name,
                log=log)
            logic.start_service(nssm, log=log)
            logic.create_update_task(log=log)
            if args.shortcut:
                ip = get_primary_ipv4() or "localhost"
                url = f"http://{ip}:{port}/"
                logic.create_desktop_shortcut(
                    url, display_name,
                    icon_path=install_dir / f"{APP_NAME}.exe",
                    log=log)
        except Exception as exc:
            print(f"✗ FEHLER: {exc}", flush=True)
            return 1
        return 0

    if args.action == "uninstall":
        port = logic.validate_port(str(args.port))
        display_name = logic.resolve_display_name(
            args.display_name or "")
        try:
            logic.stop_service(install_dir, log=log)
            logic.remove_service(install_dir, log=log)
            logic.remove_scheduled_task(log=log)
            logic.remove_firewall_rules(extra_port=port, log=log)
            logic.remove_desktop_shortcut(display_name, log=log)
            if not args.keep_data:
                logic.remove_data_dir(data_dir, log=log)
            logic.remove_install_dir(install_dir, log=log)
        except Exception as exc:
            print(f"✗ FEHLER: {exc}", flush=True)
            return 1
        return 0

    if args.action == "restore-db":
        source_db = Path(args.source_db).resolve()
        try:
            logic.restore_database(
                source_db, data_dir, install_dir, log=log)
        except (ValueError, RuntimeError) as exc:
            print(f"✗ FEHLER: {exc}", flush=True)
            return 1
        return 0

    print(f"Unknown action: {args.action}", flush=True)
    return 1


def main():
    # In headless mode the EXE writes to a pipe whose codec defaults to
    # cp1252 on Windows.  Reconfigure to UTF-8 before any print() call
    # so the Unicode log characters (✓ ✗ ℹ …) don't crash the process.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="TSM-Installer",
        description="TireStorageManager Installer/Uninstaller",
        add_help=True,
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run without GUI (for CI smoke tests).",
    )
    parser.add_argument(
        "--ui-dev", dest="ui_dev", action="store_true",
        help=(
            "Launch the GUI in UI-dev mode: all install/uninstall steps are "
            "simulated (no real OS actions).  Use to preview the full UI flow "
            "without administrator rights or a real installation target."
        ),
    )
    parser.add_argument(
        "--action",
        choices=["install", "uninstall", "restore-db", "check-update"],
        help="Action to perform in headless mode.",
    )
    parser.add_argument(
        "--install-dir", dest="install_dir",
        help="Installation directory.",
    )
    parser.add_argument(
        "--data-dir", dest="data_dir",
        help="Data directory.",
    )
    parser.add_argument(
        "--source-db", dest="source_db",
        help="Source DB file for restore-db action.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"HTTP port (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--display-name", dest="display_name",
        default="", help="Windows Service display name.",
    )
    parser.add_argument(
        "--shortcut", action="store_true",
        help="Create desktop shortcut (install only).",
    )
    parser.add_argument(
        "--keep-data", dest="keep_data", action="store_true",
        help="Keep data directory on uninstall.",
    )
    parser.add_argument(
        "--version", action="store_true",
        help="Print version and exit.",
    )

    # parse_known_args so PyInstaller's bootloader args don't cause errors
    args, _ = parser.parse_known_args()

    if args.version:
        try:
            from config import VERSION  # type: ignore[import]
            print(VERSION, flush=True)
        except Exception:
            print("unknown", flush=True)
        return

    if args.headless:
        if not args.action:
            parser.error(
                "--headless requires --action install|uninstall|restore-db|check-update")
        if args.action in ("install", "uninstall"):
            if not args.install_dir or not args.data_dir:
                parser.error(
                    "--headless requires --install-dir and --data-dir")
        if args.action == "restore-db":
            if not args.data_dir or not args.install_dir:
                parser.error(
                    "restore-db requires --install-dir and --data-dir")
            if not args.source_db:
                parser.error(
                    "restore-db requires --source-db")
        sys.exit(_run_headless(args))

    # Normal GUI mode
    app = InstallerApp(dev_mode=getattr(args, "ui_dev", False))
    app.mainloop()


if __name__ == "__main__":
    main()
