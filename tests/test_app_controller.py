"""
Unit tests for app.controller.app_controller
===========================================

These tests validate the behavior of the AppController class, ensuring that it:
- Correctly validates seasons
- Delegates CRUD operations to DatabaseManager
- Manages Excel import/export
- Handles backup and close operations

The DatabaseManager is mocked so no real DB operations are performed.
"""

# =========================
# Imports
# =========================
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from app.controller.app_controller import AppController
from app.model.entities import Season, WheelRecord


# -------------------------
# Fixtures
# -------------------------
@pytest.fixture
def mock_db_manager(monkeypatch):
    """Patch DatabaseManager with a MagicMock."""
    mock = MagicMock()
    monkeypatch.setattr("app.controller.app_controller.DatabaseManager", lambda _: mock)
    return mock


@pytest.fixture
def controller(mock_db_manager):
    """Return an AppController with a mocked DatabaseManager."""
    return AppController(Path("fake.db"))


# -------------------------
# Tests: Season Validation
# -------------------------
def test_validate_season_valid(controller):
    assert controller._validate_season("winter") == Season.WINTER
    assert controller._validate_season("Summer") == Season.SUMMER
    assert controller._validate_season("ALLSEASON") == Season.ALLSEASON


def test_validate_season_invalid(controller):
    with pytest.raises(ValueError) as e:
        controller._validate_season("autumn")
    assert "Invalid season" in str(e.value)


# -------------------------
# Tests: CRUD Operations
# -------------------------
def test_add_record(controller, mock_db_manager):
    mock_db_manager.add_record.return_value = 42
    record_id = controller.add_record("Alice", "A1", "winter")
    mock_db_manager.add_record.assert_called_once_with("Alice", "A1", Season.WINTER)
    assert record_id == 42


def test_update_record(controller, mock_db_manager):
    controller.update_record(1, "Bob", "B2", "summer")
    mock_db_manager.update_record.assert_called_once_with(1, "Bob", "B2", Season.SUMMER)


def test_delete_record(controller, mock_db_manager):
    controller.delete_record(7)
    mock_db_manager.delete_record.assert_called_once_with(7)


def test_list_records(controller, mock_db_manager):
    mock_db_manager.list_records.return_value = [WheelRecord(id=1, customer_name="Carl", location="C3", season=Season.WINTER)]
    records = controller.list_records("Carl")
    mock_db_manager.list_records.assert_called_once_with("Carl")
    assert len(records) == 1
    assert records[0].customer_name == "Carl"


# -------------------------
# Tests: Import/Export
# -------------------------
def test_import_excel(controller, mock_db_manager):
    mock_db_manager.import_from_excel.return_value = 3
    count = controller.import_excel("file.xlsx")
    mock_db_manager.import_from_excel.assert_called_once_with("file.xlsx")
    assert count == 3


def test_export_excel(controller, mock_db_manager):
    controller.export_excel("out.xlsx", "filter")
    mock_db_manager.export_to_excel.assert_called_once_with("out.xlsx", "filter")


# -------------------------
# Tests: Backup / Close
# -------------------------
def test_backup(controller, mock_db_manager):
    mock_db_manager.backup.return_value = Path("backup.db")
    path = controller.backup()
    mock_db_manager.backup.assert_called_once()
    assert path == Path("backup.db")


def test_close(controller, mock_db_manager):
    controller.close()
    mock_db_manager.close.assert_called_once()
