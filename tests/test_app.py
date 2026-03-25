"""Tests for tsm/app.py — Flask app factory."""


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
