"""Rate limiter local, pequeno y seguro para multiples hilos."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: float


class SlidingWindowRateLimiter:
    """Limita eventos por clave dentro de una ventana movil."""

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        max_keys: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(0.1, float(window_seconds))
        self.max_keys = max(1, int(max_keys))
        self._clock = clock
        self._entries: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.RLock()

    def consume(self, key: str) -> RateLimitDecision:
        now = float(self._clock())
        safe_key = str(key)
        with self._lock:
            timestamps = self._entries.pop(safe_key, deque())
            cutoff = now - self.window_seconds
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                retry_after = max(0.0, self.window_seconds - (now - timestamps[0]))
                self._entries[safe_key] = timestamps
                return RateLimitDecision(False, 0, retry_after)
            timestamps.append(now)
            self._entries[safe_key] = timestamps
            while len(self._entries) > self.max_keys:
                self._entries.popitem(last=False)
            return RateLimitDecision(True, self.limit - len(timestamps), 0.0)
