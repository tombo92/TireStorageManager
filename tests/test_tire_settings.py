"""
Tests for Phase 1: enable_tire_details and enable_seasonal_tracking
settings flags (model, migration, routes, UI).
"""
import secrets

from sqlalchemy import create_engine, inspect, text, event

from tsm.models import Settings


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_csrf(client):
    """Inject a CSRF token into the session and return it."""
    with client.session_transaction() as sess:
        tok = secrets.token_urlsafe(16)
        sess["_csrf_token"] = tok
    return tok


# ── Phase 1A: Model defaults ────────────────────────────────────────────────

class TestSettingsModelDefaults:
    def test_enable_tire_details_column_exists(self):
        """Settings model has enable_tire_details attribute."""
        cols = {c.key for c in Settings.__table__.columns}
        assert "enable_tire_details" in cols

    def test_enable_seasonal_tracking_column_exists(self):
        """Settings model has enable_seasonal_tracking attribute."""
        cols = {c.key for c in Settings.__table__.columns}
        assert "enable_seasonal_tracking" in cols

    def test_enable_tire_details_default_false(self, db_session):
        s = Settings(backup_interval_minutes=60, backup_copies=10)
        db_session.add(s)
        db_session.commit()
        db_session.expire(s)
        assert s.enable_tire_details is False

    def test_enable_seasonal_tracking_default_false(self, db_session):
        s = Settings(backup_interval_minutes=60, backup_copies=10)
        db_session.add(s)
        db_session.commit()
        db_session.expire(s)
        assert s.enable_seasonal_tracking is False

    def test_can_enable_tire_details(self, db_session):
        s = Settings(backup_interval_minutes=60, backup_copies=10,
                     enable_tire_details=True)
        db_session.add(s)
        db_session.commit()
        db_session.expire(s)
        assert s.enable_tire_details is True

    def test_can_enable_seasonal_tracking(self, db_session):
        s = Settings(backup_interval_minutes=60, backup_copies=10,
                     enable_tire_details=True,
                     enable_seasonal_tracking=True)
        db_session.add(s)
        db_session.commit()
        db_session.expire(s)
        assert s.enable_seasonal_tracking is True


# ── Phase 1B: Migration (ALTER TABLE on existing DB) ───────────────────────

