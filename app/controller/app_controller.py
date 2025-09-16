"""
App Controller Module
=====================

This module implements the application controller layer in the MVC architecture
for the Tire Storage Manager. The controller coordinates communication between
the view (GUI) and the model (database + business logic).

Responsibilities:
-----------------
- Provide a clean interface for the GUI to interact with the system.
- Delegate data storage/retrieval to the database manager.
- Manage import/export of Excel files.
- Manage database backup.
- Ensure correct typing and error handling.

Author: https://github.com/tombo92
"""
# =========================
# Imports
# =========================
from pathlib import Path
from typing import Optional
from app.model.db import Database
from app.model.repository import WheelRepository
from app.model.entities import WheelRecord, Season
from app.utils.locking import WriteLock
from app.utils import excel_io
from app.config import lock_path_for, BACKUP_INTERVAL_HOURS
from app.utils.scheduler import RepeatedTimer


# =========================
# Class: AppController
# =========================
class AppController:
    """Controller layer that manages application logic."""

    def __init__(self, db_path: str):
        self.db = Database(db_path)
        self.repo = WheelRepository(self.db)
        self._lock_path = lock_path_for(db_path)
        self._backup_dir = str(Path(db_path).with_suffix("")) + "_backups"
        Path(self._backup_dir).mkdir(exist_ok=True, parents=True)

        # Start periodic backups
        self._backup_timer = RepeatedTimer(BACKUP_INTERVAL_HOURS * 3600,
                                           self.backup)
        self._backup_timer.start()

    def list_records(self, filter_text: Optional[str] = None) -> list[WheelRecord]:
        """
        Retrieve all tire storage records, optionally filtered.

        Parameters
        ----------
        filter_text : str, optional
            If provided, only records with matching customer name or location
            will be returned.

        Returns
        -------
        List[TireRecord]
            List of tire storage records.
        """
        return self.repo.list(filter_text)

    def add_record(self, customer_name: str, location: str, season: str) -> int:
        """
        Add a new tire storage record.

        Parameters
        ----------
        customer : str
            The customer's name.
        location : str
            The storage location identifier.
        season : str
            The season ("winter", "summer", or "allseason").

        Returns
        -------
        int
            The ID of the newly created record.
        """
        season_enum = self._validate_season(season)
        with WriteLock(self._lock_path):
            return self.repo.add(WheelRecord(None, customer_name.strip(), location.strip(), season_enum))

    def update_record(self, record_id: int, customer_name: str, location: str, season: str) -> None:
        """
        Update an existing tire storage record.

        Parameters
        ----------
        record_id : int
            The unique ID of the record to update.
        customer : str
            Updated customer name.
        location : str
            Updated storage location.
        season : str
            Updated season ("winter", "summer", or "allseason").
        """
        season_enum = self._validate_season(season)
        with WriteLock(self._lock_path):
            self.repo.update(WheelRecord(record_id, customer_name.strip(), location.strip(), season_enum))

    def delete_record(self, record_id: int) -> None:
        """
        Delete a tire storage record.

        Parameters
        ----------
        record_id : int
            The unique ID of the record to delete.
        """
        with WriteLock(self._lock_path):
            self.repo.delete(record_id)

    def import_excel(self, path: str) -> int:
        """
        Import records from an Excel file.

        Parameters
        ----------
        path : str
            Path to the Excel file.

        Returns
        -------
        int
            Number of imported records.
        """
        recs = excel_io.read_excel(path)
        with WriteLock(self._lock_path):
            return self.repo.bulk_insert(recs)

    def export_excel(self, path: str, search: str = ""):
        """
        Export records to an Excel file.

        Parameters
        ----------
        path : str
            Destination path for the Excel file.
        filter_text : str, optional
            If provided, only matching records will be exported.
        """
        recs = self.repo.list(search)
        excel_io.export_excel(path, recs)

    def backup(self) -> str:
        """
        Create a backup of the current database.

        Returns
        -------
        Path
            Path to the backup file created.
        """
        """Perform an online backup of the database and return the path."""
        from datetime import datetime
        dbp = Path(self.db.db_path)
        backup_name = f"{dbp.stem}_backup_{datetime.now():%Y%m%d_%H%M%S}{dbp.suffix}"
        backup_path = str(Path(self._backup_dir) / backup_name)
        self.db.backup_to(backup_path)
        return backup_path

    def close(self) -> None:
        """Stop timers and close DB connection."""
        try:
            self._backup_timer.stop()
        except Exception:
            pass
        self.db.close()

    def _validate_season(self, season: str) -> Season:
        """Convert string to Season enum, raise ValueError if invalid."""
        s = season.strip().lower()
        try:
            return Season(s)
        except ValueError as e:
            raise ValueError("Season must be 'winter', 'summer' or 'allseason'") from e
