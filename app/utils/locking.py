from filelock import FileLock

class WriteLock:
    """
    Cross-process file lock to serialize write operations.
    Ensures only one process can write to the database at a time.
    """

    def __init__(self, path: str):
        self._lock = FileLock(path)

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._lock.release()
