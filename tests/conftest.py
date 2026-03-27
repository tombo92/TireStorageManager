"""
Shared pytest fixtures for TireStorageManager tests.

Provides an in-memory SQLite database, a scoped session, and a Flask
test client so that every test runs in isolation without touching the
real DB on disk.
"""
import os
import sys
import tempfile
import pytest

# ── Make sure project root is on sys.path ──
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Force a temp data directory *before* config is imported so that
# config.py's os.makedirs calls don't fail or pollute the real dirs.
_test_data_dir = tempfile.mkdtemp(prefix="tsm_test_")
os.environ["TSM_DATA_DIR"] = _test_data_dir
os.environ.setdefault("TSM_SECRET_KEY", "test-secret-key")

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session

from tsm.models import Base, WheelSet, Settings


@pytest.fixture(scope="function")
def db_engine():
    """Create a fresh in-memory SQLite engine per test.

    The URL is asserted to be in-memory so that a future misconfiguration
    cannot silently cause tests to write to the real on-disk database.
    """
    url = "sqlite:///:memory:"
    eng = create_engine(
        url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _set_pragma(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.close()

    Base.metadata.create_all(bind=eng)
    assert ":memory:" in str(eng.url), (
        f"Tests must use an in-memory SQLite DB, got: {eng.url}"
    )
    yield eng
    eng.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Scoped session bound to the in-memory engine."""
    factory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = scoped_session(factory)
    yield session
    session.remove()


@pytest.fixture(scope="function")
def app(db_engine, db_session, monkeypatch):
    """Flask app wired to the test database."""
    # Patch tsm.db so that all code using SessionLocal / engine
    # transparently hits our in-memory DB.
    import tsm.db as db_mod
    import tsm.routes as routes_mod
    import tsm.backup_manager as bm_mod

    monkeypatch.setattr(db_mod, "engine", db_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", db_session)
    # Also patch modules that imported SessionLocal directly
    monkeypatch.setattr(routes_mod, "SessionLocal", db_session)
    monkeypatch.setattr(bm_mod, "SessionLocal", db_session)

    # Patch self_update so tests never hit the network
    import tsm.self_update as su_mod
    monkeypatch.setattr(su_mod, "_update_info_cache", None)
    monkeypatch.setattr(su_mod, "_update_info_cache_ts", 0.0)
    # Also patch the references imported into routes
    import tsm.routes as routes_mod2
    monkeypatch.setattr(routes_mod2, "get_update_info", su_mod.get_update_info)
    monkeypatch.setattr(
        routes_mod2, "invalidate_update_cache",
        su_mod.invalidate_update_cache)
    monkeypatch.setattr(
        routes_mod2, "check_for_update", su_mod.check_for_update)
    monkeypatch.setattr(routes_mod2, "_is_frozen", su_mod._is_frozen)

    from tsm.app import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    yield flask_app


@pytest.fixture(scope="function")
def client(app):
    """Flask test client."""
    with app.test_client() as c:
        yield c


@pytest.fixture(scope="function")
def seed_wheelset(db_session):
    """Insert one WheelSet and return it."""
    ws = WheelSet(
        customer_name="Max Mustermann",
        license_plate="AB-CD 1234",
        car_type="VW Golf",
        storage_position="C1ROM",
        note="Winterreifen",
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture(scope="function")
def seed_settings(db_session):
    """Ensure a Settings row exists."""
    s = Settings(backup_interval_minutes=60, backup_copies=10)
    db_session.add(s)
    db_session.commit()
    return s