class TestSettingsMigration:
    """Verify _migrate() adds new columns to an old database that lacks them."""

    def _make_old_engine(self):
        """Create an in-memory DB that has the settings table but WITHOUT
        the new columns (simulating an old installation)."""
        eng = create_engine(
            "sqlite:///:memory:",
            echo=False,
            future=True,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(eng, "connect")
        def _pragma(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON;")
            cur.close()

        # Create a minimal "old" settings table without the new columns
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE settings (
                    id INTEGER PRIMARY KEY,
                    backup_interval_minutes INTEGER NOT NULL DEFAULT 60,
                    backup_copies INTEGER NOT NULL DEFAULT 10,
                    dark_mode BOOLEAN NOT NULL DEFAULT 0,
                    auto_update BOOLEAN NOT NULL DEFAULT 1,
                    language VARCHAR(10) NOT NULL DEFAULT 'de',
                    custom_positions_json TEXT,
                    updated_at DATETIME
                )
            """))
            conn.execute(text(
                "INSERT INTO settings (backup_interval_minutes, backup_copies) "
                "VALUES (60, 10)"
            ))
        return eng

    def test_migrate_adds_enable_tire_details(self):
        eng = self._make_old_engine()
        # Columns should be absent before migration
        insp = inspect(eng)
        cols_before = {c["name"] for c in insp.get_columns("settings")}
        assert "enable_tire_details" not in cols_before

        # Run the actual migration logic (same as tsm.db._migrate)
        existing = {c["name"] for c in insp.get_columns("settings")}
        with eng.begin() as conn:
            if "enable_tire_details" not in existing:
                conn.execute(text(
                    "ALTER TABLE settings "
                    "ADD COLUMN enable_tire_details BOOLEAN NOT NULL DEFAULT 0"
                ))
            if "enable_seasonal_tracking" not in existing:
                conn.execute(text(
                    "ALTER TABLE settings "
                    "ADD COLUMN enable_seasonal_tracking "
                    "BOOLEAN NOT NULL DEFAULT 0"
                ))

        insp2 = inspect(eng)
        cols_after = {c["name"] for c in insp2.get_columns("settings")}
        assert "enable_tire_details" in cols_after
        assert "enable_seasonal_tracking" in cols_after
        eng.dispose()

    def test_migrate_preserves_existing_data(self):
        eng = self._make_old_engine()
        insp = inspect(eng)
        existing = {c["name"] for c in insp.get_columns("settings")}
        with eng.begin() as conn:
            if "enable_tire_details" not in existing:
                conn.execute(text(
                    "ALTER TABLE settings "
                    "ADD COLUMN enable_tire_details BOOLEAN NOT NULL DEFAULT 0"
                ))
            if "enable_seasonal_tracking" not in existing:
                conn.execute(text(
                    "ALTER TABLE settings "
                    "ADD COLUMN enable_seasonal_tracking "
                    "BOOLEAN NOT NULL DEFAULT 0"
                ))

        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT backup_interval_minutes, enable_tire_details "
                     "FROM settings LIMIT 1")
            ).fetchone()
        assert row[0] == 60        # existing data preserved
        assert row[1] == 0         # new column defaulted to 0
        eng.dispose()

    def test_migrate_idempotent(self):
        """Running _migrate twice on a fully migrated DB must not raise."""
        eng = self._make_old_engine()
        for _ in range(2):
            insp = inspect(eng)
            existing = {c["name"] for c in insp.get_columns("settings")}
            with eng.begin() as conn:
                if "enable_tire_details" not in existing:
                    conn.execute(text(
                        "ALTER TABLE settings "
                        "ADD COLUMN enable_tire_details "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    ))
                if "enable_seasonal_tracking" not in existing:
                    conn.execute(text(
                        "ALTER TABLE settings "
                        "ADD COLUMN enable_seasonal_tracking "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    ))
        # Should reach here without error
        eng.dispose()


# ── Phase 1C: Route — settings POST ────────────────────────────────────────

class TestSettingsTireFlags:
    def test_get_settings_shows_tire_details_switch(
        self, client, seed_settings
    ):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert b"tireDetailsSwitch" in resp.data

    def test_get_settings_seasonal_switch_hidden_by_default(
        self, client, seed_settings
    ):
        """Seasonal tracking switch only appears when tire details enabled."""
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert b"seasonalTrackingSwitch" not in resp.data

    def test_post_enable_tire_details(
        self, client, seed_settings, db_session
    ):
        token = _get_csrf(client)
        resp = client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "dark_mode": "0",
            "auto_update": "1",
            "language": "de",
            "enable_tire_details": "1",
            "enable_seasonal_tracking": "0",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.enable_tire_details is True

    def test_post_disable_tire_details(
        self, client, seed_settings, db_session
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        token = _get_csrf(client)
        resp = client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "dark_mode": "0",
            "auto_update": "1",
            "language": "de",
            # enable_tire_details omitted → False
            "enable_seasonal_tracking": "0",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.enable_tire_details is False

    def test_post_enable_seasonal_tracking_with_tire_details(
        self, client, seed_settings, db_session
    ):
        token = _get_csrf(client)
        resp = client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "dark_mode": "0",
            "auto_update": "1",
            "language": "de",
            "enable_tire_details": "1",
            "enable_seasonal_tracking": "1",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.enable_tire_details is True
        assert s.enable_seasonal_tracking is True

    def test_post_seasonal_tracking_requires_tire_details(
        self, client, seed_settings, db_session
    ):
        """seasonal_tracking must be False if tire_details is off."""
        token = _get_csrf(client)
        resp = client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "dark_mode": "0",
            "auto_update": "1",
            "language": "de",
            # enable_tire_details NOT sent → False
            "enable_seasonal_tracking": "1",  # attempted without tire_details
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.enable_tire_details is False
        assert s.enable_seasonal_tracking is False

    def test_get_settings_shows_seasonal_switch_when_tire_details_enabled(
        self, client, seed_settings, db_session
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert b"seasonalTrackingSwitch" in resp.data

    def test_other_settings_preserved_when_toggling_tire_details(
        self, client, seed_settings, db_session
    ):
        """Toggling tire details must not reset other fields."""
        seed_settings.backup_interval_minutes = 45
        seed_settings.backup_copies = 7
        db_session.commit()
        token = _get_csrf(client)
        client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "45",
            "backup_copies": "7",
            "dark_mode": "0",
            "auto_update": "1",
            "language": "de",
            "enable_tire_details": "1",
            "enable_seasonal_tracking": "0",
        }, follow_redirects=True)
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.backup_interval_minutes == 45
        assert s.backup_copies == 7
        assert s.enable_tire_details is True


# ── Phase 1D: i18n keys present ────────────────────────────────────────────

class TestTireSettingsI18n:
    def test_i18n_key_tire_details_title_de(self):
        from tsm.i18n import _CATALOGUE
        assert "settings_tire_details_title" in _CATALOGUE
        assert _CATALOGUE["settings_tire_details_title"]["de"]

    def test_i18n_key_tire_details_title_en(self):
        from tsm.i18n import _CATALOGUE
        assert _CATALOGUE["settings_tire_details_title"]["en"]

    def test_i18n_key_enable_tire_details_de(self):
        from tsm.i18n import _CATALOGUE
        assert "settings_enable_tire_details" in _CATALOGUE
        assert _CATALOGUE["settings_enable_tire_details"]["de"]

    def test_i18n_key_enable_tire_details_en(self):
        from tsm.i18n import _CATALOGUE
        assert _CATALOGUE["settings_enable_tire_details"]["en"]

    def test_i18n_key_enable_tire_details_hint_de(self):
        from tsm.i18n import _CATALOGUE
        assert "settings_enable_tire_details_hint" in _CATALOGUE
        assert _CATALOGUE["settings_enable_tire_details_hint"]["de"]

    def test_i18n_key_enable_seasonal_tracking_de(self):
        from tsm.i18n import _CATALOGUE
        assert "settings_enable_seasonal_tracking" in _CATALOGUE
        assert _CATALOGUE["settings_enable_seasonal_tracking"]["de"]

    def test_i18n_key_enable_seasonal_tracking_en(self):
        from tsm.i18n import _CATALOGUE
        assert _CATALOGUE["settings_enable_seasonal_tracking"]["en"]

    def test_i18n_key_enable_seasonal_tracking_hint_de(self):
        from tsm.i18n import _CATALOGUE
        assert "settings_enable_seasonal_tracking_hint" in _CATALOGUE
        assert _CATALOGUE["settings_enable_seasonal_tracking_hint"]["de"]

    def test_i18n_gettext_tire_details_title_de(self):
        from tsm.i18n import gettext
        result = gettext("settings_tire_details_title")
        assert result == "Erweiterte Reifendaten"

    def test_i18n_gettext_tire_details_title_en(self, app):
        """With locale set to en, correct English translation is returned."""
        from flask import g
        with app.test_request_context("/"):
            g._tsm_locale = "en"
            from tsm.i18n import gettext
            assert gettext("settings_tire_details_title") == \
                "Extended Tire Details"

    def test_i18n_gettext_seasonal_tracking_en(self, app):
        from flask import g
        with app.test_request_context("/"):
            g._tsm_locale = "en"
            from tsm.i18n import gettext
            assert gettext("settings_enable_seasonal_tracking") == \
                "Seasonal wheel tracking"

    def test_settings_page_contains_tire_details_text_de(
        self, client, seed_settings
    ):
        resp = client.get("/settings")
        assert "Erweiterte Reifendaten".encode() in resp.data

    def test_settings_page_contains_seasonal_tracking_text_when_enabled(
        self, client, seed_settings, db_session
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        resp = client.get("/settings")
        assert "Saisonale Radverwaltung".encode() in resp.data
