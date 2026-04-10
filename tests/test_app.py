"""Tests for tsm/app.py — Flask app factory."""
import logging
import logging.handlers
import os


class TestCreateApp:
    def test_app_created(self, app):
        assert app is not None

    def test_secret_key_set(self, app):
        assert app.secret_key is not None
        assert len(app.secret_key) > 0

    def test_jinja_globals(self, app):
        env = app.jinja_env
        assert "csrf_token" in env.globals
        assert "APP_VERSION" in env.globals
        assert "APP_NAME" in env.globals
        assert "now" in env.globals

    def test_testing_mode(self, app):
        assert app.config["TESTING"] is True


class TestLogRotation:
    """Verify that run.py wires up a RotatingFileHandler with sensible limits.

    Instead of reloading the module (which fights pytest's logging capture),
    we inspect the ``_file`` handler object that run.py creates at module level.
    """

    @staticmethod
    def _get_handler():
        """Return the RotatingFileHandler created by run.py."""
        import run  # noqa: PLC0415
        return run._file

    def test_rotating_handler_type(self):
        """run._file must be a RotatingFileHandler."""
        h = self._get_handler()
        assert isinstance(h, logging.handlers.RotatingFileHandler), (
            f"Expected RotatingFileHandler, got {type(h)}"
        )

    def test_log_filename_is_tsm_log(self):
        """RotatingFileHandler must target a file named tsm.log."""
        h = self._get_handler()
        assert os.path.basename(h.baseFilename) == "tsm.log"

    def test_max_bytes_at_least_1mb(self):
        """Log files must rotate before growing beyond a sensible cap (≥ 1 MB)."""
        h = self._get_handler()
        assert h.maxBytes >= 1 * 1024 * 1024, (
            f"maxBytes={h.maxBytes} is less than 1 MB"
        )

    def test_backup_count_at_least_2(self):
        """At least 2 rotated log files must be kept (ring-buffer depth ≥ 2)."""
        h = self._get_handler()
        assert h.backupCount >= 2, (
            f"backupCount={h.backupCount} — log history too short"
        )
