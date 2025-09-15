import os

# Current app version
__version__ = "1.0.0"

# Default database path (can be changed to a network share)
DB_PATH = os.path.abspath("tire_storage.db")

# Backup interval in hours
BACKUP_INTERVAL_HOURS = 6

def lock_path_for(db_path: str) -> str:
    """Return a path for the lock file based on the DB file location"""
    return db_path + ".lock"