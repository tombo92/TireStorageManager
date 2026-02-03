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
from flask import Flask
from datetime import datetime, timezone
# --------------------------------------------------------
# Local Imports
# --------------------------------------------------------
from config import SECRET_KEY, APP_NAME, VERSION
from utils import get_csrf_token


# ========================================================
# FUNCTIONS
# ========================================================
def create_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY

    # Jinja globals
    app.jinja_env.globals["csrf_token"] = get_csrf_token
    app.jinja_env.globals["APP_VERSION"] = VERSION
    app.jinja_env.globals["APP_NAME"] = APP_NAME
    app.jinja_env.globals["now"] = lambda: datetime.now(timezone.utc)

    # Register routes
    from routes import register_routes
    register_routes(app)

    return app
