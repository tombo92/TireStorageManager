import pandas as pd
from typing import List
from app.model.entities import WheelRecord, Season

REQUIRED_COLS = ["customer_name", "location", "season"]

def normalize_season(val: str) -> Season:
    """Normalize various season inputs into a Season enum."""
    v = str(val).strip().lower()
    if v in ("winter", "w", "win", "winterreifen"):
        return Season.WINTER
    if v in ("summer", "s", "sum", "sommerreifen", "sommer"):
        return Season.SUMMER
    if v in ("allseason", "as", "all", "ganzjahresreifen", "ganzjahr"):
        return Season.ALLSEASON
    raise ValueError(f"Invalid season value: {val!r}")

def read_excel(path: str) -> List[WheelRecord]:
    """Read wheel records from an Excel file."""
    df = pd.read_excel(path)
    cols = {c.lower().strip(): c for c in df.columns}
    for rc in REQUIRED_COLS:
        if rc not in cols:
            raise ValueError(f"Missing required column: {rc}. Found: {list(df.columns)}")

    out = []
    for _, row in df.iterrows():
        season = normalize_season(row[cols["season"]])
        rec = WheelRecord(
            id=None,
            customer_name=str(row[cols["customer_name"]]).strip(),
            location=str(row[cols["location"]]).strip(),
            season=season
        )
        out.append(rec)
    return out

def export_excel(path: str, records: List[WheelRecord]) -> None:
    """Export wheel records to an Excel file."""
    df = pd.DataFrame([{
        "customer_name": r.customer_name,
        "location": r.location,
        "season": r.season.value
    } for r in records])
    df.to_excel(path, index=False)
