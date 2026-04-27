"""
ratelimit.py — Rate limiting utilities for taia-browser-harness.

Implements token bucket algorithm for rate limiting.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""
    tokens: float
    last_update: float
    capacity: float
    refill_rate: float


class RateLimiter:
    """
    Token bucket rate limiter per connection.
    
    Usage:
        limiter = RateLimiter(max_requests=100, refill_rate=10)
        if not limiter.check_and_consume("connection_id"):
            return {"error": "Rate limit exceeded"}
    """

    def __init__(
        self,
        max_requests: int = 100,
        refill_rate: float = 10.0,
        bucket_capacity: float | None = None,
    ) -> None:
        self.max_requests = max_requests
        self.refill_rate = refill_rate
        self.bucket_capacity = bucket_capacity or max_requests
        self._buckets: Dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(
                tokens=self.bucket_capacity,
                last_update=time.monotonic(),
                capacity=self.bucket_capacity,
                refill_rate=self.refill_rate,
            )
        )
        self._lock = asyncio.Lock()

    async def check_and_consume(self, connection_id: str) -> bool:
        """Check if request is allowed and consume a token."""
        async with self._lock:
            bucket = self._buckets[connection_id]
            now = time.monotonic()

            # Refill tokens based on time elapsed
            elapsed = now - bucket.last_update
            bucket.tokens = min(
                bucket.capacity,
                bucket.tokens + elapsed * bucket.refill_rate,
            )
            bucket.last_update = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True
            return False

    async def reset(self, connection_id: str) -> None:
        """Reset rate limit bucket for a connection."""
        async with self._lock:
            self._buckets[connection_id] = TokenBucket(
                tokens=self.bucket_capacity,
                last_update=time.monotonic(),
                capacity=self.bucket_capacity,
                refill_rate=self.refill_rate,
            )


class BurstLimiter:
    """
    Simple burst limiter - maximum requests per time window.
    
    Usage:
        limiter = BurstLimiter(max_burst=20, window_seconds=60)
        if not limiter.check("connection_id"):
            return {"error": "Too many requests"}
    """

    def __init__(self, max_burst: int = 20, window_seconds: int = 60) -> None:
        self.max_burst = max_burst
        self.window_seconds = window_seconds
        self._requests: Dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, connection_id: str) -> bool:
        """Check if request is allowed (without consuming)."""
        async with self._lock:
            now = time.monotonic()
            window_start = now - self.window_seconds

            # Clean old requests
            self._requests[connection_id] = [
                t for t in self._requests[connection_id] if t > window_start
            ]

            return len(self._requests[connection_id]) < self.max_burst

    async def record(self, connection_id: str) -> bool:
        """Record a request and check if still within limits."""
        async with self._lock:
            now = time.monotonic()
            window_start = now - self.window_seconds

            # Clean old requests
            self._requests[connection_id] = [
                t for t in self._requests[connection_id] if t > window_start
            ]

            if len(self._requests[connection_id]) >= self.max_burst:
                return False

            self._requests[connection_id].append(now)
            return True