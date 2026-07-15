#!/usr/bin/env python
"""
installer_i18n.py – Verbose help content for the TSM Installer/Uninstaller.

Pure Python (no Tkinter imports) so it can be unit-tested on any platform,
including headless Linux CI runners, without stubbing a display.

Supported languages: de (default), en.
Content is organised into sections, each with a list of items
(title + detailed body). The Tkinter UI renders this via HelpWindow.
"""
from __future__ import annotations

# ── Supported languages ────────────────────────────────────────────────────
SUPPORTED_LANGS: tuple[str, ...] = ("de", "en")
DEFAULT_LANG: str = "de"

LANG_LABELS: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}


def resolve_lang(lang: str | None) -> str:
    """Return *lang* if supported, else :data:`DEFAULT_LANG`."""
    if lang in SUPPORTED_LANGS:
        return lang
    return DEFAULT_LANG


# ── Content catalogue ───────────────────────────────────────────────────────
# Each section: {"id": str, "title": {lang: str}, "items": [item, ...]}
# Each item:    {"title": {lang: str}, "body": {lang: str}}
HELP_SECTIONS: list[dict] = [
    {
        "id": "fields",
        "title": {
            "de": "Eingabefelder",
            "en": "Input Fields",
        },
        "items": [
            {
                "title": {
                    "de": "Installationsverzeichnis",
                    "en": "Installation Directory",
                },
                "body": {
                    "de": (
                        "Ordner, in dem die Programmdatei "
                        "(TireStorageManager.exe) und der Dienst-Manager "
                        "(nssm.exe) abgelegt werden. Standard: "
                        "'Program Files\\TireStorageManager'. Dieser Ordner "
                        "enthält keine Nutzdaten und kann bei einer "
                        "Deinstallation gefahrlos gelöscht werden."
                    ),
                    "en": (
                        "Folder where the application executable "
                        "(TireStorageManager.exe) and the service manager "
                        "(nssm.exe) are placed. Default: "
                        "'Program Files\\TireStorageManager'. This folder "
                        "contains no user data and can be safely removed "
                        "during uninstallation."
                    ),
                },
            },
            {
                "title": {
                    "de": "Datenverzeichnis",
                    "en": "Data Directory",
                },
                "body": {
                    "de": (
                        "Ordner für Datenbank, Backups und Logdateien. "
                        "Standard: 'ProgramData\\TireStorageManager'. "
                        "WICHTIG: Bei einer Aktualisierung muss dieses Feld "
                        "unverändert bleiben, damit die vorhandene "
                        "Datenbank mit allen Kundendaten weiterverwendet "
                        "wird. Der Installer merkt sich diesen Pfad "
                        "zwischen Sitzungen automatisch (Registrierung)."
                    ),
                    "en": (
                        "Folder for the database, backups, and log files. "
                        "Default: 'ProgramData\\TireStorageManager'. "
                        "IMPORTANT: When upgrading, this field must stay "
                        "unchanged so the existing database with all "
                        "customer data continues to be used. The installer "
                        "remembers this path automatically between "
                        "sessions (Windows Registry)."
                    ),
                },
            },
            {
                "title": {
                    "de": "HTTP Port",
                    "en": "HTTP Port",
                },
                "body": {
                    "de": (
                        "TCP-Port, auf dem der Webserver erreichbar ist "
                        "(Standard: 5000). Ändern Sie diesen Wert nur, wenn "
                        "der Port bereits von einer anderen Anwendung "
                        "belegt ist. Eine passende Firewall-Regel wird "
                        "automatisch für den gewählten Port erstellt."
                    ),
                    "en": (
                        "TCP port on which the web server is reachable "
                        "(default: 5000). Only change this if the port is "
                        "already used by another application. A matching "
                        "firewall rule is created automatically for the "
                        "chosen port."
                    ),
                },
            },
            {
                "title": {
                    "de": "Programmtitel",
                    "en": "Application Title",
                },
                "body": {
                    "de": (
                        "Frei wählbarer Name, der in der Weboberfläche und "
                        "als Dienstname (Anzeigename) angezeigt wird "
                        "(Standard: 'Reifenmanager'). Rein kosmetisch — "
                        "hat keinen Einfluss auf Datenbank oder Funktion."
                    ),
                    "en": (
                        "Freely chosen name shown in the web interface and "
                        "as the service display name (default: "
                        "'Reifenmanager'). Purely cosmetic — has no effect "
                        "on the database or functionality."
                    ),
                },
            },
            {
                "title": {
                    "de": "Geheimer Schlüssel",
                    "en": "Secret Key",
                },
                "body": {
                    "de": (
                        "Optionaler Schlüssel zur Absicherung der "
                        "Web-Sitzungen (Flask Session Secret). Leer lassen, "
                        "um den Standardschlüssel zu verwenden. Aus "
                        "Sicherheitsgründen wird ein vorhandener "
                        "Schlüssel NIE aus der Registrierung geladen oder "
                        "angezeigt — bei einer Aktualisierung muss er bei "
                        "Bedarf erneut eingegeben werden. Wird das Feld "
                        "leer gelassen, bleibt der zuvor gesetzte "
                        "Schlüssel auf dem Zielsystem unverändert, sofern "
                        "die Umgebungsvariable nicht überschrieben wird."
                    ),
                    "en": (
                        "Optional key used to secure web sessions (Flask "
                        "session secret). Leave blank to use the default "
                        "key. For security reasons an existing key is "
                        "NEVER loaded from or shown via the registry — "
                        "re-enter it manually when upgrading if you use a "
                        "custom one. Leaving this field blank does not "
                        "reset a previously configured key on the target "
                        "machine unless the environment variable is "
                        "overwritten."
                    ),
                },
            },
            {
                "title": {
                    "de": "Desktop-Verknüpfung",
                    "en": "Desktop Shortcut",
                },
                "body": {
                    "de": (
                        "Erstellt eine .url-Verknüpfung auf dem Desktop "
                        "aller Benutzer, die direkt die Weboberfläche im "
                        "Standardbrowser öffnet."
                    ),
                    "en": (
                        "Creates a .url shortcut on the All Users desktop "
                        "that opens the web interface directly in the "
                        "default browser."
                    ),
                },
            },
        ],
    },
    {
        "id": "install_steps",
        "title": {
            "de": "Installationsschritte (in dieser Reihenfolge)",
            "en": "Installation Steps (in this order)",
        },
        "items": [
            {
                "title": {
                    "de": "1. Verzeichnisse anlegen",
                    "en": "1. Create directories",
                },
                "body": {
                    "de": (
                        "Installations- und Datenverzeichnis werden "
                        "angelegt, falls sie noch nicht existieren."
                    ),
                    "en": (
                        "The installation and data directories are "
                        "created if they do not already exist."
                    ),
                },
            },
            {
                "title": {
                    "de": "2. NSSM bereitstellen",
                    "en": "2. Deploy NSSM",
                },
                "body": {
                    "de": (
                        "'nssm.exe' (Non-Sucking Service Manager) wird in "
                        "das Installationsverzeichnis kopiert. NSSM "
                        "registriert die Anwendung als Windows-Dienst, "
                        "damit sie ohne angemeldeten Benutzer im "
                        "Hintergrund läuft und automatisch startet."
                    ),
                    "en": (
                        "'nssm.exe' (Non-Sucking Service Manager) is "
                        "copied into the installation directory. NSSM "
                        "registers the application as a Windows service so "
                        "it runs in the background without a logged-in "
                        "user and starts automatically."
                    ),
                },
            },
            {
                "title": {
                    "de": "3. Anwendung kopieren",
                    "en": "3. Copy application",
                },
                "body": {
                    "de": (
                        "'TireStorageManager.exe' wird in das "
                        "Installationsverzeichnis kopiert. Läuft bereits "
                        "ein Dienst einer vorherigen Installation, wird "
                        "dieser zuerst gestoppt, damit die Datei nicht "
                        "durch Windows gesperrt ist."
                    ),
                    "en": (
                        "'TireStorageManager.exe' is copied into the "
                        "installation directory. If a service from a "
                        "previous installation is still running, it is "
                        "stopped first so the file is not locked by "
                        "Windows."
                    ),
                },
            },
            {
                "title": {
                    "de": "4. Datenbank vorbereiten",
                    "en": "4. Prepare database",
                },
                "body": {
                    "de": (
                        "Existiert im Datenverzeichnis noch keine "
                        "Datenbank ('wheel_storage.db'), wird eine leere "
                        "Vorlage angelegt. WICHTIG: Ist bereits eine "
                        "Datenbank vorhanden (z. B. bei einer "
                        "Aktualisierung), wird diese NIE überschrieben — "
                        "alle Kundendaten, Radsätze und Einstellungen "
                        "bleiben vollständig erhalten. Fehlende "
                        "Tabellen/Spalten neuerer Programmversionen werden "
                        "beim ersten Start automatisch ergänzt "
                        "(Schema-Migration)."
                    ),
                    "en": (
                        "If no database exists yet in the data directory "
                        "('wheel_storage.db'), an empty template is "
                        "created. IMPORTANT: If a database already exists "
                        "(e.g. during an upgrade), it is NEVER "
                        "overwritten — all customer data, wheel sets, and "
                        "settings remain fully intact. Any tables/columns "
                        "missing from a newer program version are added "
                        "automatically on first start (schema migration)."
                    ),
                },
            },
            {
                "title": {
                    "de": "5. Firewall-Regel erstellen",
                    "en": "5. Create firewall rule",
                },
                "body": {
                    "de": (
                        "Eine eingehende Windows-Firewall-Regel für den "
                        "gewählten TCP-Port wird angelegt, damit andere "
                        "Geräte im Netzwerk auf die Weboberfläche zugreifen "
                        "können. Existiert die Regel bereits, wird dies "
                        "übersprungen."
                    ),
                    "en": (
                        "An inbound Windows Firewall rule for the chosen "
                        "TCP port is created so other devices on the "
                        "network can access the web interface. If the "
                        "rule already exists, this step is skipped."
                    ),
                },
            },
            {
                "title": {
                    "de": "6. Windows-Dienst installieren",
                    "en": "6. Install Windows service",
                },
                "body": {
                    "de": (
                        "Die Anwendung wird über NSSM als Windows-Dienst "
                        "mit automatischem Start registriert. Ein "
                        "eventuell vorhandener Dienst gleichen Namens wird "
                        "zuvor entfernt und neu angelegt, damit alle "
                        "Einstellungen (Port, Datenverzeichnis, Titel) "
                        "aktuell sind."
                    ),
                    "en": (
                        "The application is registered as a Windows "
                        "service with automatic startup via NSSM. Any "
                        "existing service of the same name is removed "
                        "first and re-created so all settings (port, data "
                        "directory, title) are up to date."
                    ),
                },
            },
            {
                "title": {
                    "de": "7. Dienst starten",
                    "en": "7. Start service",
                },
                "body": {
                    "de": (
                        "Der Windows-Dienst wird sofort gestartet, sodass "
                        "die Weboberfläche direkt nach der Installation "
                        "erreichbar ist."
                    ),
                    "en": (
                        "The Windows service is started immediately so the "
                        "web interface is reachable right after "
                        "installation."
                    ),
                },
            },
            {
                "title": {
                    "de": "8. Tägliches Update einrichten",
                    "en": "8. Set up daily restart task",
                },
                "body": {
                    "de": (
                        "Eine geplante Aufgabe wird angelegt, die den "
                        "Dienst täglich um 03:00 Uhr neu startet. Dies "
                        "hält den Dienst gesund (z. B. nach seltenen "
                        "Speicherlecks) und ist unabhängig vom "
                        "automatischen Selbst-Update der Anwendung."
                    ),
                    "en": (
                        "A scheduled task is created that restarts the "
                        "service daily at 03:00. This keeps the service "
                        "healthy (e.g. after rare memory leaks) and is "
                        "independent from the application's automatic "
                        "self-update."
                    ),
                },
            },
            {
                "title": {
                    "de": "9. Desktop-Verknüpfung erstellen (optional)",
                    "en": "9. Create desktop shortcut (optional)",
                },
                "body": {
                    "de": (
                        "Nur wenn die Option aktiviert ist: Eine "
                        "Verknüpfung zur Weboberfläche wird auf dem "
                        "Desktop aller Benutzer abgelegt."
                    ),
                    "en": (
                        "Only if the option is enabled: a shortcut to the "
                        "web interface is placed on the All Users desktop."
                    ),
                },
            },
        ],
    },
    {
        "id": "upgrade",
        "title": {
            "de": "Aktualisierung einer bestehenden Installation",
            "en": "Upgrading an Existing Installation",
        },
        "items": [
            {
                "title": {
                    "de": "Was passiert bei einer erneuten Installation?",
                    "en": "What happens when installing again?",
                },
                "body": {
                    "de": (
                        "Der Installer erkennt automatisch, wenn der "
                        "Dienst bereits registriert ist, und fragt vor dem "
                        "Fortfahren nach. Verwenden Sie exakt dieselben "
                        "Verzeichnisse wie beim ersten Mal (werden aus der "
                        "Registrierung vorbelegt) — dann läuft die "
                        "Aktualisierung wie folgt ab: Der alte Dienst wird "
                        "gestoppt, die Programmdatei ersetzt, die "
                        "bestehende Datenbank unverändert weiterverwendet, "
                        "der Dienst neu registriert und sofort wieder "
                        "gestartet. Kundendaten, Radsätze, Backups und "
                        "Logs bleiben während des gesamten Vorgangs "
                        "vollständig erhalten."
                    ),
                    "en": (
                        "The installer automatically detects that the "
                        "service is already registered and asks for "
                        "confirmation before proceeding. Use exactly the "
                        "same directories as the first time (pre-filled "
                        "from the registry) — the upgrade then proceeds "
                        "as follows: the old service is stopped, the "
                        "program file is replaced, the existing database "
                        "continues to be used unchanged, the service is "
                        "re-registered, and immediately restarted. "
                        "Customer data, wheel sets, backups, and logs "
                        "remain fully intact throughout the process."
                    ),
                },
            },
        ],
    },
    {
        "id": "restore_db",
        "title": {
            "de": "Datenbank wiederherstellen",
            "en": "Restore Database",
        },
        "items": [
            {
                "title": {
                    "de": "Wann verwenden?",
                    "en": "When to use it?",
                },
                "body": {
                    "de": (
                        "Zum Zurückspielen einer Sicherungsdatei (z. B. "
                        "nach einem Fehler oder um zu einem früheren Stand "
                        "zurückzukehren). Wählen Sie eine .db-Datei aus "
                        "dem Backup-Ordner aus. Die Datei wird zunächst "
                        "geprüft (gültige SQLite-Datenbank mit den "
                        "erforderlichen Tabellen/Spalten); ungültige "
                        "Dateien werden abgelehnt, ohne die aktuelle "
                        "Datenbank zu verändern. Anschließend wird der "
                        "Dienst gestoppt, die aktuelle Datenbank mit "
                        "Zeitstempel gesichert, die ausgewählte Datei "
                        "eingespielt und der Dienst neu gestartet."
                    ),
                    "en": (
                        "Use this to restore a backup file (e.g. after an "
                        "error, or to revert to an earlier state). Select "
                        "a .db file from the backups folder. The file is "
                        "first validated (a proper SQLite database with "
                        "the required tables/columns); invalid files are "
                        "rejected without touching the current database. "
                        "The service is then stopped, the current "
                        "database is backed up with a timestamp, the "
                        "selected file is copied into place, and the "
                        "service is restarted."
                    ),
                },
            },
        ],
    },
    {
        "id": "uninstall_steps",
        "title": {
            "de": "Deinstallationsschritte",
            "en": "Uninstallation Steps",
        },
        "items": [
            {
                "title": {
                    "de": "Ablauf",
                    "en": "Sequence",
                },
                "body": {
                    "de": (
                        "1. Dienst stoppen  2. Dienst entfernen  "
                        "3. geplante Aufgabe entfernen  4. Firewall-Regel "
                        "entfernen  5. Installationsverzeichnis löschen "
                        "(Programmdatei + NSSM)  6. Datenverzeichnis "
                        "optional löschen. Wird 'Daten behalten' "
                        "ausgewählt, bleiben Datenbank, Backups und Logs "
                        "vollständig erhalten und können durch eine "
                        "spätere Neuinstallation mit demselben "
                        "Datenverzeichnis wiederverwendet werden."
                    ),
                    "en": (
                        "1. Stop the service  2. Remove the service  "
                        "3. Remove the scheduled task  4. Remove the "
                        "firewall rule  5. Delete the installation "
                        "directory (program file + NSSM)  6. Optionally "
                        "delete the data directory. If 'Keep data' is "
                        "selected, the database, backups, and logs remain "
                        "fully intact and can be reused by a later "
                        "re-installation using the same data directory."
                    ),
                },
            },
        ],
    },
]


def get_help_sections(lang: str | None = None) -> list[dict]:
    """Return the help content rendered for *lang* (falls back to German).

    Returns a list of ``{"heading": str, "items": [{"title": str,
    "body": str}, ...]}`` dicts, ready for direct display.
    """
    resolved = resolve_lang(lang)
    rendered: list[dict] = []
    for section in HELP_SECTIONS:
        rendered.append({
            "id": section["id"],
            "heading": section["title"].get(resolved, section["title"][DEFAULT_LANG]),
            "items": [
                {
                    "title": item["title"].get(resolved, item["title"][DEFAULT_LANG]),
                    "body": item["body"].get(resolved, item["body"][DEFAULT_LANG]),
                }
                for item in section["items"]
            ],
        })
    return rendered


def get_full_help_text(lang: str | None = None) -> str:
    """Return the entire help content as one formatted plain-text block."""
    sections = get_help_sections(lang)
    lines: list[str] = []
    for section in sections:
        lines.append(section["heading"].upper())
        lines.append("=" * len(section["heading"]))
        lines.append("")
        for item in section["items"]:
            lines.append(item["title"])
            lines.append("-" * len(item["title"]))
            lines.append(item["body"])
            lines.append("")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
