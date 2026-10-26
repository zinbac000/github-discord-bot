import time
from collections import deque
from collections.abc import Callable


class CreateQuota:
    """In-memory cap on how many issues one person may create per window (default one hour).

    `limit` of 0 means no cap. Counters are lost on restart, by design (no database).
    """

    def __init__(
        self,
        limit: int,
        *,
        window: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = limit
        self._window = window
        self._clock = clock
        self._used: dict[int, deque[float]] = {}

    def _prune(self, user_id: int) -> deque[float]:
        now = self._clock()
        stamps = self._used.setdefault(user_id, deque())
        while stamps and now - stamps[0] >= self._window:
            stamps.popleft()
        if not stamps:
            self._used.pop(user_id, None)
        return stamps

    def remaining(self, user_id: int) -> int | None:
        """How many more issues this person may create now, or None when there is no cap."""
        if self.limit <= 0:
            return None
        return max(0, self.limit - len(self._prune(user_id)))

    def consume(self, user_id: int, n: int = 1) -> bool:
        """Count `n` creations. False, and nothing counted, if that would pass the cap."""
        left = self.remaining(user_id)
        if left is None:
            return True
        if n > left:
            return False
        stamps = self._used.setdefault(user_id, deque())
        stamps.extend([self._clock()] * n)
        return True
