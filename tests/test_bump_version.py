"""
Tests for tools/bump_version.py — patch/minor/major version bumping.
"""
from __future__ import annotations

import textwrap

from tools import bump_version


def _write_config(tmp_path, version="1.2.3"):
    cfg = tmp_path / "config.py"
    cfg.write_text(
        textwrap.dedent(f'''\
            """Config."""
            APP_NAME = "TireStorageManager"
            VERSION = "{version}"
            '''),
        encoding="utf-8",
    )
    return cfg


def _write_pyproject(tmp_path, version="1.2.3"):
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        textwrap.dedent(f'''\
            [project]
            name = "tire-storage-manager"
            version = "{version}"
            '''),
        encoding="utf-8",
    )
    return pp


class TestBumpVersionMain:
    def test_default_bump_is_patch(self, tmp_path, monkeypatch, capsys):
        cfg = _write_config(tmp_path)
        monkeypatch.setattr(bump_version, "CONFIG_PATH", cfg)
        monkeypatch.setattr(bump_version, "CHANGELOG_PATH", tmp_path / "nope.md")
        monkeypatch.setattr(bump_version, "PYPROJECT_PATH", tmp_path / "nope.toml")
        monkeypatch.setattr("sys.argv", ["bump_version.py"])

        rc = bump_version.main()

        assert rc == 0
        assert capsys.readouterr().out.strip() == "1.2.4"
        assert 'VERSION = "1.2.4"' in cfg.read_text(encoding="utf-8")

    def test_minor_bump_resets_patch(self, tmp_path, monkeypatch, capsys):
        cfg = _write_config(tmp_path)
        monkeypatch.setattr(bump_version, "CONFIG_PATH", cfg)
        monkeypatch.setattr(bump_version, "CHANGELOG_PATH", tmp_path / "nope.md")
        monkeypatch.setattr(bump_version, "PYPROJECT_PATH", tmp_path / "nope.toml")
        monkeypatch.setattr("sys.argv", ["bump_version.py", "--minor"])

        rc = bump_version.main()

        assert rc == 0
        assert capsys.readouterr().out.strip() == "1.3.0"
        assert 'VERSION = "1.3.0"' in cfg.read_text(encoding="utf-8")

    def test_major_bump_resets_minor_and_patch(
        self, tmp_path, monkeypatch, capsys
    ):
        cfg = _write_config(tmp_path)
        monkeypatch.setattr(bump_version, "CONFIG_PATH", cfg)
        monkeypatch.setattr(bump_version, "CHANGELOG_PATH", tmp_path / "nope.md")
        monkeypatch.setattr(bump_version, "PYPROJECT_PATH", tmp_path / "nope.toml")
        monkeypatch.setattr("sys.argv", ["bump_version.py", "--major"])

        rc = bump_version.main()

        assert rc == 0
        assert capsys.readouterr().out.strip() == "2.0.0"
        assert 'VERSION = "2.0.0"' in cfg.read_text(encoding="utf-8")

    def test_major_bump_from_nonzero_minor_patch(
        self, tmp_path, monkeypatch, capsys
    ):
        cfg = _write_config(tmp_path, version="3.7.9")
        monkeypatch.setattr(bump_version, "CONFIG_PATH", cfg)
        monkeypatch.setattr(bump_version, "CHANGELOG_PATH", tmp_path / "nope.md")
        monkeypatch.setattr(bump_version, "PYPROJECT_PATH", tmp_path / "nope.toml")
        monkeypatch.setattr("sys.argv", ["bump_version.py", "--major"])

        rc = bump_version.main()

        assert rc == 0
        assert capsys.readouterr().out.strip() == "4.0.0"

    def test_major_bump_syncs_pyproject_version(self, tmp_path, monkeypatch):
        cfg = _write_config(tmp_path)
        pp = _write_pyproject(tmp_path)
        monkeypatch.setattr(bump_version, "CONFIG_PATH", cfg)
        monkeypatch.setattr(bump_version, "CHANGELOG_PATH", tmp_path / "nope.md")
        monkeypatch.setattr(bump_version, "PYPROJECT_PATH", pp)
        monkeypatch.setattr("sys.argv", ["bump_version.py", "--major"])

        bump_version.main()

        assert 'version = "2.0.0"' in pp.read_text(encoding="utf-8")

    def test_missing_config_file_errors(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(bump_version, "CONFIG_PATH", tmp_path / "nope.py")
        monkeypatch.setattr("sys.argv", ["bump_version.py", "--major"])

        rc = bump_version.main()

        assert rc == 2
        assert "not found" in capsys.readouterr().err
