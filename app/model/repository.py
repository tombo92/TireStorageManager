from typing import List, Optional
from app.model.entities import WheelRecord, Season
from app.model.db import Database

class WheelRepository:
    """Repository for CRUD operations on wheel storage records."""

    def __init__(self, db: Database):
        self.db = db

    def add(self, record: WheelRecord) -> int:
        """Insert a new wheel record and return its ID."""
        cur = self.db.get_connection().cursor()
        cur.execute(
            "INSERT INTO wheels (customer_name, location, season) VALUES (?, ?, ?)",
            (record.customer_name, record.location, record.season.value)
        )
        self.db.get_connection().commit()
        return cur.lastrowid

    def update(self, record: WheelRecord) -> None:
        """Update an existing wheel record by ID."""
        if record.id is None:
            raise ValueError("Record ID required for update")
        cur = self.db.get_connection().cursor()
        cur.execute(
            "UPDATE wheels SET customer_name=?, location=?, season=? WHERE id=?",
            (record.customer_name, record.location, record.season.value, record.id)
        )
        self.db.get_connection().commit()

    def delete(self, record_id: int) -> None:
        """Delete a wheel record by ID."""
        cur = self.db.get_connection().cursor()
        cur.execute("DELETE FROM wheels WHERE id=?", (record_id,))
        self.db.get_connection().commit()

    def get(self, record_id: int) -> Optional[WheelRecord]:
        """Fetch a single wheel record by ID."""
        cur = self.db.get_connection().cursor()
        cur.execute("SELECT id, customer_name, location, season FROM wheels WHERE id=?", (record_id,))
        row = cur.fetchone()
        if row:
            return WheelRecord(row[0], row[1], row[2], Season(row[3]))
        return None

    def list(self, search: str = "") -> List[WheelRecord]:
        """List all records, optionally filtering by customer name or location."""
        cur = self.db.get_connection().cursor()
        if search:
            q = f"%{search.lower()}%"
            cur.execute(
                "SELECT id, customer_name, location, season FROM wheels "
                "WHERE lower(customer_name) LIKE ? OR lower(location) LIKE ? "
                "ORDER BY customer_name",
                (q, q)
            )
        else:
            cur.execute(
                "SELECT id, customer_name, location, season FROM wheels ORDER BY customer_name"
            )
        rows = cur.fetchall()
        return [WheelRecord(r[0], r[1], r[2], Season(r[3])) for r in rows]

    def bulk_insert(self, records: List[WheelRecord]) -> int:
        """Insert multiple records at once. Returns count of inserted records."""
        cur = self.db.get_connection().cursor()
        cur.executemany(
            "INSERT INTO wheels (customer_name, location, season) VALUES (?, ?, ?)",
            [(r.customer_name, r.location, r.season.value) for r in records]
        )
        self.db.get_connection().commit()
        return cur.rowcount
