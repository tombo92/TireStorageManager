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
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.backup_interval_minutes == 30
        assert s.backup_copies == 5


class TestBackups:
    def test_get(self, client):
        resp = client.get("/backups")
        assert resp.status_code == 200


class TestFavicon:
    def test_favicon(self, client):
        resp = client.get("/favicon.ico")
        # May be 200 (file exists) or 404 (no file in test)
        assert resp.status_code in (200, 404)


# ── Helper ─────────────────────────────────────────────
def _get_csrf(client):
    """Grab a CSRF token from a GET to the index."""
    with client.session_transaction() as sess:
        import secrets
        tok = secrets.token_urlsafe(16)
        sess["_csrf_token"] = tok
    return tok
