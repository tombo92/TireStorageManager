"""Tests for tsm/utils.py — CSRF helpers and resource_path."""
from tsm.utils import get_csrf_token, validate_csrf, resource_path


class TestCsrf:
    def test_token_generated(self, app):
        with app.test_request_context():
            token = get_csrf_token()
            assert token is not None
            assert len(token) > 10
            # Same token on subsequent calls within same session
            assert get_csrf_token() == token

    def test_validate_csrf_ok(self, app):
        with app.test_request_context(
                method="POST",
                data={"_csrf_token": "tok123"},
                content_type="application/x-www-form-urlencoded"):
            from flask import session
            session["_csrf_token"] = "tok123"
            # Should NOT raise
            validate_csrf()

    def test_validate_csrf_fail(self, app):
        import pytest
        with app.test_request_context(
                method="POST",
                data={"_csrf_token": "wrong"},
                content_type="application/x-www-form-urlencoded"):
            from flask import session
            session["_csrf_token"] = "correct"
            with pytest.raises(Exception):
                validate_csrf()

    def test_validate_csrf_missing(self, app):
        import pytest
        with app.test_request_context(method="POST"):
            with pytest.raises(Exception):
                validate_csrf()


class TestResourcePath:
    def test_returns_string(self):
        result = resource_path("templates")
        assert isinstance(result, str)
        assert "templates" in result
