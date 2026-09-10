"""A sliding-window counter per client, in memory (spec §6.45: code lookups are rate-limited)."""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, per_s: float) -> None:
        self.limit, self.per = limit, per_s
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, q = time.monotonic(), self._hits[key]
        while q and now - q[0] > self.per:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
