"""Tests for tsm/positions.py — position validation, sorting, free/disabled."""
import pytest
from tsm.positions import (
    all_valid_positions,
    is_valid_position,
    position_sort_key,
    get_occupied_positions,
    get_disabled_positions,
    disable_position,
    enable_position,
    is_usable_position,
    first_free_position,
    free_positions,
    ALL_POSITIONS,
    SORTED_POSITIONS,
    RE_CONTAINER,
    RE_GARAGE,
)
from tsm.models import WheelSet, DisabledPosition


# ── Validation ─────────────────────────────────────────
class TestValidation:
    def test_valid_container_positions(self):
        assert is_valid_position("C1ROL")
        assert is_valid_position("C4LULL")
        assert is_valid_position("C2ROMM")

    def test_valid_garage_positions(self):
        assert is_valid_position("GR1OL")
        assert is_valid_position("GR8UM")
        assert is_valid_position("GR5MR")

    def test_invalid_positions(self):
        assert not is_valid_position("")
        assert not is_valid_position("X1ROL")
        assert not is_valid_position("C0ROL")
        assert not is_valid_position("C5ROL")
        assert not is_valid_position("GR0OL")
        assert not is_valid_position("GR9OL")
        assert not is_valid_position("RANDOM")

    def test_regex_container_groups(self):
        m = RE_CONTAINER.match("C3LUMM")
        assert m is not None
        assert m.group(1) == "3"
        assert m.group(2) == "L"
        assert m.group(3) == "U"
        assert m.group(4) == "MM"

    def test_regex_garage_groups(self):
        m = RE_GARAGE.match("GR7MR")
        assert m is not None
        assert m.group(1) == "7"
        assert m.group(2) == "M"
        assert m.group(3) == "R"


# ── All positions generation ───────────────────────────
class TestAllPositions:
    def test_count(self):
        # 4 containers × 2 sides × 3 levels × 6 positions = 144
        # 8 garages × 3 levels × 3 positions = 72
        assert len(ALL_POSITIONS) == 144 + 72

    def test_all_valid(self):
        for p in ALL_POSITIONS:
            assert is_valid_position(p), f"{p} should be valid"

    def test_sorted_same_length(self):
        assert len(SORTED_POSITIONS) == len(ALL_POSITIONS)

    def test_sorted_is_actually_sorted(self):
        keys = [position_sort_key(p) for p in SORTED_POSITIONS]
        assert keys == sorted(keys)


# ── Sorting ────────────────────────────────────────────
class TestSorting:
    def test_containers_before_garage(self):
        assert position_sort_key("C1ROL") < position_sort_key("GR1OL")

    def test_container_number_ordering(self):
        assert position_sort_key("C1ROL") < position_sort_key("C2ROL")

    def test_garage_shelf_ordering(self):
        assert position_sort_key("GR1OL") < position_sort_key("GR2OL")

    def test_level_ordering(self):
        assert position_sort_key("C1ROL") < position_sort_key("C1RML")
        assert position_sort_key("C1RML") < position_sort_key("C1RUL")


# ── DB-dependent functions ─────────────────────────────
class TestOccupied:
    def test_empty_db(self, db_session):
        assert get_occupied_positions(db_session) == set()

    def test_with_wheelset(self, db_session, seed_wheelset):
        occ = get_occupied_positions(db_session)
        assert seed_wheelset.storage_position in occ


class TestDisabled:
    def test_empty_db(self, db_session):
        assert get_disabled_positions(db_session) == set()

    def test_disable_and_get(self, db_session):
        assert disable_position(db_session, "C1ROL", "broken") is True
        dis = get_disabled_positions(db_session)
        assert "C1ROL" in dis

    def test_disable_invalid(self, db_session):
        assert disable_position(db_session, "INVALID") is False

    def test_disable_duplicate(self, db_session):
        disable_position(db_session, "C1ROL")
        assert disable_position(db_session, "C1ROL") is False

    def test_enable(self, db_session):
        disable_position(db_session, "C1ROL")
        assert enable_position(db_session, "C1ROL") is True
        assert "C1ROL" not in get_disabled_positions(db_session)

    def test_enable_nonexistent(self, db_session):
        assert enable_position(db_session, "C1ROL") is False

    def test_is_usable(self, db_session):
        assert is_usable_position(db_session, "C1ROL") is True
        disable_position(db_session, "C1ROL")
        assert is_usable_position(db_session, "C1ROL") is False


class TestFreePositions:
    def test_all_free_empty_db(self, db_session):
        fp = free_positions(db_session)
        assert len(fp) == len(ALL_POSITIONS)

    def test_first_free(self, db_session):
        pos = first_free_position(db_session)
        assert pos is not None
        assert pos == SORTED_POSITIONS[0]

    def test_occupied_excluded(self, db_session, seed_wheelset):
        fp = free_positions(db_session)
        assert seed_wheelset.storage_position not in fp

    def test_disabled_excluded(self, db_session):
        first = SORTED_POSITIONS[0]
        disable_position(db_session, first)
        fp = free_positions(db_session)
        assert first not in fp
        assert first_free_position(db_session) == SORTED_POSITIONS[1]
