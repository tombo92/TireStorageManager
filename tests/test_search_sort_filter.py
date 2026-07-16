"""
Unit & integration tests for the wheelset list search, sort and filter logic.

Tests operate directly against a real SQLAlchemy session (in-memory SQLite)
so they are fast and do not require the Flask request cycle.
"""

from tsm.models import WheelSet


# =========================================================
# Helpers
# =========================================================
def _add(db, name, plate, car, pos, note=None, season=None):
    ws = WheelSet(
        customer_name=name,
        license_plate=plate,
        car_type=car,
        storage_position=pos,
        note=note,
        season=season,
    )
    db.add(ws)
    db.commit()
    return ws


def _search(db, q="", sort="updated_desc", filter_pos="",
            filter_season="", filter_renewal=""):
    """Replicate the query logic from list_wheelsets without Flask."""

    query = db.query(WheelSet)

    if q:
        like = f"%{q}%"
        query = query.filter(
            (WheelSet.customer_name.ilike(like)) |
            (WheelSet.license_plate.ilike(like)) |
            (WheelSet.car_type.ilike(like)) |
            (WheelSet.note.ilike(like))
        )

    if filter_pos == "container":
        query = query.filter(WheelSet.storage_position.like("C%"))
    elif filter_pos == "garage":
        query = query.filter(WheelSet.storage_position.like("GR%"))

    if filter_season:
        query = query.filter(WheelSet.season == filter_season)

    if filter_renewal == "1":
        query = query.filter(WheelSet.tires_need_renewal == True)  # noqa: E712

    sort_map = {
        "updated_desc":  WheelSet.updated_at.desc(),
        "updated_asc":   WheelSet.updated_at.asc(),
        "customer_asc":  WheelSet.customer_name.asc(),
        "customer_desc": WheelSet.customer_name.desc(),
        "plate_asc":     WheelSet.license_plate.asc(),
        "plate_desc":    WheelSet.license_plate.desc(),
        "position_asc":  WheelSet.storage_position.asc(),
        "position_desc": WheelSet.storage_position.desc(),
    }
    order = sort_map.get(sort, WheelSet.updated_at.desc())
    return query.order_by(order).all()


# =========================================================
# Search unit tests
# =========================================================
class TestSearchByNote:
    def test_match_in_note(self, db_session):
        _add(db_session, "Peter Pan", "P-PP 1", "X", "C1ROL",
             note="Sonderbestellung")
        results = _search(db_session, q="Sonderbestellung")
        assert len(results) == 1
        assert results[0].customer_name == "Peter Pan"

    def test_partial_match_in_note(self, db_session):
        _add(db_session, "Lena Müller", "L-LM 1", "X", "C1RML",
             note="besondere Felge")
        results = _search(db_session, q="besondere")
        assert len(results) == 1

    def test_note_search_case_insensitive(self, db_session):
        _add(db_session, "Karl Krause", "K-KK 1", "X", "C2ROL",
             note="WINTERREIFEN GEPRÜFT")
        results = _search(db_session, q="winterreifen")
        assert len(results) == 1

    def test_no_match_in_note(self, db_session):
        _add(db_session, "Anna Bauer", "A-AB 1", "X", "C2RML",
             note="normale Reifen")
        results = _search(db_session, q="ZZZFOUND")
        assert results == []

    def test_search_note_and_name_combined(self, db_session):
        """Term matching the note of one and the name of another returns both."""
        _add(db_session, "Sonderfall Kunde", "S-SK 1", "X", "C1ROL")
        _add(db_session, "Normal Kunde", "N-NK 1", "X", "C1RML",
             note="Sonderfall Muster")
        results = _search(db_session, q="Sonderfall")
        assert len(results) == 2

    def test_null_note_no_crash(self, db_session):
        """Wheel sets with no note (NULL) must not raise an error."""
        _add(db_session, "Null Notiz", "N-NN 1", "X", "C1ROL", note=None)
        results = _search(db_session, q="irgendwas")
        assert isinstance(results, list)

    def test_empty_search_returns_all(self, db_session):
        _add(db_session, "A", "A-A 1", "X", "C1ROL")
        _add(db_session, "B", "B-B 1", "X", "C1RML")
        results = _search(db_session, q="")
        assert len(results) == 2

    # ── Unicode / umlaut search ──────────────────────────────
    def test_umlaut_in_note_lowercase_query(self, db_session):
        """Searching with a lowercase umlaut must match a note with the same
        umlaut (requires Python-level lower(), not SQLite ASCII lower())."""
        _add(db_session, "Umlaut Kunde", "U-U 1", "X", "C1ROL",
             note="Ölwechsel noch offen")
        results = _search(db_session, q="öl")
        assert len(results) == 1

    def test_umlaut_in_note_uppercase_query(self, db_session):
        """Searching with an uppercase umlaut must match (case-insensitive)."""
        _add(db_session, "Umlaut Kunde2", "U-U 2", "X", "C1RML",
             note="schäden am fahrzeug")
        results = _search(db_session, q="Schäden")
        assert len(results) == 1

    def test_umlaut_substring_match(self, db_session):
        """Substring containing an umlaut must match notes containing it."""
        _add(db_session, "Umlaut Kunde3", "U-U 3", "X", "C2ROL",
             note="lange nicht gewechselt – Überfällig")
        results = _search(db_session, q="überfällig")
        assert len(results) == 1

    def test_ascii_substring_still_matches(self, db_session):
        """Plain ASCII substring 'lang' must still match 'lange nicht gewechselt'."""
        _add(db_session, "Ascii Kunde", "A-U 1", "X", "C1ROL",
             note="lange nicht gewechselt")
        results = _search(db_session, q="lang")
        assert len(results) == 1


