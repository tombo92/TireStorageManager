#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Lightweight i18n for TireStorageManager.

Supported locales: de (default), en.
Translations are plain Python dicts — no .po/.mo compilation needed,
works transparently inside a PyInstaller bundle.

Usage in Python:
    from tsm.i18n import gettext as _
    flash(_("settings_saved"))

Usage in Jinja2 templates (injected via context processor):
    {{ _("settings_saved") }}
"""
from __future__ import annotations

from flask import g, has_request_context

# ── Supported locales ─────────────────────────────────────────────────────────
SUPPORTED_LOCALES: list[str] = ["de", "en"]
DEFAULT_LOCALE: str = "de"

# ── Translation catalogue ──────────────────────────────────────────────────────
# Keys are stable identifiers (snake_case).
# Add new keys to BOTH locales to keep them in sync.
_CATALOGUE: dict[str, dict[str, str]] = {
    # ── Navigation ─────────────────────────────────────────────
    "nav_wheelsets":        {"de": "Radsätze",          "en": "Wheel Sets"},
    "nav_positions":        {"de": "Positionen",        "en": "Positions"},
    "nav_backups":          {"de": "Backups",           "en": "Backups"},
    "nav_settings":         {"de": "Einstellungen",     "en": "Settings"},
    "nav_impressum":        {"de": "Impressum",         "en": "Imprint"},
    "search_placeholder":   {"de": "Suche (Name, Kennzeichen, Fahrzeug)",
                             "en": "Search (name, plate, vehicle)"},

    # ── Flash messages ──────────────────────────────────────────
    "fill_required_fields": {
        "de": "Bitte alle Pflichtfelder ausfüllen.",
        "en": "Please fill in all required fields.",
    },
    "invalid_plate": {
        "de": "Ungültiges Kennzeichen. Bitte deutsches Format verwenden, z. B. M AB 1234.",
        "en": "Invalid licence plate. Please use German format, e.g. M AB 1234.",
    },
    "invalid_position": {
        "de": "Ungültige Position.",
        "en": "Invalid position.",
    },
    "position_disabled": {
        "de": "Position ist gesperrt und kann nicht verwendet werden.",
        "en": "Position is disabled and cannot be used.",
    },
    "position_occupied": {
        "de": "Position ist bereits belegt.",
        "en": "Position is already occupied.",
    },
    "position_conflict": {
        "de": "Position bereits belegt oder Datenkonflikt.",
        "en": "Position already occupied or data conflict.",
    },
    "wheelset_created": {
        "de": "Radsatz wurde angelegt.",
        "en": "Wheel set was created.",
    },
    "wheelset_updated": {
        "de": "Radsatz wurde aktualisiert.",
        "en": "Wheel set was updated.",
    },
    "wheelset_deleted": {
        "de": "Radsatz wurde sicher gelöscht.",
        "en": "Wheel set was deleted.",
    },
    "target_position_disabled": {
        "de": "Zielposition ist gesperrt und kann nicht verwendet werden.",
        "en": "Target position is disabled and cannot be used.",
    },
    "data_conflict": {
        "de": "Datenkonflikt beim Speichern.",
        "en": "Data conflict while saving.",
    },
    "confirm_failed": {
        "de": "Bestätigung fehlgeschlagen (Kennzeichen stimmt nicht).",
        "en": "Confirmation failed (licence plate does not match).",
    },
    "settings_saved": {
        "de": "Einstellungen gespeichert.",
        "en": "Settings saved.",
    },
    "settings_error": {
        "de": "Fehler beim Speichern.",
        "en": "Error while saving.",
    },
    "positions_reset": {
        "de": "Positionen auf Standard zurückgesetzt.",
        "en": "Positions reset to defaults.",
    },
    "positions_min_one": {
        "de": "Mindestens eine Position erforderlich.",
        "en": "At least one position is required.",
    },
    "positions_saved": {
        "de": "{n} Positionen gespeichert.",
        "en": "{n} positions saved.",
    },
    "backup_created": {
        "de": "Backup wurde erstellt.",
        "en": "Backup was created.",
    },
    "backup_failed": {
        "de": "Backup fehlgeschlagen: {e}",
        "en": "Backup failed: {e}",
    },
    "csv_created": {
        "de": "CSV-Export wurde erstellt.",
        "en": "CSV export was created.",
    },
    "csv_failed": {
        "de": "CSV-Export fehlgeschlagen: {e}",
        "en": "CSV export failed: {e}",
    },
    "update_exe_only": {
        "de": "Update kann nur in der installierten Version (EXE) durchgeführt werden.",
        "en": "Updates can only be applied in the installed version (EXE).",
    },
    "update_installed": {
        "de": "Update wurde installiert — der Dienst wird neu gestartet.",
        "en": "Update installed — the service will restart.",
    },
    "update_none": {
        "de": "Kein Update verfügbar oder Update fehlgeschlagen.",
        "en": "No update available or update failed.",
    },
    "update_failed": {
        "de": "Update fehlgeschlagen: {e}",
        "en": "Update failed: {e}",
    },

    # ── Settings page labels ────────────────────────────────────
    "settings_title":           {"de": "Einstellungen",         "en": "Settings"},
    "settings_appearance":      {"de": "Erscheinungsbild",      "en": "Appearance"},
    "settings_dark_mode":       {"de": "Dark Mode",             "en": "Dark Mode"},
    "settings_language":        {"de": "Sprache / Language",    "en": "Sprache / Language"},
    "settings_backup":          {"de": "Backup",                "en": "Backup"},
    "settings_backup_interval": {
        "de": "Backup-Intervall (Minuten)",
        "en": "Backup interval (minutes)",
    },
    "settings_backup_copies":   {
        "de": "Anzahl Sicherungskopien",
        "en": "Number of backup copies",
    },
    "settings_save":            {"de": "Speichern",             "en": "Save"},
    "settings_backup_now":      {
        "de": "Backup jetzt erstellen",
        "en": "Create backup now",
    },
    "settings_positions_title": {
        "de": "Lagerplatz-Positionen",
        "en": "Storage Positions",
    },
    "settings_positions_desc": {
        "de": "Positionen komplett anpassen — eigene Positionsnamen vergeben, "
              "Reihenfolge festlegen, oder auf den Standard zurücksetzen.",
        "en": "Fully customise positions — define your own names, set the order, "
              "or reset to defaults.",
    },
    "settings_manage_positions": {
        "de": "Positionen verwalten",
        "en": "Manage positions",
    },
    "settings_updates_title":   {"de": "Updates",               "en": "Updates"},
    "settings_auto_update": {
        "de": "Automatische Updates (03:00 Uhr)",
        "en": "Automatic updates (03:00)",
    },
    "settings_auto_update_hint": {
        "de": "Wenn aktiviert, wird beim Neustart des Dienstes automatisch auf die "
              "neueste Version aktualisiert.",
        "en": "When enabled, the service automatically updates to the latest version "
              "on restart.",
    },
    "settings_current_version": {
        "de": "Aktuelle Version",
        "en": "Current version",
    },
    "settings_available":       {"de": "verfügbar",             "en": "available"},
    "settings_up_to_date":      {"de": "Aktuell",               "en": "Up to date"},
    "settings_check_now":       {"de": "Jetzt prüfen",          "en": "Check now"},
    "settings_update_now": {
        "de": "Jetzt aktualisieren & neustarten",
        "en": "Update now & restart",
    },
    "settings_release_notes":   {"de": "Änderungen:",           "en": "Release notes:"},

    # ── Index page ──────────────────────────────────────────────
    "index_title":              {"de": "Übersicht",             "en": "Overview"},
    "index_total":              {"de": "Gesamt",                "en": "Total"},
    "index_occupied":           {"de": "Belegt",                "en": "Occupied"},
    "index_free":               {"de": "Frei",                  "en": "Free"},
    "index_next_free":          {"de": "Nächste freie Position","en": "Next free position"},
    "index_none":               {"de": "Keine",                 "en": "None"},
    "stats_occupancy":          {"de": "Auslastung",            "en": "Occupancy"},
    "stats_positions":          {"de": "Stellplätze",           "en": "Positions"},
    "stats_recent":             {"de": "Letzte Aktivitäten",    "en": "Recent activity"},
    "stats_no_activity":        {"de": "Noch keine Aktivitäten","en": "No activity yet"},
    "stats_top_cars":           {"de": "Häufigste Fahrzeuge",   "en": "Top vehicles"},
    "stats_no_cars":            {"de": "Noch keine Einträge",   "en": "No entries yet"},
    "stats_action_create":      {"de": "Angelegt",              "en": "Created"},
    "stats_action_update":      {"de": "Geändert",              "en": "Updated"},
    "stats_action_delete":      {"de": "Gelöscht",              "en": "Deleted"},
    "stats_action_backup":      {"de": "Backup",                "en": "Backup"},

    # ── Wheelset list ───────────────────────────────────────────
    "wl_title":         {"de": "Radsätze",              "en": "Wheel Sets"},
    "wl_add":           {"de": "Radsatz anlegen",       "en": "Add wheel set"},
    "wl_customer":      {"de": "Kunde",                 "en": "Customer"},
    "wl_plate":         {"de": "Kennzeichen",           "en": "Licence Plate"},
    "wl_car":           {"de": "Fahrzeug",              "en": "Vehicle"},
    "wl_position":      {"de": "Position",              "en": "Position"},
    "wl_note":          {"de": "Notiz",                 "en": "Note"},
    "wl_updated":       {"de": "Geändert",              "en": "Updated"},
    "wl_actions":       {"de": "Aktionen",              "en": "Actions"},
    "wl_no_results":    {"de": "Keine Radsätze gefunden.", "en": "No wheel sets found."},
    "wl_edit":          {"de": "Bearbeiten",            "en": "Edit"},
    "wl_delete":        {"de": "Löschen",               "en": "Delete"},
    "wl_overdue_hint": {
        "de": "Reifenwechsel überfällig! "
              "Jan–Apr: Sommerreifen sollten bis Dezember abgeholt sein. "
              "Jul–Sep: Winterreifen sollten bis Juni abgeholt sein.",
        "en": "Tyre exchange overdue! "
              "Jan–Apr: summer tyres should have been collected by December. "
              "Jul–Sep: winter tyres should have been collected by June.",
    },

    # ── Wheelset form ───────────────────────────────────────────
    "wf_title_new":     {"de": "Neuer Radsatz",         "en": "New Wheel Set"},
    "wf_title_edit":    {"de": "Radsatz bearbeiten",    "en": "Edit Wheel Set"},
    "wf_customer":      {"de": "Kundenname",            "en": "Customer name"},
    "wf_plate":         {"de": "Kennzeichen",           "en": "Licence plate"},
    "wf_plate_hint": {
        "de": "Format: ORT-KK 1234 — Beispiele: B-TB 3005, LOS-ZE 123, M-AB 1234 H",
        "en": "Format: ORT-KK 1234 — Examples: B-TB 3005, LOS-ZE 123, M-AB 1234 H",
    },
    "wf_plate_invalid": {
        "de": "Ungültiges deutsches Kennzeichen (z. B. B-TB 3005, LOS-ZE 123 H)",
        "en": "Invalid German licence plate (e.g. B-TB 3005, LOS-ZE 123 H)",
    },
    "wf_car":           {"de": "Fahrzeugtyp",           "en": "Vehicle type"},
    "wf_position":      {"de": "Lagerposition",         "en": "Storage position"},
    "wf_note":          {"de": "Notiz (optional)",      "en": "Note (optional)"},
    "wf_save":          {"de": "Speichern",             "en": "Save"},
    "wf_cancel":        {"de": "Abbrechen",             "en": "Cancel"},
    # Extended tire detail fields
    "wf_tire_details_section": {
        "de": "Reifendaten (optional)",
        "en": "Tire details (optional)",
    },
    "wf_tire_manufacturer": {
        "de": "Hersteller",
        "en": "Manufacturer",
    },
    "wf_tire_size": {
        "de": "Größe (z. B. 205/55 R16)",
        "en": "Size (e.g. 205/55 R16)",
    },
    "wf_tire_age": {
        "de": "Alter / DOT (z. B. 2021)",
        "en": "Age / DOT (e.g. 2021)",
    },
    "wf_season": {
        "de": "Saison",
        "en": "Season",
    },
    "wf_season_sommer": {"de": "Sommer",       "en": "Summer"},
    "wf_season_winter": {"de": "Winter",        "en": "Winter"},
    "wf_season_allwetter": {"de": "Allwetter",  "en": "All-season"},
    "wf_rim_type": {
        "de": "Felgenart",
        "en": "Rim type",
    },
    "wf_rim_stahl": {"de": "Stahlfelge",  "en": "Steel rim"},
    "wf_rim_alu":   {"de": "Alufelge",    "en": "Alloy rim"},
    "wf_exchange_note": {
        "de": "Hinweis für nächsten Wechsel (optional)",
        "en": "Note for next exchange (optional)",
    },

    # ── Delete confirmation ──────────────────────────────────────
    "del_title":        {"de": "Radsatz löschen",       "en": "Delete Wheel Set"},
    "del_warning": {
        "de": "Diese Aktion kann nicht rückgängig gemacht werden.",
        "en": "This action cannot be undone.",
    },
    "del_confirm_label": {
        "de": "Kennzeichen zur Bestätigung eingeben:",
        "en": "Enter licence plate to confirm:",
    },
    "del_btn":          {"de": "Endgültig löschen",     "en": "Delete permanently"},
    "del_cancel":       {"de": "Abbrechen",             "en": "Cancel"},

    # ── Positions page ───────────────────────────────────────────
    "pos_title":        {"de": "Lagerplätze",           "en": "Storage Positions"},
    "pos_free":         {"de": "Freie Plätze",          "en": "Free positions"},
    "pos_next":         {"de": "Nächste freie Position","en": "Next free position"},
    "pos_disabled":     {"de": "Gesperrt",              "en": "Disabled"},
    "pos_none_free":    {"de": "Keine freien Plätze",   "en": "No free positions"},

    # ── Backups page ─────────────────────────────────────────────
    "bk_title":         {"de": "Backups",               "en": "Backups"},
    "bk_export_csv":    {"de": "CSV exportieren",       "en": "Export CSV"},
    "bk_name":          {"de": "Dateiname",             "en": "File name"},
    "bk_size":          {"de": "Größe",                 "en": "Size"},
    "bk_date":          {"de": "Datum",                 "en": "Date"},
    "bk_type":          {"de": "Typ",                   "en": "Type"},
    "bk_download":      {"de": "Download",              "en": "Download"},
    "bk_print":         {"de": "Inventur drucken",      "en": "Print Inventory"},
    "bk_files":         {"de": "Dateien",               "en": "Files"},
    "bk_no_backups":    {"de": "Keine Backups vorhanden.", "en": "No backups available."},

    # ── Settings positions page ──────────────────────────────────
    "sp_title":           {"de": "Positionen verwalten",      "en": "Manage Positions"},
    "sp_back":            {"de": "Zurück",                    "en": "Back"},
    "sp_custom_active":   {"de": "Individuelle Positionen aktiv.", "en": "Custom positions active."},
    "sp_custom_desc":     {
        "de": "Es werden benutzerdefinierte Positionen verwendet ({n} Stück).",
        "en": "Custom positions are in use ({n} total).",
    },
    "sp_default_active":  {"de": "Standard-Positionen aktiv.", "en": "Default positions active."},
    "sp_default_desc": {
        "de": "Es werden die vordefinierten Container- und Garagen-Positionen verwendet ({n} Stück).",
        "en": "The predefined container and garage positions are in use ({n} total).",
    },
    "sp_editor_title":    {"de": "Positionsliste bearbeiten",  "en": "Edit Position List"},
    "sp_editor_hint": {
        "de": "Eine Position pro Zeile. Die Reihenfolge hier bestimmt die Sortierung überall in der Anwendung.",
        "en": "One position per line. The order here determines the sort order throughout the application.",
    },
    "sp_save":            {"de": "Positionen speichern",       "en": "Save positions"},
    "sp_sort":            {"de": "Alphabetisch sortieren",     "en": "Sort alphabetically"},
    "sp_reset_title":     {"de": "Zurücksetzen",               "en": "Reset"},
    "sp_reset_desc": {
        "de": "Setzt alle Positionen auf die vordefinierten Container + Garagen-Positionen zurück.",
        "en": "Resets all positions to the predefined container and garage defaults.",
    },
    "sp_reset_confirm": {
        "de": "Wirklich auf Standard zurücksetzen? Eigene Positionen gehen verloren.",
        "en": "Really reset to defaults? Custom positions will be lost.",
    },
    "sp_reset_btn":       {"de": "Auf Standard zurücksetzen", "en": "Reset to defaults"},
    "sp_tips_title":      {"de": "Tipps",                      "en": "Tips"},
    "sp_tip1":            {"de": "Jede Zeile = eine Position", "en": "One line = one position"},
    "sp_tip2":            {"de": "Leere Zeilen werden ignoriert", "en": "Empty lines are ignored"},
    "sp_tip3":            {
        "de": "Die Reihenfolge bestimmt die Vorschlagspriorität",
        "en": "The order determines suggestion priority",
    },
    "sp_tip4": {
        "de": "Bestehende Radsätze behalten ihre Position auch wenn sie hier entfernt wird",
        "en": "Existing wheel sets keep their position even if removed here",
    },

    # ── Splash / idle ─────────────────────────────────────────────
    "splash_loading":   {"de": "Datenbank wird geladen …", "en": "Loading database …"},

    # ── Tire details / seasonal settings ─────────────────────────
    "settings_tire_details_title": {
        "de": "Erweiterte Reifendaten",
        "en": "Extended Tire Details",
    },
    "settings_enable_tire_details": {
        "de": "Erweiterte Reifendaten erfassen",
        "en": "Capture extended tire details",
    },
    "settings_enable_tire_details_hint": {
        "de": "Aktiviert zusätzliche Felder: Reifentyp (Hersteller, Größe, "
              "Alter), Saison, Felgenart und Wechselhinweis.",
        "en": "Enables additional fields: tyre type (manufacturer, size, "
              "age), season, rim type and exchange note.",
    },
    "settings_enable_seasonal_tracking": {
        "de": "Saisonale Radverwaltung",
        "en": "Seasonal wheel tracking",
    },
    "settings_enable_seasonal_tracking_hint": {
        "de": "Erlaubt mehrere Radsätze pro Kunde und erfasst "
              "Rad-Wechsel mit Historie und Statistiken. "
              "Erfordert 'Erweiterte Reifendaten'.",
        "en": "Allows multiple wheel sets per customer and tracks "
              "wheel exchanges with history and stats. "
              "Requires 'Extended Tire Details'.",
    },
    "idle_hint": {
        "de": "Maus bewegen oder Taste drücken zum Fortfahren …",
        "en": "Move the mouse or press a key to continue …",
    },

    # ── Update banner ─────────────────────────────────────────────
    "banner_new_version":   {"de": "Neue Version",          "en": "New version"},
    "banner_available":     {"de": "verfügbar!",            "en": "available!"},
    "banner_release_page":  {"de": "Release-Seite",         "en": "Release page"},
    "banner_to_settings":   {"de": "Einstellungen",         "en": "Settings"},
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_locale() -> str:
    """Return the active locale for the current request (falls back to default)."""
    if has_request_context():
        locale = getattr(g, "_tsm_locale", None)
        if locale in SUPPORTED_LOCALES:
            return locale
    return DEFAULT_LOCALE


def gettext(key: str, **kwargs) -> str:
    """Translate *key* into the current locale.

    Supports simple ``{placeholder}`` substitution via kwargs:
        gettext("positions_saved", n=5)
    """
    locale = get_locale()
    entry = _CATALOGUE.get(key)
    if entry is None:
        return key  # unknown key — return as-is so nothing breaks
    text = entry.get(locale) or entry.get(DEFAULT_LOCALE) or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text


# Convenient alias matching Flask-Babel / standard gettext convention
_ = gettext
