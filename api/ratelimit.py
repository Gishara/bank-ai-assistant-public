"""Per-user token-bucket rate limiting, sized by role."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from core.rbac import RATE_LIMITS, Role


@dataclass
class Bucket:
    capacity: int
    refill_per_s: float
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, Bucket] = {}
        self._lock = threading.Lock()

    def check(self, user_id: str, role: Role, cost: float = 1.0) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        capacity, rate = RATE_LIMITS[role]
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(user_id)
            if b is None or b.capacity != capacity:
                b = self._buckets[user_id] = Bucket(capacity, rate, float(capacity), now)
            b.tokens = min(b.capacity, b.tokens + (now - b.updated) * b.refill_per_s)
            b.updated = now
            if b.tokens >= cost:
                b.tokens -= cost
                return True, 0.0
            return False, math.ceil((cost - b.tokens) / b.refill_per_s)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


limiter = RateLimiter()
