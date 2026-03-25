"""Tests for tsm/self_update.py — version parsing and helpers."""
from tsm.self_update import _ver_tuple, _nocache_url, _is_frozen


class TestVerTuple:
    def test_basic_semver(self):
        assert _ver_tuple("1.2.3") == (1, 2, 3)

    def test_with_v_prefix(self):
        assert _ver_tuple("v1.2.3") == (1, 2, 3)

    def test_pre_release(self):
        assert _ver_tuple("1.2.3-beta") == (1, 2, 3)

    def test_empty_string(self):
        assert _ver_tuple("") == (0, 0, 0)

    def test_nonsense(self):
        assert _ver_tuple("abc") == (0, 0, 0)

    def test_comparison(self):
        assert _ver_tuple("1.3.0") > _ver_tuple("1.2.9")
        assert _ver_tuple("2.0.0") > _ver_tuple("1.99.99")
        assert _ver_tuple("1.2.0") == _ver_tuple("1.2.0")


class TestNoCacheUrl:
    def test_adds_ts_param(self):
        url = _nocache_url("https://example.com/api")
        assert "?ts=" in url

    def test_existing_query(self):
        url = _nocache_url("https://example.com/api?foo=bar")
        assert "&ts=" in url


class TestIsFrozen:
    def test_not_frozen_in_test(self):
        # Tests run from source, not PyInstaller
        assert _is_frozen() is False
