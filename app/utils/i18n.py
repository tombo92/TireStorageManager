from enum import Enum

class Language(str, Enum):
    EN = "en"
    DE = "de"

# Enum for seasons
class SeasonEnum(str, Enum):
    WINTER = "winter"
    SUMMER = "summer"
    ALLSEASON = "allseason"

# Translation dictionary
TRANSLATIONS = {
    "title": {"en": "Tire Storage Manager", "de": "Reifenlager Manager"},
    "search": {"en": "Search:", "de": "Suche:"},
    "find": {"en": "Find", "de": "Suchen"},
    "add": {"en": "Add", "de": "Hinzufügen"},
    "edit": {"en": "Edit", "de": "Bearbeiten"},
    "delete": {"en": "Delete", "de": "Löschen"},
    "import_excel": {"en": "Import Excel", "de": "Excel Import"},
    "export_excel": {"en": "Export Excel", "de": "Excel Export"},
    "backup_now": {"en": "Backup Now", "de": "Backup Jetzt"},
    "customer_name": {"en": "Customer Name", "de": "Kundenname"},
    "licence_plate": {"en": "Licence Plate", "de": "Kennzeichen"},
    "location": {"en": "Location", "de": "Lagerplatz"},
    "season": {"en": "Season", "de": "Saison"},
    "winter": {"en": "Winter", "de": "Winter"},
    "summer": {"en": "Summer", "de": "Sommer"},
    "allseason": {"en": "All-season", "de": "Ganzjahresreifen"},
    "save": {"en": "Save", "de": "Speichern"},
    "cancel": {"en": "Cancel", "de": "Abbrechen"},
    "delete_confirm": {"en": "Delete the selected record?", "de": "Den ausgewählten Eintrag löschen?"},
    "info_select_row": {"en": "Please select a row first.", "de": "Bitte zuerst eine Zeile auswählen."},
}

_current_lang = Language.EN

def set_language(lang: Language):
    """Set the current language"""
    global _current_lang
    _current_lang = lang

def t(key: str) -> str:
    """Translate a key to the current language"""
    return TRANSLATIONS.get(key, {}).get(_current_lang.value, key)

def localized_seasons():
    """Return list of localized season names for the current language"""
    return [t("winter"), t("summer"), t("allseason")]

def season_from_string(s: str):
    """Convert a localized string back to SeasonEnum"""
    s_lower = s.lower()
    mapping = {
        t("winter").lower(): SeasonEnum.WINTER,
        t("summer").lower(): SeasonEnum.SUMMER,
        t("allseason").lower(): SeasonEnum.ALLSEASON,
    }
    return mapping.get(s_lower, SeasonEnum.WINTER)
