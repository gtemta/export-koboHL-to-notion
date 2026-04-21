"""Thread-safe rate limiter for Notion API calls."""
import time
from threading import Lock


class NotionRateLimiter:
    """Enforces a minimum interval between calls across threads.

    Notion documents ~3 requests per second per integration.
    """

    def __init__(self, calls_per_second: float = 3.0):
        self._min_interval = 1.0 / calls_per_second
        self._last_call = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()