# =========================================================
# Sort unit tests
# =========================================================
class TestSort:
    def test_customer_asc(self, db_session):
        _add(db_session, "Zeta", "Z-Z 1", "X", "C1ROL")
        _add(db_session, "Alpha", "A-A 1", "X", "C1RML")
        results = _search(db_session, sort="customer_asc")
        assert results[0].customer_name == "Alpha"
        assert results[-1].customer_name == "Zeta"

    def test_customer_desc(self, db_session):
        _add(db_session, "Zeta", "Z-Z 2", "X", "C1ROL")
        _add(db_session, "Alpha", "A-A 2", "X", "C1RML")
        results = _search(db_session, sort="customer_desc")
        assert results[0].customer_name == "Zeta"
        assert results[-1].customer_name == "Alpha"

    def test_plate_asc(self, db_session):
        _add(db_session, "X", "Z-ZZ 99", "X", "C1ROL")
        _add(db_session, "X", "A-AA 01", "X", "C1RML")
        results = _search(db_session, sort="plate_asc")
        assert results[0].license_plate == "A-AA 01"

    def test_plate_desc(self, db_session):
        _add(db_session, "X", "Z-ZZ 98", "X", "C1ROL")
        _add(db_session, "X", "A-AA 02", "X", "C1RML")
        results = _search(db_session, sort="plate_desc")
        assert results[0].license_plate == "Z-ZZ 98"

    def test_position_asc(self, db_session):
        _add(db_session, "X", "P-P 1", "X", "GR1OL")
        _add(db_session, "X", "P-P 2", "X", "C1ROL")
        results = _search(db_session, sort="position_asc")
        # C < G lexicographically
        assert results[0].storage_position == "C1ROL"

    def test_position_desc(self, db_session):
        _add(db_session, "X", "P-P 3", "X", "GR1OL")
        _add(db_session, "X", "P-P 4", "X", "C1ROL")
        results = _search(db_session, sort="position_desc")
        assert results[0].storage_position == "GR1OL"

    def test_invalid_sort_returns_results(self, db_session):
        """An unknown sort key must not raise — falls back to default."""
        _add(db_session, "X", "Q-Q 1", "X", "C1ROL")
        results = _search(db_session, sort="no_such_sort")
        assert len(results) == 1

    def test_updated_desc_default(self, db_session):
        """Default sort (updated_desc) must not crash and returns rows."""
        _add(db_session, "X", "D-D 1", "X", "C1ROL")
        results = _search(db_session, sort="updated_desc")
        assert len(results) == 1


