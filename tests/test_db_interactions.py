"""
Tests for real database interactions:
- WheelSet CRUD via SQLAlchemy session
- AuditLog creation and querying
- Settings read/write/defaults
- DisabledPosition enable/disable round-trips
- Schema migration (_migrate) adds missing columns
"""
import json
import pytest
from sqlalchemy.exc import IntegrityError
from tsm.models import WheelSet, Settings, AuditLog, DisabledPosition
from tsm.positions import disable_position, enable_position


# ──────────────────────────────────────────────────────────────────────
# WheelSet CRUD
# ──────────────────────────────────────────────────────────────────────
class TestWheelSetCrud:

    def test_create_and_fetch(self, db_session):
        ws = WheelSet(
            customer_name="Anna Müller",
            license_plate="M-AB 1234",
            car_type="BMW 3er",
            storage_position="C1ROL",
        )
        db_session.add(ws)
        db_session.commit()

        fetched = db_session.get(WheelSet, ws.id)
        assert fetched is not None
        assert fetched.customer_name == "Anna Müller"
        assert fetched.license_plate == "M-AB 1234"
        assert fetched.storage_position == "C1ROL"

    def test_timestamps_set_on_create(self, db_session):
        ws = WheelSet(
            customer_name="Tim Test",
            license_plate="TT-00 001",
            car_type="VW Golf",
            storage_position="C2ROL",
        )
        db_session.add(ws)
        db_session.commit()
        assert ws.created_at is not None
        assert ws.updated_at is not None

    def test_update_fields(self, db_session, seed_wheelset):
        seed_wheelset.note = "Updated note"
        db_session.commit()
        db_session.expire_all()
        fetched = db_session.get(WheelSet, seed_wheelset.id)
        assert fetched.note == "Updated note"

    def test_delete(self, db_session, seed_wheelset):
        wid = seed_wheelset.id
        db_session.delete(seed_wheelset)
        db_session.commit()
        assert db_session.get(WheelSet, wid) is None

    def test_duplicate_position_raises(self, db_session):
        ws1 = WheelSet(
            customer_name="A", license_plate="A1",
            car_type="X", storage_position="C3ROL")
        db_session.add(ws1)
        db_session.commit()

        ws2 = WheelSet(
            customer_name="B", license_plate="B2",
            car_type="Y", storage_position="C3ROL")
        db_session.add(ws2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_search_by_name(self, db_session):
        db_session.add(WheelSet(
            customer_name="Findable Person",
            license_plate="FP-00 001",
            car_type="Audi",
            storage_position="C1RML",
        ))
        db_session.add(WheelSet(
            customer_name="Other Person",
            license_plate="OP-00 002",
            car_type="Seat",
            storage_position="C1RUL",
        ))
        db_session.commit()

        results = db_session.query(WheelSet).filter(
            WheelSet.customer_name.ilike("%findable%")
        ).all()
        assert len(results) == 1
        assert results[0].customer_name == "Findable Person"

    def test_optional_note_is_nullable(self, db_session):
        ws = WheelSet(
            customer_name="No Note",
            license_plate="NN-00 001",
            car_type="Skoda",
            storage_position="C1ROM",
            note=None,
        )
        db_session.add(ws)
        db_session.commit()
        assert ws.note is None


# ──────────────────────────────────────────────────────────────────────
# AuditLog
# ──────────────────────────────────────────────────────────────────────
class TestAuditLog:

    def test_create_entry(self, db_session):
        entry = AuditLog(action="create", details="test entry")
        db_session.add(entry)
        db_session.commit()
        assert entry.id is not None
        assert entry.created_at is not None

    def test_null_wheelset_id_allowed(self, db_session):
        entry = AuditLog(action="backup", wheelset_id=None,
                         details="manual backup")
        db_session.add(entry)
        db_session.commit()
        assert entry.wheelset_id is None

    def test_multiple_actions_ordered(self, db_session):
        for action in ("create", "update", "delete"):
            db_session.add(AuditLog(action=action))
        db_session.commit()

        all_logs = (db_session.query(AuditLog)
                    .order_by(AuditLog.id).all())
        actions = [e.action for e in all_logs]
        assert actions == ["create", "update", "delete"]

    def test_query_by_action(self, db_session):
        db_session.add(AuditLog(action="create", wheelset_id=1))
        db_session.add(AuditLog(action="delete", wheelset_id=1))
        db_session.add(AuditLog(action="create", wheelset_id=2))
        db_session.commit()

        creates = (db_session.query(AuditLog)
                   .filter_by(action="create").all())
        assert len(creates) == 2


# ──────────────────────────────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────────────────────────────
class TestSettingsDb:

    def test_defaults(self, db_session):
        s = Settings(backup_interval_minutes=60, backup_copies=10)
        db_session.add(s)
        db_session.commit()
        assert s.dark_mode is False
        assert s.auto_update is True
        assert s.custom_positions_json is None

    def test_persist_and_reload(self, db_session):
        s = Settings(
            backup_interval_minutes=30,
            backup_copies=5,
            dark_mode=True,
            auto_update=False,
        )
        db_session.add(s)
        db_session.commit()
        sid = s.id
        db_session.expire_all()

        fetched = db_session.get(Settings, sid)
        assert fetched.backup_interval_minutes == 30
        assert fetched.backup_copies == 5
        assert fetched.dark_mode is True
        assert fetched.auto_update is False

    def test_custom_positions_json_roundtrip(self, db_session):
        positions = ["SHELF-A", "SHELF-B", "SHELF-C"]
        s = Settings(
            backup_interval_minutes=60,
            backup_copies=10,
            custom_positions_json=json.dumps(positions),
        )
        db_session.add(s)
        db_session.commit()
        db_session.expire_all()

        fetched = db_session.get(Settings, s.id)
        assert json.loads(fetched.custom_positions_json) == positions

    def test_update_settings(self, db_session, seed_settings):
        seed_settings.backup_interval_minutes = 120
        seed_settings.dark_mode = True
        seed_settings.auto_update = False
        db_session.commit()
        db_session.expire_all()

        fetched = db_session.get(Settings, seed_settings.id)
        assert fetched.backup_interval_minutes == 120
        assert fetched.dark_mode is True
        assert fetched.auto_update is False

    def test_only_one_settings_row_in_practice(self, db_session):
        """App always uses get_or_create pattern — only 1 row."""
        from tsm.db import get_or_create_settings
        s1 = get_or_create_settings(db_session)
        s2 = get_or_create_settings(db_session)
        assert s1.id == s2.id
        count = db_session.query(Settings).count()
        assert count == 1


# ──────────────────────────────────────────────────────────────────────
# DisabledPosition enable/disable round-trips
# ──────────────────────────────────────────────────────────────────────
class TestDisabledPositionDb:

    def test_disable_persists(self, db_session):
        disable_position(db_session, "C1ROL", "broken shelf")
        row = db_session.get(DisabledPosition, "C1ROL")
        assert row is not None
        assert row.reason == "broken shelf"
        assert row.created_at is not None

    def test_disable_without_reason(self, db_session):
        disable_position(db_session, "C2ROL")
        row = db_session.get(DisabledPosition, "C2ROL")
        assert row.reason is None

    def test_enable_removes_row(self, db_session):
        disable_position(db_session, "C1ROL")
        enable_position(db_session, "C1ROL")
        row = db_session.get(DisabledPosition, "C1ROL")
        assert row is None

    def test_disable_then_enable_then_disable_again(self, db_session):
        assert disable_position(db_session, "C1ROL") is True
        assert enable_position(db_session, "C1ROL") is True
        assert disable_position(db_session, "C1ROL") is True
        row = db_session.get(DisabledPosition, "C1ROL")
        assert row is not None

    def test_multiple_disabled_positions(self, db_session):
        for pos in ("C1ROL", "C2ROL", "GR1OL"):
            disable_position(db_session, pos)
        rows = db_session.query(DisabledPosition).all()
        codes = {r.code for r in rows}
        assert codes == {"C1ROL", "C2ROL", "GR1OL"}

    def test_enable_all_clears_table(self, db_session):
        for pos in ("C1ROL", "C2ROL"):
            disable_position(db_session, pos)
        for pos in ("C1ROL", "C2ROL"):
            enable_position(db_session, pos)
        assert db_session.query(DisabledPosition).count() == 0


# ──────────────────────────────────────────────────────────────────────
# Schema migration
# ──────────────────────────────────────────────────────────────────────
class TestSchemaMigration:
    """Verify that _migrate() adds columns missing from old databases."""

    def test_migrate_adds_dark_mode(self):
        from sqlalchemy import create_engine, inspect, text
        from tsm.db import _migrate

        eng = create_engine("sqlite:///:memory:", future=True)
        # Create the table WITHOUT dark_mode (simulate old schema)
        with eng.begin() as conn:
            conn.execute(text(
                "CREATE TABLE settings ("
                "  id INTEGER PRIMARY KEY,"
                "  backup_interval_minutes INTEGER NOT NULL DEFAULT 60,"
                "  backup_copies INTEGER NOT NULL DEFAULT 10"
                ")"
            ))

        # Patch the module-level engine used by _migrate
        import tsm.db as db_mod
        original = db_mod.engine
        db_mod.engine = eng
        try:
            _migrate()
        finally:
            db_mod.engine = original

        cols = {c["name"] for c in inspect(eng).get_columns("settings")}
        assert "dark_mode" in cols
        assert "custom_positions_json" in cols
        assert "auto_update" in cols

    def test_migrate_is_idempotent(self):
        """Calling _migrate() twice must not raise."""
        from tsm.db import _migrate
        _migrate()
        _migrate()   # second call should be a no-op
