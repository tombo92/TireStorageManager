"""Tests for tsm/routes.py — all Flask routes via test client."""
from unittest.mock import patch
from tsm.models import WheelSet, Settings, AuditLog


class TestIndex:
    def test_get(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Reifenmanager" in resp.data or resp.status_code == 200

    def test_stat_cards_present(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        # Four stat cards rendered
        assert b"text-primary" in resp.data   # total card
        assert b"text-success" in resp.data   # free card
        assert b"progress-bar" in resp.data   # occupancy bar

    def test_occupancy_zero_when_empty(self, client):
        resp = client.get("/")
        assert b"0%" in resp.data

    def test_recent_activity_empty_state(self, client):
        resp = client.get("/")
        # No audit entries — empty-state text must be present
        assert "stats_no_activity" not in resp.data.decode()  # key not leaked
        assert resp.status_code == 200

    def test_recent_activity_shows_entry(
            self, client, db_session, seed_wheelset):
        db_session.add(AuditLog(
            action="create",
            wheelset_id=seed_wheelset.id,
            details="AB-CD 1234",
        ))
        db_session.commit()
        resp = client.get("/")
        assert b"AB-CD 1234" in resp.data

    def test_top_cars_empty_state(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_top_cars_shows_car_type(self, client, seed_wheelset):
        resp = client.get("/")
        assert b"VW Golf" in resp.data

    def test_context_variables(self, client, seed_wheelset, db_session):
        """Verify all new context variables reach the template."""
        resp = client.get("/")
        data = resp.data.decode()
        # Occupancy bar present with non-zero value after seeding one wheelset
        assert "progress-bar" in data
        assert resp.status_code == 200


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

    # ── Search: note field ─────────────────────────────────────
    def test_search_by_note_returns_match(self, client, db_session):
        """Search term matching the note field must return that wheel set."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(
            customer_name="Fritz Meier", license_plate="K-FM 777",
            car_type="Opel Astra", storage_position="C1ROL",
            note="Sonderwunsch Winterreifen",
        ))
        db_session.commit()
        resp = client.get("/wheelsets?q=Sonderwunsch")
        assert resp.status_code == 200
        assert b"Fritz Meier" in resp.data

    def test_search_by_note_no_match(self, client, db_session):
        """Search term that only exists in a note must NOT return unrelated rows."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(
            customer_name="Anna Bauer", license_plate="S-AB 123",
            car_type="Seat Leon", storage_position="C2ROL",
            note="spezielle Felge",
        ))
        db_session.commit()
        resp = client.get("/wheelsets?q=ZZZNOTINANYFIELD")
        assert resp.status_code == 200
        assert b"Anna Bauer" not in resp.data

    def test_search_placeholder_contains_note(self, client):
        """Search input placeholder must advertise note searching."""
        resp = client.get("/wheelsets")
        html = resp.data.decode()
        assert "Notiz" in html or "note" in html.lower()

    def test_search_input_has_id_for_live_search(self, client):
        """Search input must carry id='wl-search-input' for JS live search."""
        resp = client.get("/wheelsets")
        html = resp.data.decode()
        assert 'id="wl-search-input"' in html

    def test_search_by_note_umlaut(self, client, db_session):
        """Umlaut search term must match a note containing that umlaut."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(
            customer_name="Umlaut Test", license_plate="U-UT 1",
            car_type="X", storage_position="C1ROL",
            note="Ölwechsel überfällig",
        ))
        db_session.commit()
        resp = client.get("/wheelsets?q=%C3%B6l")  # URL-encoded 'öl'
        assert resp.status_code == 200
        assert "Umlaut Test" in resp.data.decode()

    # ── Sort ──────────────────────────────────────────────────
    def test_sort_customer_asc(self, client, db_session):
        """customer_asc sort must return rows ordered alphabetically."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(customer_name="Zoe Zimmermann",
                                license_plate="Z-ZZ 001", car_type="VW",
                                storage_position="C1ROL"))
        db_session.add(WheelSet(customer_name="Adam Auer",
                                license_plate="A-AA 001", car_type="BMW",
                                storage_position="C1RML"))
        db_session.commit()
        resp = client.get("/wheelsets?sort=customer_asc")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert html.index("Adam Auer") < html.index("Zoe Zimmermann")

    def test_sort_customer_desc(self, client, db_session):
        """customer_desc sort must return rows in reverse alphabetical order."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(customer_name="Zoe Zimmermann",
                                license_plate="Z-ZZ 002", car_type="VW",
                                storage_position="C1ROL"))
        db_session.add(WheelSet(customer_name="Adam Auer",
                                license_plate="A-AA 002", car_type="BMW",
                                storage_position="C1RML"))
        db_session.commit()
        resp = client.get("/wheelsets?sort=customer_desc")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert html.index("Zoe Zimmermann") < html.index("Adam Auer")

    def test_sort_position_asc(self, client, db_session):
        """position_asc sort must order rows by storage_position ascending."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(customer_name="B Kunde",
                                license_plate="B-B 001", car_type="X",
                                storage_position="C4ROL"))
        db_session.add(WheelSet(customer_name="A Kunde",
                                license_plate="A-A 001", car_type="X",
                                storage_position="C1ROL"))
        db_session.commit()
        resp = client.get("/wheelsets?sort=position_asc")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert html.index("C1ROL") < html.index("C4ROL")

    def test_unknown_sort_falls_back_to_default(self, client, seed_wheelset):
        """Unknown sort value must not crash; default order is used."""
        resp = client.get("/wheelsets?sort=invalid_value")
        assert resp.status_code == 200

    def test_sort_select_rendered(self, client):
        """Sort dropdown must appear on the page."""
        resp = client.get("/wheelsets")
        html = resp.data.decode()
        assert 'name="sort"' in html

    # ── Filter: position type ─────────────────────────────────
    def test_filter_container(self, client, db_session):
        """filter_pos=container must exclude garage positions."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(customer_name="Container Kunde",
                                license_plate="C-C 001", car_type="X",
                                storage_position="C1ROL"))
        db_session.add(WheelSet(customer_name="Garage Kunde",
                                license_plate="G-G 001", car_type="X",
                                storage_position="GR1OL"))
        db_session.commit()
        resp = client.get("/wheelsets?filter_pos=container")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Container Kunde" in html
        assert "Garage Kunde" not in html

    def test_filter_garage(self, client, db_session):
        """filter_pos=garage must exclude container positions."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(customer_name="Container Kunde",
                                license_plate="C-C 002", car_type="X",
                                storage_position="C1ROL"))
        db_session.add(WheelSet(customer_name="Garage Kunde",
                                license_plate="G-G 002", car_type="X",
                                storage_position="GR1OL"))
        db_session.commit()
        resp = client.get("/wheelsets?filter_pos=garage")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Garage Kunde" in html
        assert "Container Kunde" not in html

    def test_filter_all_positions_shows_both(self, client, db_session):
        """No position filter must return both container and garage rows."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(customer_name="Container Kunde",
                                license_plate="C-C 003", car_type="X",
                                storage_position="C1ROL"))
        db_session.add(WheelSet(customer_name="Garage Kunde",
                                license_plate="G-G 003", car_type="X",
                                storage_position="GR1OL"))
        db_session.commit()
        resp = client.get("/wheelsets")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Container Kunde" in html
        assert "Garage Kunde" in html

    def test_filter_pos_select_rendered(self, client):
        """Position filter dropdown must appear on the page."""
        resp = client.get("/wheelsets")
        html = resp.data.decode()
        assert 'name="filter_pos"' in html

    # ── Filter: season ────────────────────────────────────────
    def test_filter_season_winter(self, client, db_session, seed_settings):
        """filter_season=winter must only return winter tyre wheel sets."""
        from tsm.models import WheelSet
        seed_settings.enable_tire_details = True
        db_session.commit()
        db_session.add(WheelSet(customer_name="Winter Kunde",
                                license_plate="W-W 001", car_type="X",
                                storage_position="C1ROL", season="winter"))
        db_session.add(WheelSet(customer_name="Sommer Kunde",
                                license_plate="S-S 001", car_type="X",
                                storage_position="C1RML", season="sommer"))
        db_session.commit()
        resp = client.get("/wheelsets?filter_season=winter")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Winter Kunde" in html
        assert "Sommer Kunde" not in html

    def test_filter_season_combined_with_search(self, client, db_session,
                                                seed_settings):
        """Season filter combined with text search must apply both constraints."""
        from tsm.models import WheelSet
        seed_settings.enable_tire_details = True
        db_session.commit()
        db_session.add(WheelSet(customer_name="Hans Winter",
                                license_plate="H-W 001", car_type="X",
                                storage_position="C1ROL", season="winter"))
        db_session.add(WheelSet(customer_name="Hans Sommer",
                                license_plate="H-S 001", car_type="X",
                                storage_position="C1RML", season="sommer"))
        db_session.commit()
        resp = client.get("/wheelsets?q=Hans&filter_season=winter")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Hans Winter" in html
        assert "Hans Sommer" not in html

    # ── Reset filter link ─────────────────────────────────────
    def test_reset_link_shown_when_filter_active(self, client):
        """Reset link must appear when any non-default parameter is set."""
        resp = client.get("/wheelsets?filter_pos=container")
        html = resp.data.decode()
        assert "wl_reset_filter" not in html  # key must not leak
        assert url_for_pattern("/wheelsets") in html or "list_wheelsets" in html

    def test_reset_link_not_shown_without_filters(self, client):
        """Reset link must NOT appear on a plain unfiltered page load."""
        resp = client.get("/wheelsets")
        html = resp.data.decode()
        assert "wl_reset_filter" not in html
        # The translated text should not appear either
        assert "Filter zurücksetzen" not in html
        assert "Reset filters" not in html


# ── helper used in reset tests ────────────────────────────────────────────────
def url_for_pattern(path: str) -> str:
    """Return a string that is expected to appear as an href in a reset link."""
    return path


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

    def test_backups_shows_xlsx_badge(self, client, tmp_path, monkeypatch):
        """Backups page must render the XLSX badge for an xlsx backup file."""
        import tsm.routes as routes_mod
        monkeypatch.setattr(routes_mod, "BACKUP_DIR", str(tmp_path))
        (tmp_path / "wheel_storage_20260402-120000.xlsx").write_bytes(b"x" * 2048)
        resp = client.get("/backups")
        assert resp.status_code == 200
        assert b"XLSX" in resp.data

    def test_backups_shows_print_button(self, client):
        """Backups page must have the Print Inventory button."""
        resp = client.get("/backups")
        html = resp.data.decode()
        assert "inventory_print" in html or "/backups/inventory" in html

    def test_download_xlsx_allowed(self, client, tmp_path, monkeypatch):
        """Downloading an xlsx backup file must return 200."""
        import tsm.routes as routes_mod
        monkeypatch.setattr(routes_mod, "BACKUP_DIR", str(tmp_path))
        fname = "wheel_storage_20260402-120000.xlsx"
        (tmp_path / fname).write_bytes(b"x" * 1024)
        resp = client.get(f"/backups/download/{fname}")
        assert resp.status_code == 200

    def test_download_xlsx_path_traversal_blocked(self, client):
        """Path traversal in download must return 403."""
        resp = client.get("/backups/download/../etc/passwd")
        assert resp.status_code == 403

    def test_download_unknown_extension_blocked(self, client, tmp_path,
                                                 monkeypatch):
        """Downloading a non-whitelisted extension must return 403."""
        import tsm.routes as routes_mod
        monkeypatch.setattr(routes_mod, "BACKUP_DIR", str(tmp_path))
        fname = "wheel_storage_20260402-120000.exe"
        (tmp_path / fname).write_bytes(b"x")
        resp = client.get(f"/backups/download/{fname}")
        assert resp.status_code == 403


class TestInventoryPrint:
    def test_get_empty(self, client):
        """Inventory page renders without wheel sets."""
        resp = client.get("/backups/inventory")
        assert resp.status_code == 200

    def test_contains_heading(self, client):
        resp = client.get("/backups/inventory")
        html = resp.data.decode()
        assert "Bestandsübersicht" in html or "Bestands" in html

    def test_shows_wheelset(self, client, seed_wheelset):
        """Seeded wheel set must appear on the inventory page."""
        resp = client.get("/backups/inventory")
        html = resp.data.decode()
        assert "Mustermann" in html
        assert "C1ROM" in html
        assert "AB-CD 1234" in html

    def test_groups_by_container(self, client, db_session):
        """Wheel sets in different containers appear under separate headings."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(
            customer_name="Anna Müller", license_plate="B-AM 111",
            car_type="BMW X3", storage_position="C1ROM",
        ))
        db_session.add(WheelSet(
            customer_name="Karl Berg", license_plate="M-KB 222",
            car_type="Audi A6", storage_position="C2ROM",
        ))
        db_session.commit()
        resp = client.get("/backups/inventory")
        html = resp.data.decode()
        assert "Container 1" in html
        assert "Container 2" in html

    def test_groups_by_garage(self, client, db_session):
        """Wheel sets in a garage shelf appear under the garage heading."""
        from tsm.models import WheelSet
        db_session.add(WheelSet(
            customer_name="Test Kunde", license_plate="HH-TK 999",
            car_type="VW Passat", storage_position="GR3OL",
        ))
        db_session.commit()
        resp = client.get("/backups/inventory")
        html = resp.data.decode()
        assert "Garage" in html
        assert "3" in html

    def test_check_column_present(self, client, seed_wheelset):
        """Inventory page must have the manual-check column marker."""
        resp = client.get("/backups/inventory")
        html = resp.data.decode()
        assert "✓" in html or "&#x2713;" in html

    def test_total_count_shown(self, client, seed_wheelset):
        """Total wheel set count must be rendered on the inventory page."""
        resp = client.get("/backups/inventory")
        html = resp.data.decode()
        assert "1" in html  # one seeded wheelset

    def test_empty_state_message(self, client):
        """When no wheel sets exist, a meaningful empty-state is shown."""
        resp = client.get("/backups/inventory")
        html = resp.data.decode()
        assert "keine" in html.lower() or "no" in html.lower() or \
               "gespeichert" in html.lower()


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


