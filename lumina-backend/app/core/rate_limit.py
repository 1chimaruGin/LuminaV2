"""
Simple in-memory rate limiter for expensive API endpoints.
Uses a sliding-window counter per client IP.
"""

import time
from collections import defaultdict
from functools import wraps

from fastapi import HTTPException, Request


class RateLimiter:
    """Per-IP sliding window rate limiter."""

    def __init__(self):
        # ip -> list of request timestamps
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, ip: str, max_requests: int, window_seconds: int) -> bool:
        """Return True if allowed, raise 429 if rate exceeded."""
        now = time.time()
        cutoff = now - window_seconds
        # Prune old entries
        self._windows[ip] = [t for t in self._windows[ip] if t > cutoff]
        if len(self._windows[ip]) >= max_requests:
            return False
        self._windows[ip].append(now)
        return True


# Singleton
_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(max_requests: int = 10, window_seconds: int = 60):
    """FastAPI dependency for rate limiting."""
    async def _check(request: Request):
        ip = get_client_ip(request)
        if not _limiter.check(ip, max_requests, window_seconds):
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {max_requests} requests per {window_seconds}s.",
            )
    return _check
