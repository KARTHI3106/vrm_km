"""
Resilient LLM call wrapper with rate-limiting and retry logic.

* Integrates ``TokenBucketRateLimiter`` before every call.
* Retries on rate-limit (429) and transient server errors (5xx).
* Fails immediately on authentication errors (401/403).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.core.llm_rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

# Groq SDK exception names — imported lazily to avoid hard dependency.
_RATE_LIMIT_ERRORS = ("RateLimitError",)
_AUTH_ERRORS = ("AuthenticationError",)


def _is_rate_limit_error(exc: Exception) -> bool:
    """True if *exc* looks like a 429 / rate-limit error."""
    name = type(exc).__name__
    if name in _RATE_LIMIT_ERRORS:
        return True
    # Some SDKs wrap status codes in a generic ``APIStatusError``.
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status == 429:
        return True
    return False


def _is_auth_error(exc: Exception) -> bool:
    name = type(exc).__name__
    if name in _AUTH_ERRORS:
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status in (401, 403):
        return True
    return False


def _is_server_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if isinstance(status, int) and 500 <= status < 600:
        return True
    return False


async def call_llm_with_backoff(
    llm: BaseChatModel,
    messages: Any,
    *,
    max_retries: int = 3,
    backoff_base: float = 2.0,
) -> Any:
    """Invoke *llm* with rate-limiting, retries, and exponential backoff.

    Args:
        llm: LangChain chat model instance.
        messages: Prompt payload (string, list of BaseMessage, etc.).
        max_retries: Maximum retry attempts for transient failures.
        backoff_base: Base seconds for exponential backoff.

    Returns:
        The LLM response object.

    Raises:
        Exception: If all retries are exhausted or a non-retryable error
            is encountered (e.g. ``AuthenticationError``).
    """
    limiter = get_rate_limiter()
    last_exception: Exception | None = None

    for attempt in range(1, max_retries + 1):
        # ---------- rate-limit gate ----------
        await limiter.acquire()

        try:
            # Prefer async invoke if available.
            if hasattr(llm, "ainvoke"):
                result = await llm.ainvoke(messages)
            else:
                result = llm.invoke(messages)
            return result

        except Exception as exc:
            # Auth errors — fail immediately, no retry.
            last_exception = exc

            if _is_auth_error(exc):
                logger.error("LLM authentication error (not retryable): %s", exc)
                raise

            # Rate-limit or 5xx — exponential backoff then retry.
            if _is_rate_limit_error(exc) or _is_server_error(exc):
                wait = backoff_base ** attempt
                logger.warning(
                    "LLM transient error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    max_retries,
                    wait,
                    exc,
                )
                await asyncio.sleep(wait)
                continue

            # Unknown/unexpected error on last attempt — raise.
            if attempt == max_retries:
                logger.error(
                    "LLM call failed after %d attempts: %s", max_retries, exc
                )
                raise

            # Unknown error, still have retries — back off and retry.
            wait = backoff_base ** attempt
            logger.warning(
                "LLM unexpected error (attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                max_retries,
                wait,
                exc,
            )
            await asyncio.sleep(wait)

    # All retries exhausted — re-raise the last exception
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("LLM call exhausted all retries without returning.")
