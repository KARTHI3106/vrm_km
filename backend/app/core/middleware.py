"""
Rate limiting, security headers, and request validation middleware.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_RATE = 60
DEFAULT_WINDOW = 60

SQL_INJECTION_PATTERNS = re.compile(
    r"(?:';|\";|--|\b(?:DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|EXEC|UNION|SELECT)\b.*\b(?:FROM|TABLE|INTO|SET|WHERE)\b)",
    re.IGNORECASE,
)

XSS_PATTERNS = re.compile(
    r"<\s*script|javascript\s*:|on\w+\s*=|<\s*iframe|<\s*object|<\s*embed",
    re.IGNORECASE,
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if settings.app_env == "development" and not settings.jwt_secret:
            return await call_next(request)

        if request.url.path.startswith("/docs") or request.url.path.startswith(
            "/openapi"
        ):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        key = f"vrm:ratelimit:{client_ip}"

        try:
            from app.core.redis_state import get_redis

            redis = get_redis()
            now = time.time()
            window_start = now - DEFAULT_WINDOW
            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, DEFAULT_WINDOW)
            results = pipe.execute()
            count = results[2]

            if count > DEFAULT_RATE:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Rate limit exceeded. Try again later."},
                )
        except Exception:
            pass

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        if not response.headers.get("Content-Security-Policy"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;"
            )
        return response


class InputValidationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" not in content_type:
                try:
                    body = await request.body()
                    if body:
                        text = body.decode("utf-8", errors="ignore")
                        if SQL_INJECTION_PATTERNS.search(text):
                            logger.warning(
                                "Potential SQL injection blocked from %s",
                                request.client.host if request.client else "unknown",
                            )
                            return JSONResponse(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                content={"detail": "Invalid input detected."},
                            )
                        if XSS_PATTERNS.search(text):
                            logger.warning(
                                "Potential XSS blocked from %s",
                                request.client.host if request.client else "unknown",
                            )
                            return JSONResponse(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                content={"detail": "Invalid input detected."},
                            )
                except Exception:
                    pass
        return await call_next(request)
