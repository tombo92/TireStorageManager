#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Flask App Factory
"""
# ========================================================
# IMPORTS
# ========================================================
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask
# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from config import SECRET_KEY, APP_NAME, VERSION
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

    # Jinja globals
    app.jinja_env.globals["csrf_token"] = get_csrf_token
    app.jinja_env.globals["APP_VERSION"] = VERSION
    app.jinja_env.globals["APP_NAME"] = APP_NAME
    app.jinja_env.globals["now"] = lambda: datetime.now(timezone.utc)

    # Register routes
    from tsm.routes import register_routes
    register_routes(app)

    return app
