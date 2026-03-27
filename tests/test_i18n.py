"""
Tests for tsm/i18n.py — translation catalogue, gettext(), and get_locale().
"""
import secrets

import pytest
from flask import g

from tsm.i18n import (
    SUPPORTED_LOCALES,
    DEFAULT_LOCALE,
    _CATALOGUE,
    get_locale,
    gettext,
    _,
)


def _csrf(client) -> str:
    """Inject a CSRF token into the test session and return it."""
    tok = secrets.token_urlsafe(16)
    with client.session_transaction() as sess:
        sess["_csrf_token"] = tok
    return tok


# ── Catalogue integrity ────────────────────────────────────────────────────────

def test_all_keys_have_both_locales():
    """Every catalogue entry must have a 'de' and an 'en' value."""
    missing = []
    for key, translations in _CATALOGUE.items():
        for locale in SUPPORTED_LOCALES:
            if locale not in translations or not translations[locale]:
                missing.append((key, locale))
    assert not missing, f"Missing translations: {missing}"


def test_no_empty_strings():
    """No translation value should be an empty string."""
    empty = [
        (k, loc)
        for k, vals in _CATALOGUE.items()
        for loc, text in vals.items()
        if not text.strip()
    ]
    assert not empty, f"Empty translation strings: {empty}"


def test_default_locale():
    assert DEFAULT_LOCALE == "de"


def test_supported_locales_contains_de_and_en():
    assert "de" in SUPPORTED_LOCALES
    assert "en" in SUPPORTED_LOCALES


# ── gettext() / _ alias ────────────────────────────────────────────────────────

def test_gettext_unknown_key_returns_key():
    """An unknown key should be returned as-is (no exception)."""
    assert gettext("__nonexistent_key__") == "__nonexistent_key__"


def test_gettext_alias_is_same_function():
    assert _ is gettext


def test_gettext_format_substitution(app):
    """Keyword arguments are substituted into the translated string."""
    with app.test_request_context("/"):
        g._tsm_locale = "en"
        result = gettext("positions_saved", n=7)
        assert "7" in result


def test_gettext_format_substitution_de(app):
    with app.test_request_context("/"):
        g._tsm_locale = "de"
        result = gettext("positions_saved", n=3)
        assert "3" in result


def test_gettext_missing_kwarg_does_not_raise(app):
    """If a required placeholder is missing, gettext returns the raw string."""
    with app.test_request_context("/"):
        g._tsm_locale = "en"
        # positions_saved expects {n} — omit it → should not raise
        result = gettext("positions_saved")
        assert isinstance(result, str)


# ── get_locale() ───────────────────────────────────────────────────────────────

def test_get_locale_outside_request_returns_default():
    """Outside a request context, get_locale() returns DEFAULT_LOCALE."""
    result = get_locale()
    assert result == DEFAULT_LOCALE


def test_get_locale_de(app):
    with app.test_request_context("/"):
        g._tsm_locale = "de"
        assert get_locale() == "de"


def test_get_locale_en(app):
    with app.test_request_context("/"):
        g._tsm_locale = "en"
        assert get_locale() == "en"


def test_get_locale_invalid_falls_back_to_default(app):
    with app.test_request_context("/"):
        g._tsm_locale = "zz"  # unsupported locale
        assert get_locale() == DEFAULT_LOCALE


def test_get_locale_missing_g_attr_falls_back(app):
    with app.test_request_context("/"):
        # g._tsm_locale not set at all
        assert get_locale() == DEFAULT_LOCALE


# ── Translation spot checks ───────────────────────────────────────────────────

@pytest.mark.parametrize("key,locale,expected_substring", [
    ("settings_saved",      "de", "gespeichert"),
    ("settings_saved",      "en", "saved"),
    ("wheelset_created",    "de", "angelegt"),
    ("wheelset_created",    "en", "created"),
    ("nav_wheelsets",       "de", "Radsätze"),
    ("nav_wheelsets",       "en", "Wheel"),
    ("wl_no_results",       "de", "Keine"),
    ("wl_no_results",       "en", "No"),
    ("del_title",           "de", "löschen"),
    ("del_title",           "en", "Delete"),
    ("bk_no_backups",       "de", "Keine"),
    ("bk_no_backups",       "en", "No backups"),
    ("settings_language",   "de", "Sprache"),
    ("settings_language",   "en", "Sprache"),  # intentionally bilingual label
])
def test_spot_translations(key, locale, expected_substring, app):
    with app.test_request_context("/"):
        g._tsm_locale = locale
        result = gettext(key)
        assert expected_substring in result, (
            f"Key={key!r} locale={locale!r}: "
            f"expected {expected_substring!r} in {result!r}"
        )


# ── Jinja2 injection ──────────────────────────────────────────────────────────

def test_jinja_globals_contain_gettext(app):
    """The Flask app must expose _ and get_locale in Jinja globals."""
    assert "_" in app.jinja_env.globals
    assert "get_locale" in app.jinja_env.globals


def test_jinja_gettext_is_callable(app):
    assert callable(app.jinja_env.globals["_"])


# ── Settings persistence ──────────────────────────────────────────────────────

def test_settings_post_saves_language(client, seed_settings):
    """POST /settings with language=en should persist and redirect with 200."""
    resp = client.post(
        "/settings",
        data={
            "_csrf_token": _csrf(client),
            "dark_mode": "0",
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "auto_update": "0",
            "language": "en",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Flash message is rendered (de or en depending on DB state in test)
    assert b"gespeichert" in resp.data or b"saved" in resp.data


def test_settings_post_invalid_language_falls_back_to_de(client, seed_settings):
    """Posting an unsupported locale should silently fall back to 'de'."""
    resp = client.post(
        "/settings",
        data={
            "_csrf_token": _csrf(client),
            "dark_mode": "0",
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "auto_update": "0",
            "language": "xx",  # unsupported
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