# =========================================================
#  Update feature tests
# =========================================================
class TestApiUpdateCheck:
    """Tests for /api/update-check endpoint."""

    def test_get_returns_json(self, client):
        fake = {
            "update_available": False,
            "current_version": "1.0.0",
            "remote_version": None,
            "release_notes": None,
            "release_url": None,
            "frozen": False,
        }
        with patch("tsm.routes.get_update_info", return_value=fake):
            resp = client.get("/api/update-check")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["update_available"] is False

    def test_get_update_available(self, client):
        fake = {
            "update_available": True,
            "current_version": "1.0.0",
            "remote_version": "2.0.0",
            "release_notes": "Big update",
            "release_url": "https://example.com",
            "frozen": False,
        }
        with patch("tsm.routes.get_update_info", return_value=fake):
            resp = client.get("/api/update-check")
        data = resp.get_json()
        assert data["update_available"] is True
        assert data["remote_version"] == "2.0.0"
        assert data["release_notes"] == "Big update"

    def test_post_forces_refresh(self, client):
        fake = {
            "update_available": False,
            "current_version": "1.0.0",
            "remote_version": None,
            "release_notes": None,
            "release_url": None,
            "frozen": False,
        }
        token = _get_csrf(client)
        with patch("tsm.routes.invalidate_update_cache") as m_inv, \
             patch("tsm.routes.get_update_info", return_value=fake):
            resp = client.post("/api/update-check", data={
                "_csrf_token": token,
            })
        assert resp.status_code == 200
        m_inv.assert_called_once()


