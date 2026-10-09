from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta

from .clock import Clock, utcnow


class SlidingWindowLimiter:
    """At most ``limit`` events per ``window`` for each key. ``limit=0`` blocks everything."""

    def __init__(self, limit: int, window: timedelta, clock: Clock = utcnow) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._events: dict[str, deque] = defaultdict(deque)  # type: ignore[type-arg]

    def allow(self, key: str = "") -> bool:
        now = self.clock()
        q = self._events[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
