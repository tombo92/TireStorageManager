#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Utils: leichter CSRF Schutz + Kennzeichen-Validierung
"""
# ========================================================
# IMPORTS
# ========================================================
import os
import re
import sys
import hmac
import secrets
from flask import session, request, abort


# ========================================================
# CONSTANTS
# ========================================================

# German licence-plate pattern
# Covers all current formats:
#   Unterscheidungszeichen (1–3 letters)  e.g. M, AB, MIL, TEG …
#   Erkennungsbuchstaben  (1–2 letters)   e.g. A, AB
#   Erkennungsziffern     (1–4 digits)    e.g. 1, 12, 123, 1234
#   Optional: E suffix (Elektro), H suffix (Historisch)
#
# Allowed separators between the three parts: space, hyphen, or none.
# Examples:
#   M AB 1234   M-AB-1234   MAB1234
#   B A 1 H     KA XY 99 E
#
# The regex is intentionally liberal on the Unterscheidungszeichen
# length (1–3) because there are ~500 valid codes and validating
# them exhaustively is out of scope.  The format itself is enforced.
_PLATE_RE = re.compile(
    r"^[A-ZÄÖÜ]{1,3}"        # Unterscheidungszeichen
    r"[\s\-]?"                 # optional separator
    r"[A-Z]{1,2}"             # Erkennungsbuchstaben
    r"[\s\-]?"                 # optional separator
    r"\d{1,4}"                 # Erkennungsziffern
    r"(?:[\s\-]?[EH])?$",     # optional E (Elektro) or H (Historisch)
    re.IGNORECASE,
)


# ========================================================
# FUNCTIONS
# ========================================================
def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(16)
        session["_csrf_token"] = token
    return token


def validate_csrf():
    token = session.get("_csrf_token")
    form_token = request.form.get("_csrf_token")
    if not token or not form_token or not hmac.compare_digest(token, form_token):
        abort(400, description="Ungültiges CSRF-Token.")


def resource_path(rel_path: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel_path)


def is_valid_license_plate(value: str) -> bool:
    """Return True if *value* matches the German licence-plate pattern."""
    return bool(_PLATE_RE.match(value.strip()))


def normalize_license_plate(value: str) -> str:
    """Strip whitespace and upper-case a licence plate value for storage.

    No reformatting is performed — the plate is stored exactly as the user
    entered it (after uppercasing), so that ``B-JB 123`` stays ``B-JB 123``
    and is never silently rewritten.
    """
    return value.strip().upper()


def overdue_season(month: int) -> str | None:
    """Return the season name whose tires are overdue for the given month.

    Swap windows (not overdue):
      - May–Jun  (5–6):  winter→summer is happening now
      - Oct–Dec (10–12): summer→winter is happening now

    Overdue:
      - Jan–Apr  (1–4):  summer tires still stored
                         (swap to winter should have finished by Dec)
      - Jul–Sep  (7–9):  winter tires still stored
                         (swap to summer should have finished by Jun)

    Returns None when neither season is considered overdue (swap windows).
    """
    if 1 <= month <= 4:
        return "sommer"   # should have left by December
    if 7 <= month <= 9:
        return "winter"   # should have left by June
    return None           # active swap window (May–Jun or Oct–Dec)