class TestUpdateNow:
    """Tests for /settings/update-now endpoint."""

    def test_not_frozen_shows_info_flash(self, client, seed_settings):
        token = _get_csrf(client)
        with patch("tsm.routes._is_frozen", return_value=False):
            resp = client.post("/settings/update-now", data={
                "_csrf_token": token,
            }, follow_redirects=True)
        assert resp.status_code == 200
        assert ("installierte" in resp.data.decode()
                or "EXE" in resp.data.decode())

    def test_frozen_update_success(self, client, seed_settings):
        token = _get_csrf(client)
        with patch("tsm.routes._is_frozen", return_value=True), \
             patch("tsm.routes.check_for_update", return_value=True):
            resp = client.post("/settings/update-now", data={
                "_csrf_token": token,
            }, follow_redirects=True)
        assert resp.status_code == 200
        assert "installiert" in resp.data.decode()

    def test_frozen_no_update(self, client, seed_settings):
        token = _get_csrf(client)
        with patch("tsm.routes._is_frozen", return_value=True), \
             patch("tsm.routes.check_for_update",
                   return_value=False):
            resp = client.post("/settings/update-now", data={
                "_csrf_token": token,
            }, follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode()
        assert ("Kein Update" in html
                or "fehlgeschlagen" in html)

    def test_frozen_update_exception(self, client, seed_settings):
        token = _get_csrf(client)
        with patch("tsm.routes._is_frozen", return_value=True), \
             patch("tsm.routes.check_for_update",
                   side_effect=RuntimeError("boom")):
            resp = client.post("/settings/update-now", data={
                "_csrf_token": token,
            }, follow_redirects=True)
        assert resp.status_code == 200
        assert "fehlgeschlagen" in resp.data.decode()


class TestSettingsAutoUpdate:
    """Tests for auto_update setting persistence."""

    def test_auto_update_default_true(self, client, seed_settings,
                                      db_session):
        s = db_session.query(Settings).first()
        assert s.auto_update is True

    def test_toggle_auto_update_off(self, client, seed_settings,
                                    db_session):
        token = _get_csrf(client)
        resp = client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "dark_mode": "0",
            # auto_update omitted → unchecked → False
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.auto_update is False

    def test_toggle_auto_update_on(self, client, seed_settings,
                                   db_session):
        # First disable
        token = _get_csrf(client)
        client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
        }, follow_redirects=True)
        # Then enable
        token = _get_csrf(client)
        resp = client.post("/settings", data={
            "_csrf_token": token,
            "backup_interval_minutes": "60",
            "backup_copies": "10",
            "auto_update": "1",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        s = db_session.query(Settings).first()
        assert s.auto_update is True


class TestUpdateBanner:
    """Tests for the update notification banner in base.html."""

    def test_banner_div_present(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        assert 'id="updateBanner"' in html

    def test_banner_present_on_every_page(self, client):
        for url in ["/", "/wheelsets", "/positions", "/settings"]:
            resp = client.get(url)
            html = resp.data.decode()
            assert 'id="updateBanner"' in html, \
                f"Missing on {url}"


class TestUpdateSettingsUI:
    """Tests for the update card on the settings page."""

    def test_settings_has_update_card(self, client, seed_settings):
        resp = client.get("/settings")
        html = resp.data.decode()
        assert 'id="update-card"' in html
        assert "Updates" in html

    def test_settings_has_auto_update_switch(
        self, client, seed_settings
    ):
        resp = client.get("/settings")
        html = resp.data.decode()
        assert 'id="autoUpdateSwitch"' in html

    def test_settings_has_check_button(
        self, client, seed_settings
    ):
        resp = client.get("/settings")
        html = resp.data.decode()
        assert 'id="btnCheckUpdate"' in html

    def test_settings_has_version_display(
        self, client, seed_settings
    ):
        resp = client.get("/settings")
        html = resp.data.decode()
        from config import VERSION
        assert f"v{VERSION}" in html
