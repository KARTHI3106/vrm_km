"""
Tests for the TokenBucketRateLimiter and LLM wrapper utilities.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.llm_rate_limiter import TokenBucketRateLimiter


# ═══════════════════════════════════════════════════════════════════
# TokenBucketRateLimiter
# ═══════════════════════════════════════════════════════════════════


class TestTokenBucketRateLimiter:
    """Tests for the token-bucket rate limiter."""

    @pytest.fixture
    def limiter(self):
        """Create a limiter with a small budget for fast tests."""
        return TokenBucketRateLimiter(requests_per_minute=60, burst_size=5)

    def test_initial_burst(self, limiter):
        """Limiter starts with burst_size tokens available."""
        assert limiter.available_tokens == 5.0

    def test_try_acquire_consumes_token(self, limiter):
        """try_acquire returns True and reduces token count."""
        assert limiter.try_acquire() is True
        assert limiter.available_tokens < 5.0

    def test_try_acquire_respects_budget(self, limiter):
        """After exhausting tokens, try_acquire returns False."""
        for _ in range(5):
            limiter.try_acquire()
        assert limiter.try_acquire() is False

    @pytest.mark.asyncio
    async def test_acquire_blocks_when_empty(self):
        """acquire() blocks when tokens are exhausted, then proceeds after refill."""
        limiter = TokenBucketRateLimiter(requests_per_minute=600, burst_size=2)
        # Exhaust all tokens
        await limiter.acquire()
        await limiter.acquire()
        # Next acquire should block briefly
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed > 0.0  # It had to wait

    @pytest.mark.asyncio
    async def test_acquire_permits_when_available(self):
        """acquire() returns immediately when tokens are available."""
        limiter = TokenBucketRateLimiter(requests_per_minute=600, burst_size=10)
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should be essentially instant

    def test_refill_adds_tokens(self, limiter):
        """Tokens refill over time."""
        limiter.try_acquire()
        initial = limiter.available_tokens
        # Simulate passage of time
        limiter._last_refill -= 1.0  # 1 second ago
        limiter._refill()
        assert limiter.available_tokens > initial

    def test_token_cap_at_burst_size(self, limiter):
        """Tokens never exceed burst_size."""
        limiter._last_refill -= 600  # 10 minutes ago
        limiter._refill()
        assert limiter.available_tokens <= 5.0


# ═══════════════════════════════════════════════════════════════════
# LLM Wrapper
# ═══════════════════════════════════════════════════════════════════


class TestLLMWrapper:
    """Tests for call_llm_with_backoff()."""

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Successful LLM call returns response immediately."""
        from app.core.llm_wrapper import call_llm_with_backoff

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value="Hello!")

        with patch("app.core.llm_wrapper.get_rate_limiter") as mock_rl:
            mock_rl.return_value.acquire = AsyncMock()
            result = await call_llm_with_backoff(mock_llm, "Hi")
            assert result == "Hello!"
            mock_llm.ainvoke.assert_called_once_with("Hi")

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self):
        """Retries on rate-limit error with backoff."""
        from app.core.llm_wrapper import call_llm_with_backoff

        # First call raises 429, second succeeds
        error = Exception("rate limit")
        error.status_code = 429
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[error, "ok"])

        with patch("app.core.llm_wrapper.get_rate_limiter") as mock_rl:
            mock_rl.return_value.acquire = AsyncMock()
            result = await call_llm_with_backoff(mock_llm, "Hi", backoff_base=0.01)
            assert result == "ok"
            assert mock_llm.ainvoke.call_count == 2

    @pytest.mark.asyncio
    async def test_fails_immediately_on_auth_error(self):
        """Auth errors are not retried."""
        from app.core.llm_wrapper import call_llm_with_backoff

        error = Exception("invalid key")
        error.status_code = 401
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=error)

        with patch("app.core.llm_wrapper.get_rate_limiter") as mock_rl:
            mock_rl.return_value.acquire = AsyncMock()
            with pytest.raises(Exception, match="invalid key"):
                await call_llm_with_backoff(mock_llm, "Hi", backoff_base=0.01)
            # Should have been called exactly once (no retry)
            assert mock_llm.ainvoke.call_count == 1

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        """After max_retries, raises the last exception."""
        from app.core.llm_wrapper import call_llm_with_backoff

        error = Exception("server error")
        error.status_code = 500
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=error)

        with patch("app.core.llm_wrapper.get_rate_limiter") as mock_rl:
            mock_rl.return_value.acquire = AsyncMock()
            with pytest.raises(Exception, match="server error"):
                await call_llm_with_backoff(
                    mock_llm, "Hi", max_retries=2, backoff_base=0.01
                )
            assert mock_llm.ainvoke.call_count == 2
