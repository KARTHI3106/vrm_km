"""
Token-bucket rate limiter for LLM API calls.

Prevents exceeding Groq free-tier limits (30 RPM) by throttling requests
with a configurable requests-per-minute budget.  Default is 25 RPM to
leave 5 RPM headroom.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton instance — shared across all agents in the same process
# ---------------------------------------------------------------------------
_global_limiter: Optional["TokenBucketRateLimiter"] = None


class TokenBucketRateLimiter:
    """Async-friendly token-bucket rate limiter.

    Args:
        requests_per_minute: Maximum sustained request rate.
        burst_size: Maximum number of tokens that can accumulate. Defaults
            to *requests_per_minute* (i.e. one-minute burst).
    """

    def __init__(
        self,
        requests_per_minute: int | None = None,
        burst_size: int | None = None,
    ) -> None:
        settings = get_settings()
        self.rpm: int = requests_per_minute or getattr(
            settings, "llm_requests_per_minute", 25
        )
        self.burst_size: int = burst_size or self.rpm
        self._tokens: float = float(self.burst_size)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

        logger.info(
            "TokenBucketRateLimiter initialised: rpm=%d, burst=%d",
            self.rpm,
            self.burst_size,
        )

    # -- internal -----------------------------------------------------------

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self.rpm / 60.0)
        self._tokens = min(self._tokens + new_tokens, float(self.burst_size))
        self._last_refill = now

    # -- public API ---------------------------------------------------------

    async def acquire(self, tokens: int = 1) -> None:
        """Wait until *tokens* are available, then consume them.

        This is the primary entry-point. Call ``await limiter.acquire()``
        before every LLM request.
        """
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

            # Not enough tokens — sleep briefly and retry.
            wait = tokens / (self.rpm / 60.0)
            logger.debug(
                "Rate limiter throttling: waiting %.2fs (%.1f tokens available)",
                wait,
                self._tokens,
            )
            await asyncio.sleep(wait)

    def try_acquire(self, tokens: int = 1) -> bool:
        """Non-blocking variant. Returns *True* if tokens were consumed."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    @property
    def available_tokens(self) -> float:
        """Current number of available tokens (informational)."""
        self._refill()
        return self._tokens


def get_rate_limiter() -> TokenBucketRateLimiter:
    """Return (or lazily create) the process-global rate limiter."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = TokenBucketRateLimiter()
    return _global_limiter
