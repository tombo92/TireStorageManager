"""
Unit & integration tests for the wheelset list search, sort and filter logic.

Tests operate directly against a real SQLAlchemy session (in-memory SQLite)
so they are fast and do not require the Flask request cycle.
"""
import pytest

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
            filter_season=""):
    """Replicate the query logic from list_wheelsets without Flask."""
    from sqlalchemy import asc, desc

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
