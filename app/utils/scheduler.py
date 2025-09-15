import threading
import traceback

class RepeatedTimer:
    """
    Runs a given function repeatedly every interval_seconds in a background thread.
    """

    def __init__(self, interval_seconds: float, function, *, run_immediately=False):
        self.interval = interval_seconds
        self.function = function
        self.thread = threading.Thread(target=self._run, daemon=True)
        self._stop = threading.Event()
        self.run_immediately = run_immediately

    def start(self):
        """Start the background thread."""
        self.thread.start()

    def stop(self):
        """Stop the background thread."""
        self._stop.set()
        self.thread.join(timeout=1)

    def _run(self):
        """Internal loop to run the function repeatedly."""
        if self.run_immediately:
            try:
                self.function()
            except Exception:
                traceback.print_exc()

        while not self._stop.wait(self.interval):
            try:
                self.function()
            except Exception:
                traceback.print_exc()