# =========================================================
# Filter unit tests
# =========================================================
class TestFilterPosition:
    def test_container_only(self, db_session):
        _add(db_session, "C Kunde", "C-C 1", "X", "C1ROL")
        _add(db_session, "G Kunde", "G-G 1", "X", "GR1OL")
        results = _search(db_session, filter_pos="container")
        assert all(r.storage_position.startswith("C") for r in results)
        assert len(results) == 1

    def test_garage_only(self, db_session):
        _add(db_session, "C Kunde", "C-C 2", "X", "C1ROL")
        _add(db_session, "G Kunde", "G-G 2", "X", "GR1OL")
        results = _search(db_session, filter_pos="garage")
        assert all(r.storage_position.startswith("GR") for r in results)
        assert len(results) == 1

    def test_no_filter_returns_all(self, db_session):
        _add(db_session, "C Kunde", "C-C 3", "X", "C1ROL")
        _add(db_session, "G Kunde", "G-G 3", "X", "GR1OL")
        results = _search(db_session, filter_pos="")
        assert len(results) == 2

    def test_container_filter_multiple(self, db_session):
        _add(db_session, "A", "A-A 1", "X", "C1ROL")
        _add(db_session, "B", "B-B 1", "X", "C2ROL")
        _add(db_session, "C", "C-C 4", "X", "GR1OL")
        results = _search(db_session, filter_pos="container")
        assert len(results) == 2

    def test_unknown_filter_returns_all(self, db_session):
        """An unrecognised filter_pos value must fall through to no filter."""
        _add(db_session, "X", "X-X 1", "X", "C1ROL")
        # 'unknown' is not 'container' or 'garage', so no filter applied
        results = _search(db_session, filter_pos="unknown")
        assert len(results) == 1


class TestFilterSeason:
    def test_winter_only(self, db_session):
        _add(db_session, "W", "W-W 1", "X", "C1ROL", season="winter")
        _add(db_session, "S", "S-S 1", "X", "C1RML", season="sommer")
        results = _search(db_session, filter_season="winter")
        assert len(results) == 1
        assert results[0].season == "winter"

    def test_sommer_only(self, db_session):
        _add(db_session, "W", "W-W 2", "X", "C1ROL", season="winter")
        _add(db_session, "S", "S-S 2", "X", "C1RML", season="sommer")
        results = _search(db_session, filter_season="sommer")
        assert len(results) == 1
        assert results[0].season == "sommer"

    def test_allwetter(self, db_session):
        _add(db_session, "A", "A-A 3", "X", "C1ROL", season="allwetter")
        _add(db_session, "W", "W-W 3", "X", "C1RML", season="winter")
        results = _search(db_session, filter_season="allwetter")
        assert len(results) == 1

    def test_no_season_filter_returns_all(self, db_session):
        _add(db_session, "W", "W-W 4", "X", "C1ROL", season="winter")
        _add(db_session, "S", "S-S 3", "X", "C1RML", season="sommer")
        results = _search(db_session, filter_season="")
        assert len(results) == 2

    def test_season_filter_excludes_null_season(self, db_session):
        _add(db_session, "No Season", "N-N 1", "X", "C1ROL", season=None)
        _add(db_session, "Winter", "N-W 1", "X", "C1RML", season="winter")
        results = _search(db_session, filter_season="winter")
        assert len(results) == 1
        assert results[0].customer_name == "Winter"


# =========================================================
# Combined filter + sort + search
# =========================================================
class TestCombined:
    def test_search_and_filter_container(self, db_session):
        _add(db_session, "Hans Container", "H-C 1", "X", "C1ROL",
             note="suchwort")
        _add(db_session, "Hans Garage", "H-G 1", "X", "GR1OL",
             note="suchwort")
        results = _search(db_session, q="suchwort", filter_pos="container")
        assert len(results) == 1
        assert results[0].customer_name == "Hans Container"

    def test_search_sort_and_filter(self, db_session):
        _add(db_session, "Zeta Winter", "Z-W 1", "X", "C1ROL", season="winter")
        _add(db_session, "Alpha Winter", "A-W 1", "X", "C1RML", season="winter")
        _add(db_session, "Alpha Sommer", "A-S 1", "X", "C2ROL", season="sommer")
        results = _search(db_session, q="Alpha", filter_season="winter",
                          sort="customer_asc")
        assert len(results) == 1
        assert results[0].customer_name == "Alpha Winter"

    def test_all_params_empty_returns_everything(self, db_session):
        _add(db_session, "X", "X-X 2", "X", "C1ROL")
        _add(db_session, "Y", "Y-Y 1", "X", "GR1OL")
        results = _search(db_session)
        assert len(results) == 2


