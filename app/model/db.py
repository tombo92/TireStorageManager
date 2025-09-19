import sqlite3
from pathlib import Path

class Database:
    """SQLite database connection manager with WAL mode and backup support."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._create_schema()

    def _create_schema(self):
        """Ensure the required tables exist."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS wheels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                licence_plate TEXT NOT NULL,
                location TEXT NOT NULL,
                season TEXT NOT NULL CHECK(season IN ('winter','summer','allseason'))
            );
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_name ON wheels(customer_name);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_licence_plate ON wheels(licence_plate);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_location ON wheels(location);")
        self.conn.commit()

    def get_connection(self) -> sqlite3.Connection:
        """Return the active SQLite connection."""
        return self.conn

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def backup_to(self, dest_path: str):
        """Create an online backup to the given path."""
        dest = sqlite3.connect(dest_path)
        with dest:
            self.conn.backup(dest)
        dest.close()
