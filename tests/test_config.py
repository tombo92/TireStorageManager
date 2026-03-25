"""Tests for config.py."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_version_format():
    from config import VERSION
    parts = VERSION.split(".")
    assert len(parts) == 3, "VERSION must be semver X.Y.Z"
    for p in parts:
        assert p.isdigit(), f"VERSION part '{p}' is not a digit"


def test_app_name_not_empty():
    from config import APP_NAME
    assert APP_NAME and len(APP_NAME) > 0


def test_paths_are_strings():
    from config import DB_PATH, BACKUP_DIR, LOG_DIR
    assert isinstance(DB_PATH, str)
    assert isinstance(BACKUP_DIR, str)
    assert isinstance(LOG_DIR, str)


def test_host_and_port():
    from config import HOST, PORT
    assert HOST == "0.0.0.0"
    assert isinstance(PORT, int)
    assert 1 <= PORT <= 65535