# =========================================================
# NULL note edge cases (customer-reported scenario)
# =========================================================
class TestNullNoteSearch:
    """When note is NULL, LIKE returns NULL (not FALSE).
    In SQLAlchemy's OR chain, NULL OR TRUE → TRUE, so rows with
    NULL notes must still appear when another column matches."""

    def test_null_note_matches_by_customer_name(self, db_session):
        """Row with NULL note must appear when customer_name matches."""
        _add(db_session, "Max Mustermann", "M-MM 1", "Golf", "C1ROL",
             note=None)
        results = _search(db_session, q="Mustermann")
        assert len(results) == 1

    def test_null_note_matches_by_plate(self, db_session):
        _add(db_session, "X", "B-AB 1234", "Golf", "C1ROL", note=None)
        results = _search(db_session, q="B-AB")
        assert len(results) == 1

    def test_null_note_matches_by_car_type(self, db_session):
        _add(db_session, "X", "X-X 1", "BMW 3er", "C1ROL", note=None)
        results = _search(db_session, q="BMW")
        assert len(results) == 1

    def test_null_note_not_matched_by_random_query(self, db_session):
        """Row with NULL note must NOT appear when no column matches."""
        _add(db_session, "X", "X-X 1", "Golf", "C1ROL", note=None)
        results = _search(db_session, q="ZZNOTFOUND")
        assert len(results) == 0

    def test_mix_null_and_real_notes(self, db_session):
        """Mixed scenario: one row has matching note, another has NULL."""
        _add(db_session, "Anna", "A-A 1", "Golf", "C1ROL",
             note="Winterreifen geprüft")
        _add(db_session, "Bob", "B-B 1", "Golf", "C1RML", note=None)
        results = _search(db_session, q="Winterreifen")
        assert len(results) == 1
        assert results[0].customer_name == "Anna"

    def test_all_null_notes_with_name_match(self, db_session):
        """Multiple rows with NULL notes, searching by a common car type."""
        _add(db_session, "A", "A-A 1", "VW Golf", "C1ROL", note=None)
        _add(db_session, "B", "B-B 1", "VW Golf", "C1RML", note=None)
        _add(db_session, "C", "C-C 1", "BMW 3er", "C2ROL", note=None)
        results = _search(db_session, q="VW Golf")
        assert len(results) == 2


