#!/usr/bin/env python
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Flask App Factory
"""
# ========================================================
# IMPORTS
# ========================================================
from datetime import UTC, datetime
from pathlib import Path

from flask import Flask, g

# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from config import APP_NAME, IS_PRERELEASE, SECRET_KEY, VERSION
from tsm.i18n import SUPPORTED_LOCALES, get_locale, gettext
from tsm.utils import get_csrf_token

# --------------------------------------------------------
# GLOBALS
# --------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]   # repo root (one level up from tsm/)
TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"


# ========================================================
# FUNCTIONS
# ========================================================
def create_app():
    app = Flask(__name__,
                template_folder=str(TEMPLATES_DIR),
                static_folder=str(STATIC_DIR),
                static_url_path="/static",
                )
    app.secret_key = SECRET_KEY

    # ── Locale: set g._tsm_locale before every request ──────────
    @app.before_request
    def _set_locale():
        from tsm.db import SessionLocal
        from tsm.models import Settings
        try:
            db = SessionLocal()
            s = db.query(Settings).first()
            locale = (s.language if s and s.language in SUPPORTED_LOCALES
                      else "de")
        except Exception:
            locale = "de"
        finally:
            SessionLocal.remove()
        g._tsm_locale = locale

    # Jinja globals
    app.jinja_env.globals["csrf_token"] = get_csrf_token
    app.jinja_env.globals["APP_VERSION"] = VERSION
    app.jinja_env.globals["APP_NAME"] = APP_NAME
    app.jinja_env.globals["IS_PRERELEASE"] = IS_PRERELEASE
    app.jinja_env.globals["now"] = lambda: datetime.now(UTC)
    app.jinja_env.globals["_"] = gettext
    app.jinja_env.globals["get_locale"] = get_locale

    # Register routes
    from tsm.routes import register_routes
    register_routes(app)

    return app
