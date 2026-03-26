"""Tests for tsm/models.py — ORM model definitions."""
from tsm.models import Base, WheelSet, Settings, AuditLog, DisabledPosition


def test_wheelset_table_name():
    assert WheelSet.__tablename__ == "wheel_sets"


def test_settings_table_name():
    assert Settings.__tablename__ == "settings"


def test_auditlog_table_name():
    assert AuditLog.__tablename__ == "audit_log"


def test_disabled_position_table_name():
    assert DisabledPosition.__tablename__ == "disabled_positions"


def test_base_has_all_tables():
    names = set(Base.metadata.tables.keys())
    assert "wheel_sets" in names
    assert "settings" in names
    assert "audit_log" in names
    assert "disabled_positions" in names


def test_create_wheelset(db_session):
    ws = WheelSet(
        customer_name="Test",
        license_plate="XX-YY 999",
        car_type="BMW",
        storage_position="C1ROL",
    )
    db_session.add(ws)
    db_session.commit()
    assert ws.id is not None
    assert ws.created_at is not None
    assert ws.updated_at is not None


def test_wheelset_unique_position(db_session):
    import pytest
    from sqlalchemy.exc import IntegrityError

    ws1 = WheelSet(customer_name="A", license_plate="A1",
                   car_type="VW", storage_position="C1ROL")
    db_session.add(ws1)
    db_session.commit()

    ws2 = WheelSet(customer_name="B", license_plate="B2",
                   car_type="Audi", storage_position="C1ROL")
    db_session.add(ws2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_create_settings(db_session):
    s = Settings(backup_interval_minutes=30, backup_copies=5)
    db_session.add(s)
    db_session.commit()
    assert s.id is not None


def test_settings_dark_mode_default(db_session):
    s = Settings(backup_interval_minutes=60, backup_copies=10)
    db_session.add(s)
    db_session.commit()
    assert s.dark_mode is False


def test_settings_dark_mode_toggle(db_session):
    s = Settings(
        backup_interval_minutes=60,
        backup_copies=10,
        dark_mode=True,
    )
    db_session.add(s)
    db_session.commit()
    assert s.dark_mode is True


def test_settings_custom_positions_json(db_session):
    import json
    positions = ["A1", "A2", "B1"]
    s = Settings(
        backup_interval_minutes=60,
        backup_copies=10,
        custom_positions_json=json.dumps(positions),
    )
    db_session.add(s)
    db_session.commit()
    loaded = json.loads(s.custom_positions_json)
    assert loaded == positions


def test_settings_custom_positions_null_by_default(db_session):
    s = Settings(backup_interval_minutes=60, backup_copies=10)
    db_session.add(s)
    db_session.commit()
    assert s.custom_positions_json is None


def test_create_audit_log(db_session):
    log = AuditLog(action="test", details="unit test entry")
    db_session.add(log)
    db_session.commit()
    assert log.id is not None
    assert log.created_at is not None


def test_create_disabled_position(db_session):
    dp = DisabledPosition(code="C2LOM", reason="broken shelf")
    db_session.add(dp)
    db_session.commit()
    fetched = db_session.get(DisabledPosition, "C2LOM")
    assert fetched is not None
    assert fetched.reason == "broken shelf"
