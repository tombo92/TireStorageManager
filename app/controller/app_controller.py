from pathlib import Path
from app.model.db import Database
from app.model.repository import WheelRepository
from app.model.entities import WheelRecord, Season
from app.utils.locking import WriteLock
from app.utils import excel_io
from app.config import lock_path_for, BACKUP_INTERVAL_HOURS
from app.utils.scheduler import RepeatedTimer


class AppController:
    """Controller layer that manages application logic."""

    def __init__(self, db_path: str):
        self.db = Database(db_path)
        self.repo = WheelRepository(self.db)
        self._lock_path = lock_path_for(db_path)
        self._backup_dir = str(Path(db_path).with_suffix("")) + "_backups"
        Path(self._backup_dir).mkdir(exist_ok=True, parents=True)

        # Start periodic backups
        self._backup_timer = RepeatedTimer(BACKUP_INTERVAL_HOURS * 3600, self.backup)
        self._backup_timer.start()

    def list_records(self, search: str = ""):
        return self.repo.list(search)

    def add_record(self, customer_name: str, location: str, season: str) -> int:
        season_enum = self._validate_season(season)
        with WriteLock(self._lock_path):
            return self.repo.add(WheelRecord(None, customer_name.strip(), location.strip(), season_enum))

    def update_record(self, record_id: int, customer_name: str, location: str, season: str):
        season_enum = self._validate_season(season)
        with WriteLock(self._lock_path):
            self.repo.update(WheelRecord(record_id, customer_name.strip(), location.strip(), season_enum))

    def delete_record(self, record_id: int):
        with WriteLock(self._lock_path):
            self.repo.delete(record_id)

    def import_excel(self, path: str) -> int:
        recs = excel_io.read_excel(path)
        with WriteLock(self._lock_path):
            return self.repo.bulk_insert(recs)

    def export_excel(self, path: str, search: str = ""):
        recs = self.repo.list(search)
        excel_io.export_excel(path, recs)

    def backup(self) -> str:
        """Perform an online backup of the database and return the path."""
        from datetime import datetime
        dbp = Path(self.db.db_path)
        backup_name = f"{dbp.stem}_backup_{datetime.now():%Y%m%d_%H%M%S}{dbp.suffix}"
        backup_path = str(Path(self._backup_dir) / backup_name)
        self.db.backup_to(backup_path)
        return backup_path

    def close(self):
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
        except ValueError:
            raise ValueError("Season must be 'winter', 'summer' or 'allseason'")
