"""
Tests for Phase 2: Extended WheelSet tire-detail columns.

Covers:
- Model: new nullable columns with correct defaults
- Migration: ALTER TABLE on an old wheel_sets table
- Routes: create/edit persist tire detail fields when flag is on;
          fields are silently ignored when flag is off
- Templates: form shows / hides tire detail section based on flag;
             list shows season/rim badges, icons, and overdue highlights
- Overdue logic: overdue_season() utility + route integration
"""
import secrets

from sqlalchemy import create_engine, inspect, text, event

from tsm.models import WheelSet
from tsm.utils import overdue_season


# ── Helpers ────────────────────────────────────────────────────────────────

def _csrf(client):
    with client.session_transaction() as sess:
        tok = secrets.token_urlsafe(16)
        sess["_csrf_token"] = tok
    return tok


def _enable_tire_details(db_session, seed_settings):
    seed_settings.enable_tire_details = True
    db_session.commit()


# ── Phase 2A: Model ─────────────────────────────────────────────────────────

class TestWheelSetTireColumns:
    def test_tire_manufacturer_column_exists(self):
        cols = {c.key for c in WheelSet.__table__.columns}
        assert "tire_manufacturer" in cols

    def test_tire_size_column_exists(self):
        cols = {c.key for c in WheelSet.__table__.columns}
        assert "tire_size" in cols

    def test_tire_age_column_exists(self):
        cols = {c.key for c in WheelSet.__table__.columns}
        assert "tire_age" in cols

    def test_season_column_exists(self):
        cols = {c.key for c in WheelSet.__table__.columns}
        assert "season" in cols

    def test_rim_type_column_exists(self):
        cols = {c.key for c in WheelSet.__table__.columns}
        assert "rim_type" in cols

    def test_exchange_note_column_exists(self):
        cols = {c.key for c in WheelSet.__table__.columns}
        assert "exchange_note" in cols

    def test_all_tire_columns_nullable_by_default(self, db_session):
        ws = WheelSet(
            customer_name="Test", license_plate="B-XX 1",
            car_type="Golf", storage_position="C1ROM",
        )
        db_session.add(ws)
        db_session.commit()
        db_session.expire(ws)
        assert ws.tire_manufacturer is None
        assert ws.tire_size is None
        assert ws.tire_age is None
        assert ws.season is None
        assert ws.rim_type is None
        assert ws.exchange_note is None

    def test_can_store_tire_details(self, db_session):
        ws = WheelSet(
            customer_name="Anna", license_plate="M-AA 1",
            car_type="BMW 3er", storage_position="C1LOM",
            tire_manufacturer="Michelin",
            tire_size="225/45 R18",
            tire_age="2023",
            season="winter",
            rim_type="alu",
            exchange_note="Vor erstem Schneefall wechseln",
        )
        db_session.add(ws)
        db_session.commit()
        db_session.expire(ws)
        assert ws.tire_manufacturer == "Michelin"
        assert ws.tire_size == "225/45 R18"
        assert ws.tire_age == "2023"
        assert ws.season == "winter"
        assert ws.rim_type == "alu"
        assert ws.exchange_note == "Vor erstem Schneefall wechseln"


# ── Phase 2B: Migration ─────────────────────────────────────────────────────

