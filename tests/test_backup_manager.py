"""Tests for tsm/backup_manager.py — backup + CSV export."""
import os
import tempfile
from unittest.mock import patch

from tsm.models import WheelSet, Settings, AuditLog
from tsm.backup_manager import BackupManager, export_csv_snapshot


class TestExportCsv:
    def test_creates_csv(self, db_session, db_engine, seed_wheelset,
                         monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "test.csv")
            # Patch SessionLocal used inside export_csv_snapshot
            import tsm.backup_manager as bm_mod
            monkeypatch.setattr(bm_mod, "SessionLocal", db_session)
            result = export_csv_snapshot(target)
            assert result == target
            assert os.path.exists(target)
            with open(target, encoding="utf-8-sig") as f:
                content = f.read()
            assert "Mustermann" in content
            assert "C1ROM" in content

    def test_csv_header(self, db_session, db_engine, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "test.csv")
            import tsm.backup_manager as bm_mod
            monkeypatch.setattr(bm_mod, "SessionLocal", db_session)
            export_csv_snapshot(target)
            with open(target, encoding="utf-8-sig") as f:
                header = f.readline()
            assert "customer_name" in header
            assert "storage_position" in header


class TestBackupManager:
    def test_perform_backup(self, db_session, db_engine, seed_wheelset,
                            seed_settings, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            import tsm.backup_manager as bm_mod
            monkeypatch.setattr(bm_mod, "SessionLocal", db_session)
            monkeypatch.setattr(bm_mod, "engine", db_engine)

            mgr = BackupManager(db_engine, tmpdir)
            mgr.perform_backup()

            files = os.listdir(tmpdir)
            db_files = [f for f in files if f.endswith(".db")]
            csv_files = [f for f in files if f.endswith(".csv")]
            assert len(db_files) >= 1
            assert len(csv_files) >= 1

    def test_retention(self, db_session, db_engine, seed_wheelset,
                       seed_settings, monkeypatch):
        """Backup manager should respect retention (backup_copies)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import tsm.backup_manager as bm_mod
            monkeypatch.setattr(bm_mod, "SessionLocal", db_session)
            monkeypatch.setattr(bm_mod, "engine", db_engine)

            # Set retention to 2
            seed_settings.backup_copies = 2
            db_session.commit()

            mgr = BackupManager(db_engine, tmpdir)
            # Run 4 backups — only 2 should survive
            for _ in range(4):
                mgr.perform_backup()

            db_files = [f for f in os.listdir(tmpdir) if f.endswith(".db")]
            csv_files = [f for f in os.listdir(tmpdir) if f.endswith(".csv")]
            assert len(db_files) <= 2
            assert len(csv_files) <= 2
