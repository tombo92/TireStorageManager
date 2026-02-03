#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Utils: leichter CSRF Schutz
"""
# ========================================================
# IMPORTS
# ========================================================
import secrets
from flask import session, request, abort


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
    if not token or not form_token or token != form_token:
        abort(400, description="Ungültiges CSRF-Token.")
