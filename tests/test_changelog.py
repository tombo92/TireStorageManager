"""Tests for tools/extract_changelog.py and changelog stamping."""
import textwrap

from tools.extract_changelog import extract


SAMPLE_CHANGELOG = textwrap.dedent("""\
    # Changelog

    ## [Unreleased]

    ### Added
    - New feature X

    ## [1.5.0] – 2026-03-25

    ### Added
    - Feature A
    - Feature B

    ### Fixed
    - Bug C

    ## [1.4.0] – 2026-03-01

    ### Added
    - Feature D
""")


class TestExtractChangelog:

    def test_extract_unreleased(self, tmp_path, monkeypatch):
        f = tmp_path / "CHANGELOG.md"
        f.write_text(SAMPLE_CHANGELOG, encoding="utf-8")
        monkeypatch.setattr(
            "tools.extract_changelog.CHANGELOG", f)
        body = extract(None)
        assert "New feature X" in body
        assert "Feature A" not in body

    def test_extract_specific_version(self, tmp_path, monkeypatch):
        f = tmp_path / "CHANGELOG.md"
        f.write_text(SAMPLE_CHANGELOG, encoding="utf-8")
        monkeypatch.setattr(
            "tools.extract_changelog.CHANGELOG", f)
        body = extract("1.5.0")
        assert "Feature A" in body
        assert "Feature B" in body
        assert "Bug C" in body
        assert "Feature D" not in body

    def test_extract_with_v_prefix(self, tmp_path, monkeypatch):
        f = tmp_path / "CHANGELOG.md"
        f.write_text(SAMPLE_CHANGELOG, encoding="utf-8")
        monkeypatch.setattr(
            "tools.extract_changelog.CHANGELOG", f)
        body = extract("v1.5.0")
        assert "Feature A" in body

    def test_extract_last_section(self, tmp_path, monkeypatch):
        f = tmp_path / "CHANGELOG.md"
        f.write_text(SAMPLE_CHANGELOG, encoding="utf-8")
        monkeypatch.setattr(
            "tools.extract_changelog.CHANGELOG", f)
        body = extract("1.4.0")
        assert "Feature D" in body

    def test_extract_missing_version(self, tmp_path, monkeypatch):
        f = tmp_path / "CHANGELOG.md"
        f.write_text(SAMPLE_CHANGELOG, encoding="utf-8")
        monkeypatch.setattr(
            "tools.extract_changelog.CHANGELOG", f)
        body = extract("9.9.9")
        assert body == ""

    def test_extract_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools.extract_changelog.CHANGELOG",
            tmp_path / "nope.md")
        body = extract("1.0.0")
        assert body == ""

    def test_extract_unreleased_keyword(
        self, tmp_path, monkeypatch
    ):
        f = tmp_path / "CHANGELOG.md"
        f.write_text(SAMPLE_CHANGELOG, encoding="utf-8")
        monkeypatch.setattr(
            "tools.extract_changelog.CHANGELOG", f)
        body = extract("unreleased")
        assert "New feature X" in body


class TestBumpStampsChangelog:
    """Verify bump_version._stamp_changelog moves Unreleased."""

    def test_stamp_creates_versioned_section(
        self, tmp_path, monkeypatch
    ):
        cl = tmp_path / "CHANGELOG.md"
        cl.write_text(SAMPLE_CHANGELOG, encoding="utf-8")
        monkeypatch.setattr(
            "tools.bump_version.CHANGELOG_PATH", cl)

        from tools.bump_version import _stamp_changelog
        _stamp_changelog("2.0.0")

        text = cl.read_text(encoding="utf-8")
        assert "## [2.0.0]" in text
        # Fresh Unreleased section should still exist
        assert "## [Unreleased]" in text
        # Old [1.5.0] section still present
        assert "## [1.5.0]" in text

    def test_stamp_no_changelog_file(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "tools.bump_version.CHANGELOG_PATH",
            tmp_path / "nope.md")
        from tools.bump_version import _stamp_changelog
        # Should not raise
        _stamp_changelog("1.0.0")
