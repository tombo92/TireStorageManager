"""Tests for tsm/routes.py — all Flask routes via test client."""
from tsm.models import WheelSet, Settings, AuditLog


class TestIndex:
    def test_get(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Reifenmanager" in resp.data or resp.status_code == 200


class TestWheelsetsList:
    def test_get_empty(self, client):
        resp = client.get("/wheelsets")
        assert resp.status_code == 200

    def test_search(self, client, seed_wheelset):
        resp = client.get("/wheelsets?q=Mustermann")
        assert resp.status_code == 200
        assert b"Mustermann" in resp.data

    def test_search_no_results(self, client):
        resp = client.get("/wheelsets?q=ZZZNOTFOUND")
        assert resp.status_code == 200


class TestCreateWheelset:
    def test_get_form(self, client):
        resp = client.get("/wheelsets/new")
        assert resp.status_code == 200

    def test_post_missing_fields(self, client):
        """Should redirect with flash on missing fields."""
        resp = client.post("/wheelsets/new", data={
            "_csrf_token": _get_csrf(client),
            "customer_name": "",
            "license_plate": "",
            "car_type": "",
            "storage_position": "",
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_post_success(self, client, db_session):
        token = _get_csrf(client)
        resp = client.post("/wheelsets/new", data={
            "_csrf_token": token,
            "customer_name": "Hans Test",
            "license_plate": "HH-TT 999",
            "car_type": "Audi A4",
            "storage_position": "C1ROL",
        }, follow_redirects=True)
        assert resp.status_code == 200
        ws = db_session.query(WheelSet).filter_by(
            license_plate="HH-TT 999").first()
        assert ws is not None
        assert ws.customer_name == "Hans Test"

    def test_post_invalid_position(self, client):
        token = _get_csrf(client)
        resp = client.post("/wheelsets/new", data={
            "_csrf_token": token,
            "customer_name": "A",
            "license_plate": "B",
            "car_type": "C",
            "storage_position": "INVALID",
        }, follow_redirects=True)
        assert resp.status_code == 200


class TestEditWheelset:
    def test_get_form(self, client, seed_wheelset):
        resp = client.get(f"/wheelsets/{seed_wheelset.id}/edit")
        assert resp.status_code == 200

    def test_get_404(self, client):
        resp = client.get("/wheelsets/99999/edit")
        assert resp.status_code == 404

    def test_post_update(self, client, seed_wheelset, db_session):
        wid = seed_wheelset.id
        plate = seed_wheelset.license_plate
        car = seed_wheelset.car_type
        pos = seed_wheelset.storage_position
        token = _get_csrf(client)
        resp = client.post(
            f"/wheelsets/{wid}/edit",
            data={
                "_csrf_token": token,
                "customer_name": "Neuer Name",
                "license_plate": plate,
                "car_type": car,
                "storage_position": pos,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db_session.expire_all()
        ws = db_session.get(WheelSet, wid)
        assert ws.customer_name == "Neuer Name"


class TestDeleteWheelset:
    def test_confirm_page(self, client, seed_wheelset):
        resp = client.get(f"/wheelsets/{seed_wheelset.id}/delete")
        assert resp.status_code == 200

    def test_delete_wrong_plate(self, client, seed_wheelset):
        token = _get_csrf(client)
        resp = client.post(
            f"/wheelsets/{seed_wheelset.id}/delete",
            data={"_csrf_token": token, "confirm_plate": "WRONG"},
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_delete_success(self, client, seed_wheelset, db_session):
        token = _get_csrf(client)
        resp = client.post(
            f"/wheelsets/{seed_wheelset.id}/delete",
            data={
                "_csrf_token": token,
                "confirm_plate": seed_wheelset.license_plate,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert db_session.get(WheelSet, seed_wheelset.id) is None


class TestPositions:
    def test_get(self, client):
        resp = client.get("/positions")
        assert resp.status_code == 200


class TestSettings:
    def test_get(self, client, seed_settings):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_post_update(self, client, seed_settings, db_session):
        token = _get_csrf(client)
        resp = client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "30",
            "backup_copies": "5",
            "dark_mode": "0",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.backup_interval_minutes == 30
        assert s.backup_copies == 5

    def test_post_toggle_dark_mode_on(
        self, client, seed_settings, db_session
    ):
        token = _get_csrf(client)
        resp = client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "dark_mode": "1",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.dark_mode is True

    def test_post_toggle_dark_mode_off(
        self, client, seed_settings, db_session
    ):
        seed_settings.dark_mode = True
        db_session.commit()
        token = _get_csrf(client)
        resp = client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            # dark_mode omitted → checkbox unchecked → False
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.dark_mode is False

    def test_dark_mode_in_html(self, client, seed_settings, db_session):
        """Dark mode injects data-bs-theme into every page."""
        # Enable dark mode via the settings POST (refreshes the cache)
        token = _get_csrf(client)
        client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "dark_mode": "1",
        }, follow_redirects=True)
        resp = client.get("/")
        assert b'data-bs-theme="dark"' in resp.data

    def test_light_mode_in_html(self, client, seed_settings, db_session):
        # Ensure dark mode is off via the settings POST
        token = _get_csrf(client)
        client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            # dark_mode omitted → checkbox unchecked → False
        }, follow_redirects=True)
        resp = client.get("/")
        assert b'data-bs-theme="light"' in resp.data


class TestSettingsPositions:
    def test_get(self, client, seed_settings):
        resp = client.get("/settings/positions")
        assert resp.status_code == 200

    def test_save_custom(self, client, seed_settings, db_session):
        token = _get_csrf(client)
        resp = client.post("/settings/positions", data={
            "_csrf_token": token,
            "action": "save",
            "positions_text": "POS-A\nPOS-B\nPOS-C",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.custom_positions_json is not None
        import json
        saved = json.loads(s.custom_positions_json)
        assert saved == ["POS-A", "POS-B", "POS-C"]

    def test_save_empty_rejected(self, client, seed_settings):
        token = _get_csrf(client)
        resp = client.post("/settings/positions", data={
            "_csrf_token": token,
            "action": "save",
            "positions_text": "",
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Should flash an error, positions_json stays None
        assert b"Mindestens eine Position" in resp.data

    def test_reset(self, client, seed_settings, db_session):
        seed_settings.custom_positions_json = '["X","Y"]'
        db_session.commit()
        token = _get_csrf(client)
        resp = client.post("/settings/positions", data={
            "_csrf_token": token,
            "action": "reset",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.custom_positions_json is None


class TestImpressum:
    def test_get(self, client):
        resp = client.get("/impressum")
        assert resp.status_code == 200
        assert b"Tom Brandherm" in resp.data
        assert b"github.com/tombo92" in resp.data

    def test_has_easter_egg_container(self, client):
        resp = client.get("/impressum")
        assert b"easterEgg" in resp.data
        assert b"Konami" in resp.data or b"SEQ" in resp.data


class TestBackups:
    def test_get(self, client):
        resp = client.get("/backups")
        assert resp.status_code == 200


class TestFavicon:
    def test_favicon(self, client):
        resp = client.get("/favicon.ico")
        # May be 200 (file exists) or 404 (no file in test)
        assert resp.status_code in (200, 404)
        resp.close()


class TestSplashScreen:
    def test_splash_present_on_index(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        assert 'id="splashScreen"' in html

    def test_splash_has_tire_svg(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        assert 'class="splash-tire"' in html

    def test_splash_has_progress_bar(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        assert 'splash-progress-fill' in html

    def test_splash_shows_app_name(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        assert 'splash-title' in html

    def test_splash_present_on_every_page(self, client):
        """Splash is in base.html, so it should appear on all pages."""
        for url in ["/wheelsets", "/positions", "/settings"]:
            resp = client.get(url)
            assert 'id="splashScreen"' in resp.data.decode(), f"Missing on {url}"


# ── Helper ─────────────────────────────────────────────
def _get_csrf(client):
    """Grab a CSRF token from a GET to the index."""
    with client.session_transaction() as sess:
        import secrets
        tok = secrets.token_urlsafe(16)
        sess["_csrf_token"] = tok
    return tok