# =========================================================
# Renewal filter tests
# =========================================================
class TestFilterRenewal:
    def test_renewal_filter_returns_only_flagged(self, db_session):
        ws1 = WheelSet(customer_name="Renew", license_plate="R-R 1",
                       car_type="Golf", storage_position="C1ROL",
                       tires_need_renewal=True)
        ws2 = WheelSet(customer_name="NoRenew", license_plate="N-N 1",
                       car_type="Golf", storage_position="C1RML",
                       tires_need_renewal=False)
        db_session.add_all([ws1, ws2])
        db_session.commit()
        results = _search(db_session, filter_renewal="1")
        assert len(results) == 1
        assert results[0].customer_name == "Renew"

    def test_no_renewal_filter_returns_all(self, db_session):
        ws1 = WheelSet(customer_name="Renew", license_plate="R-R 2",
                       car_type="Golf", storage_position="C1ROL",
                       tires_need_renewal=True)
        ws2 = WheelSet(customer_name="NoRenew", license_plate="N-N 2",
                       car_type="Golf", storage_position="C1RML",
                       tires_need_renewal=False)
        db_session.add_all([ws1, ws2])
        db_session.commit()
        results = _search(db_session, filter_renewal="")
        assert len(results) == 2

    def test_renewal_filter_combined_with_search(self, db_session):
        ws1 = WheelSet(customer_name="Hans Renewal", license_plate="H-R 1",
                       car_type="Golf", storage_position="C1ROL",
                       tires_need_renewal=True)
        ws2 = WheelSet(customer_name="Hans NoRenewal", license_plate="H-N 1",
                       car_type="Golf", storage_position="C1RML",
                       tires_need_renewal=False)
        ws3 = WheelSet(customer_name="Other Renewal", license_plate="O-R 1",
                       car_type="Golf", storage_position="C2ROL",
                       tires_need_renewal=True)
        db_session.add_all([ws1, ws2, ws3])
        db_session.commit()
        results = _search(db_session, q="Hans", filter_renewal="1")
        assert len(results) == 1
        assert results[0].customer_name == "Hans Renewal"

    def test_renewal_filter_combined_with_season(self, db_session):
        ws1 = WheelSet(customer_name="Winter Renew", license_plate="W-R 1",
                       car_type="Golf", storage_position="C1ROL",
                       tires_need_renewal=True, season="winter")
        ws2 = WheelSet(customer_name="Summer Renew", license_plate="S-R 1",
                       car_type="Golf", storage_position="C1RML",
                       tires_need_renewal=True, season="sommer")
        db_session.add_all([ws1, ws2])
        db_session.commit()
        results = _search(db_session, filter_renewal="1",
                          filter_season="winter")
        assert len(results) == 1
        assert results[0].customer_name == "Winter Renew"

    def test_renewal_with_null_note_and_search(self, db_session):
        """Renewal-flagged row with NULL note found by customer name."""
        ws = WheelSet(customer_name="Flagged Customer",
                      license_plate="F-C 1", car_type="Golf",
                      storage_position="C1ROL",
                      tires_need_renewal=True, note=None)
        db_session.add(ws)
        db_session.commit()
        results = _search(db_session, q="Flagged", filter_renewal="1")
        assert len(results) == 1


# =========================================================
# Search via Flask routes (integration)
# =========================================================
class TestSearchRouteIntegration:
    """Test the actual /wheelsets endpoint with query parameters."""

    def test_search_by_note_via_route(self, client, seed_settings,
                                      db_session):
        ws = WheelSet(customer_name="Route Test",
                      license_plate="R-T 1", car_type="Golf",
                      storage_position="C1ROM",
                      note="Spezialbehandlung")
        db_session.add(ws)
        db_session.commit()
        resp = client.get("/wheelsets?q=Spezialbehandlung")
        assert resp.status_code == 200
        assert b"Route Test" in resp.data

    def test_search_null_note_by_name_via_route(self, client,
                                                 seed_settings,
                                                 db_session):
        ws = WheelSet(customer_name="Null Note Kunde",
                      license_plate="N-N 1", car_type="Golf",
                      storage_position="C1ROM", note=None)
        db_session.add(ws)
        db_session.commit()
        resp = client.get("/wheelsets?q=Null+Note")
        assert resp.status_code == 200
        assert b"Null Note Kunde" in resp.data

    def test_renewal_filter_via_route(self, client, seed_settings,
                                      db_session):
        ws1 = WheelSet(customer_name="Flagged",
                       license_plate="F-F 1", car_type="Golf",
                       storage_position="C1ROM",
                       tires_need_renewal=True)
        ws2 = WheelSet(customer_name="Normal",
                       license_plate="N-N 2", car_type="Golf",
                       storage_position="C1LOM",
                       tires_need_renewal=False)
        db_session.add_all([ws1, ws2])
        db_session.commit()
        resp = client.get("/wheelsets?filter_renewal=1")
        assert resp.status_code == 200
        assert b"Flagged" in resp.data
        assert b"Normal" not in resp.data

    def test_search_umlaut_via_route(self, client, seed_settings,
                                     db_session):
        ws = WheelSet(customer_name="Müller",
                      license_plate="M-M 1", car_type="Golf",
                      storage_position="C1ROM",
                      note="Ölwechsel fällig")
        db_session.add(ws)
        db_session.commit()
        resp = client.get("/wheelsets?q=%C3%B6lwechsel")  # ölwechsel
        assert resp.status_code == 200
        assert "Müller".encode("utf-8") in resp.data