class TestWheelSetMigration:
    def _make_old_engine(self):
        """wheel_sets table without the new tire-detail columns."""
        eng = create_engine(
            "sqlite:///:memory:", echo=False, future=True,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(eng, "connect")
        def _p(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON;")
            cur.close()

        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE wheel_sets (
                    id INTEGER PRIMARY KEY,
                    customer_name VARCHAR(200) NOT NULL,
                    license_plate VARCHAR(50) NOT NULL,
                    car_type VARCHAR(200) NOT NULL,
                    note TEXT,
                    storage_position VARCHAR(20) NOT NULL UNIQUE,
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """))
            conn.execute(text(
                "INSERT INTO wheel_sets "
                "(customer_name, license_plate, car_type, storage_position) "
                "VALUES ('Old User', 'X-YZ 1', 'Polo', 'C1ROM')"
            ))
        return eng

    def _run_migration(self, eng):
        insp = inspect(eng)
        ws_existing = {c["name"] for c in insp.get_columns("wheel_sets")}
        with eng.begin() as conn:
            for col, typ in [
                ("tire_manufacturer", "VARCHAR(100)"),
                ("tire_size",         "VARCHAR(50)"),
                ("tire_age",          "VARCHAR(20)"),
                ("season",            "VARCHAR(20)"),
                ("rim_type",          "VARCHAR(20)"),
                ("exchange_note",     "TEXT"),
            ]:
                if col not in ws_existing:
                    conn.execute(text(
                        f"ALTER TABLE wheel_sets ADD COLUMN {col} {typ}"
                    ))

    def test_migrate_adds_all_tire_columns(self):
        eng = self._make_old_engine()
        insp = inspect(eng)
        cols_before = {c["name"] for c in insp.get_columns("wheel_sets")}
        assert "tire_manufacturer" not in cols_before

        self._run_migration(eng)

        insp2 = inspect(eng)
        cols_after = {c["name"] for c in insp2.get_columns("wheel_sets")}
        for col in ("tire_manufacturer", "tire_size", "tire_age",
                    "season", "rim_type", "exchange_note"):
            assert col in cols_after, f"Missing column: {col}"
        eng.dispose()

    def test_migrate_preserves_existing_rows(self):
        eng = self._make_old_engine()
        self._run_migration(eng)
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT customer_name, tire_manufacturer FROM wheel_sets")
            ).fetchone()
        assert row[0] == "Old User"
        assert row[1] is None
        eng.dispose()

    def test_migrate_idempotent(self):
        eng = self._make_old_engine()
        self._run_migration(eng)
        self._run_migration(eng)  # second run must not raise
        eng.dispose()


# ── Phase 2C: Routes — create ───────────────────────────────────────────────

class TestCreateWheelsetTireDetails:
    def test_form_hidden_when_flag_off(self, client, seed_settings):
        resp = client.get("/wheelsets/new")
        assert resp.status_code == 200
        assert b"tire_manufacturer" not in resp.data

    def test_form_shown_when_flag_on(
        self, client, seed_settings, db_session
    ):
        _enable_tire_details(db_session, seed_settings)
        resp = client.get("/wheelsets/new")
        assert resp.status_code == 200
        assert b"tire_manufacturer" in resp.data

    def test_create_saves_tire_details_when_flag_on(
        self, client, seed_settings, db_session
    ):
        _enable_tire_details(db_session, seed_settings)
        tok = _csrf(client)
        resp = client.post("/wheelsets/new", data={
            "_csrf_token": tok,
            "customer_name": "Klaus Müller",
            "license_plate": "M-KM 4321",
            "car_type": "Audi A4",
            "storage_position": "C1LOM",
            "tire_manufacturer": "Continental",
            "tire_size": "205/55 R16",
            "tire_age": "2022",
            "season": "winter",
            "rim_type": "stahl",
            "exchange_note": "Im Oktober wechseln",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        ws = db_session.query(WheelSet).filter_by(
            license_plate="M-KM 4321").first()
        assert ws is not None
        assert ws.tire_manufacturer == "Continental"
        assert ws.tire_size == "205/55 R16"
        assert ws.tire_age == "2022"
        assert ws.season == "winter"
        assert ws.rim_type == "stahl"
        assert ws.exchange_note == "Im Oktober wechseln"

    def test_create_ignores_tire_details_when_flag_off(
        self, client, seed_settings, db_session
    ):
        # flag off by default
        tok = _csrf(client)
        client.post("/wheelsets/new", data={
            "_csrf_token": tok,
            "customer_name": "Hans",
            "license_plate": "B-HH 99",
            "car_type": "VW Polo",
            "storage_position": "C1LOM",
            "tire_manufacturer": "ShouldBeIgnored",
            "season": "sommer",
        }, follow_redirects=True)
        db_session.expire_all()
        ws = db_session.query(WheelSet).filter_by(
            license_plate="B-HH 99").first()
        assert ws is not None
        assert ws.tire_manufacturer is None
        assert ws.season is None

    def test_season_invalid_value_stored_as_none(
        self, client, seed_settings, db_session
    ):
        _enable_tire_details(db_session, seed_settings)
        tok = _csrf(client)
        client.post("/wheelsets/new", data={
            "_csrf_token": tok,
            "customer_name": "Eva",
            "license_plate": "HH-EV 1",
            "car_type": "Mini",
            "storage_position": "C1LOM",
            "season": "herbst",  # invalid value
        }, follow_redirects=True)
        db_session.expire_all()
        ws = db_session.query(WheelSet).filter_by(
            license_plate="HH-EV 1").first()
        assert ws is not None
        assert ws.season is None

    def test_rim_type_invalid_value_stored_as_none(
        self, client, seed_settings, db_session
    ):
        _enable_tire_details(db_session, seed_settings)
        tok = _csrf(client)
        client.post("/wheelsets/new", data={
            "_csrf_token": tok,
            "customer_name": "Karl",
            "license_plate": "S-KK 2",
            "car_type": "Opel",
            "storage_position": "C1LOM",
            "rim_type": "carbon",  # invalid value
        }, follow_redirects=True)
        db_session.expire_all()
        ws = db_session.query(WheelSet).filter_by(
            license_plate="S-KK 2").first()
        assert ws is not None
        assert ws.rim_type is None


# ── Phase 2D: Routes — edit ─────────────────────────────────────────────────

class TestEditWheelsetTireDetails:
    def test_edit_form_shows_tire_details_when_flag_on(
        self, client, seed_wheelset, seed_settings, db_session
    ):
        _enable_tire_details(db_session, seed_settings)
        resp = client.get(
            f"/wheelsets/{seed_wheelset.id}/edit")
        assert resp.status_code == 200
        assert b"tire_manufacturer" in resp.data

    def test_edit_form_hides_tire_details_when_flag_off(
        self, client, seed_wheelset, seed_settings
    ):
        resp = client.get(
            f"/wheelsets/{seed_wheelset.id}/edit")
        assert resp.status_code == 200
        assert b"tire_manufacturer" not in resp.data

    def test_edit_saves_tire_details(
        self, client, seed_wheelset, seed_settings, db_session
    ):
        _enable_tire_details(db_session, seed_settings)
        tok = _csrf(client)
        resp = client.post(
            f"/wheelsets/{seed_wheelset.id}/edit", data={
                "_csrf_token": tok,
                "customer_name": seed_wheelset.customer_name,
                "license_plate": seed_wheelset.license_plate,
                "car_type": seed_wheelset.car_type,
                "storage_position": seed_wheelset.storage_position,
                "tire_manufacturer": "Pirelli",
                "tire_size": "215/65 R17",
                "tire_age": "2020",
                "season": "sommer",
                "rim_type": "alu",
                "exchange_note": "Vor Sommerurlaub",
            }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        ws = db_session.get(WheelSet, seed_wheelset.id)
        assert ws.tire_manufacturer == "Pirelli"
        assert ws.season == "sommer"
        assert ws.rim_type == "alu"
        assert ws.exchange_note == "Vor Sommerurlaub"

    def test_edit_clears_tire_details_when_blanked(
        self, client, seed_settings, db_session
    ):
        """Submitting empty strings should store None, not empty strings."""
        _enable_tire_details(db_session, seed_settings)
        ws = WheelSet(
            customer_name="Pre-filled", license_plate="K-PF 1",
            car_type="Ford", storage_position="C1LOM",
            tire_manufacturer="Bridgestone", season="winter",
        )
        db_session.add(ws)
        db_session.commit()
        tok = _csrf(client)
        client.post(f"/wheelsets/{ws.id}/edit", data={
            "_csrf_token": tok,
            "customer_name": ws.customer_name,
            "license_plate": ws.license_plate,
            "car_type": ws.car_type,
            "storage_position": ws.storage_position,
            "tire_manufacturer": "",  # cleared
            "season": "",             # cleared
        }, follow_redirects=True)
        db_session.expire_all()
        ws = db_session.get(WheelSet, ws.id)
        assert ws.tire_manufacturer is None
        assert ws.season is None


# ── Phase 2E: List template badges ─────────────────────────────────────────

class TestWheelsetListTireDetails:
    def test_list_shows_season_badge_when_flag_on(
        self, client, seed_settings, db_session
    ):
        _enable_tire_details(db_session, seed_settings)
        ws = WheelSet(
            customer_name="Badge User", license_plate="N-BU 1",
            car_type="VW", storage_position="C1LOM",
            season="winter",
        )
        db_session.add(ws)
        db_session.commit()
        resp = client.get("/wheelsets")
        assert resp.status_code == 200
        assert "Winter".encode() in resp.data

    def test_list_hides_season_badge_when_flag_off(
        self, client, seed_settings, db_session
    ):
        ws = WheelSet(
            customer_name="NoFlag User", license_plate="N-NF 1",
            car_type="VW", storage_position="C1LOM",
            season="winter",
        )
        db_session.add(ws)
        db_session.commit()
        resp = client.get("/wheelsets")
        # Season badge is rendered via i18n key lookup; without flag the
        # Jinja block is not rendered at all.
        assert b"wf_season_winter" not in resp.data

    def test_list_shows_rim_badge_when_flag_on(
        self, client, seed_settings, db_session
    ):
        _enable_tire_details(db_session, seed_settings)
        ws = WheelSet(
            customer_name="Rim User", license_plate="N-RM 1",
            car_type="BMW", storage_position="C1LOM",
            rim_type="alu",
        )
        db_session.add(ws)
        db_session.commit()
        resp = client.get("/wheelsets")
        assert "Alufelge".encode() in resp.data


# ── Phase 2F: i18n keys ─────────────────────────────────────────────────────

class TestTireDetailsI18n:
    _EXPECTED_KEYS = [
        "wf_tire_details_section",
        "wf_tire_manufacturer",
        "wf_tire_size",
        "wf_tire_age",
        "wf_season",
        "wf_season_sommer",
        "wf_season_winter",
        "wf_season_allwetter",
        "wf_rim_type",
        "wf_rim_stahl",
        "wf_rim_alu",
        "wf_exchange_note",
    ]

    def test_all_keys_present_in_catalogue(self):
        from tsm.i18n import _CATALOGUE
        for key in self._EXPECTED_KEYS:
            assert key in _CATALOGUE, f"Missing i18n key: {key}"

    def test_all_keys_have_de_and_en(self):
        from tsm.i18n import _CATALOGUE
        for key in self._EXPECTED_KEYS:
            entry = _CATALOGUE[key]
            assert entry.get("de"), f"Missing 'de' for {key}"
            assert entry.get("en"), f"Missing 'en' for {key}"

    def test_season_sommer_de(self):
        from tsm.i18n import gettext
        assert gettext("wf_season_sommer") == "Sommer"

    def test_season_winter_de(self):
        from tsm.i18n import gettext
        assert gettext("wf_season_winter") == "Winter"

    def test_rim_stahl_de(self):
        from tsm.i18n import gettext
        assert gettext("wf_rim_stahl") == "Stahlfelge"

    def test_rim_alu_en(self, app):
        from flask import g
        with app.test_request_context("/"):
            g._tsm_locale = "en"
            from tsm.i18n import gettext
            assert gettext("wf_rim_alu") == "Alloy rim"


# ── Phase 2G: overdue_season() utility ──────────────────────────────────────

class TestOverdueSeason:
    """Unit tests for tsm.utils.overdue_season — no Flask needed.

    Overdue windows:
      Jan–Apr (1–4): sommer tires overdue (should have left by Dec)
      Jul–Sep (7–9): winter tires overdue (should have left by Jun)
      May–Jun (5–6): swap window winter→summer, nothing overdue
      Oct–Dec (10–12): swap window summer→winter, nothing overdue
    """

    # ── Sommer overdue (Jan–Apr) ──
    def test_january_sommer_overdue(self):
        assert overdue_season(1) == "sommer"

    def test_april_sommer_overdue(self):
        assert overdue_season(4) == "sommer"

    def test_march_sommer_overdue(self):
        assert overdue_season(3) == "sommer"

    # ── Winter overdue (Jul–Sep) ──
    def test_july_winter_overdue(self):
        assert overdue_season(7) == "winter"

    def test_september_winter_overdue(self):
        assert overdue_season(9) == "winter"

    def test_august_winter_overdue(self):
        assert overdue_season(8) == "winter"

    # ── Swap windows — nothing overdue ──
    def test_may_no_overdue(self):
        assert overdue_season(5) is None

    def test_june_no_overdue(self):
        assert overdue_season(6) is None

    def test_october_no_overdue(self):
        assert overdue_season(10) is None

    def test_november_no_overdue(self):
        assert overdue_season(11) is None

    def test_december_no_overdue(self):
        assert overdue_season(12) is None


# ── Phase 2H: overdue in route / template ───────────────────────────────────

class TestOverdueInList:
    def _seed_ws(self, db_session, plate, position, season):
        ws = WheelSet(
            customer_name="Overdue Tester",
            license_plate=plate,
            car_type="Golf",
            storage_position=position,
            season=season,
        )
        db_session.add(ws)
        db_session.commit()
        return ws

    def test_no_overdue_when_tire_details_disabled(
        self, client, seed_settings, db_session, monkeypatch
    ):
        """overdue_ids must be empty when enable_tire_details is off."""
        self._seed_ws(db_session, "B-OD 1", "C1LOM", "sommer")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=2))
        resp = client.get("/wheelsets")
        assert resp.status_code == 200
        assert b"overdue-row" not in resp.data

    def test_sommer_overdue_in_january(
        self, client, seed_settings, db_session, monkeypatch
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 2", "C1LOM", "sommer")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=1))
        resp = client.get("/wheelsets")
        assert b"overdue-row" in resp.data

    def test_sommer_overdue_in_april(
        self, client, seed_settings, db_session, monkeypatch
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 3", "C1LOM", "sommer")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=4))
        resp = client.get("/wheelsets")
        assert b"overdue-row" in resp.data

    def test_winter_overdue_in_july(
        self, client, seed_settings, db_session, monkeypatch
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 4", "C1LOM", "winter")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=7))
        resp = client.get("/wheelsets")
        assert b"overdue-row" in resp.data

    def test_winter_overdue_in_september(
        self, client, seed_settings, db_session, monkeypatch
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 5", "C1LOM", "winter")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=9))
        resp = client.get("/wheelsets")
        assert b"overdue-row" in resp.data

    def test_no_overdue_in_may_for_winter(
        self, client, seed_settings, db_session, monkeypatch
    ):
        """May is swap window — winter tires still acceptable."""
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 6", "C1LOM", "winter")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=5))
        resp = client.get("/wheelsets")
        assert b"overdue-row" not in resp.data

    def test_no_overdue_in_june_for_winter(
        self, client, seed_settings, db_session, monkeypatch
    ):
        """June is last grace month for winter→summer swap."""
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 7", "C1LOM", "winter")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=6))
        resp = client.get("/wheelsets")
        assert b"overdue-row" not in resp.data

    def test_no_overdue_in_october_for_sommer(
        self, client, seed_settings, db_session, monkeypatch
    ):
        """October is swap window — summer tires still acceptable."""
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 8", "C1LOM", "sommer")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=10))
        resp = client.get("/wheelsets")
        assert b"overdue-row" not in resp.data

    def test_no_overdue_in_december_for_sommer(
        self, client, seed_settings, db_session, monkeypatch
    ):
        """December is last grace month for summer→winter swap."""
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 9", "C1LOM", "sommer")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=12))
        resp = client.get("/wheelsets")
        assert b"overdue-row" not in resp.data

    def test_allwetter_never_overdue(
        self, client, seed_settings, db_session, monkeypatch
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 10", "C1LOM", "allwetter")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=2))
        resp = client.get("/wheelsets")
        assert b"overdue-row" not in resp.data

    def test_season_icons_rendered(
        self, client, seed_settings, db_session
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-IC 1", "C1LOM", "winter")
        resp = client.get("/wheelsets")
        assert b"bi-snow" in resp.data

    def test_sun_icon_for_sommer(
        self, client, seed_settings, db_session
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-IC 2", "C1LOM", "sommer")
        resp = client.get("/wheelsets")
        assert b"bi-sun-fill" in resp.data

    def test_cloud_icon_for_allwetter(
        self, client, seed_settings, db_session
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-IC 3", "C1LOM", "allwetter")
        resp = client.get("/wheelsets")
        assert b"bi-cloud-drizzle-fill" in resp.data

    def test_overdue_warning_icon_in_customer_column(
        self, client, seed_settings, db_session, monkeypatch
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        self._seed_ws(db_session, "B-OD 11", "C1LOM", "sommer")
        import tsm.routes as r
        monkeypatch.setattr(r, "datetime", _FakeDatetime(month=2))
        resp = client.get("/wheelsets")
        assert b"bi-exclamation-triangle-fill" in resp.data

    def test_exchange_note_shown_as_title_attribute(
        self, client, seed_settings, db_session
    ):
        seed_settings.enable_tire_details = True
        db_session.commit()
        ws = WheelSet(
            customer_name="Note User", license_plate="B-NT 1",
            car_type="BMW", storage_position="C1LOM",
            season="sommer", exchange_note="Im Oktober wechseln",
        )
        db_session.add(ws)
        db_session.commit()
        resp = client.get("/wheelsets")
        assert b"Im Oktober wechseln" in resp.data


# ── Fake datetime helper ─────────────────────────────────────────────────────

class _FakeDatetime:
    """Minimal datetime stub: only .now() is needed by the route."""
    def __init__(self, month: int):
        self._month = month

    def now(self):
        class _Fake:
            pass
        obj = _Fake()
        obj.month = self._month
        return obj

    # pass-through for anything else (fromtimestamp used in backups view)
    @staticmethod
    def fromtimestamp(ts):
        from datetime import datetime
        return datetime.fromtimestamp(ts)
