"""
Rate Limiting — SOC 2 Control
================================
Sliding window rate limits per client IP using slowapi (starlette-limiter).

Limits:
  - Auth endpoints (/api/auth/*):  5 requests / minute
  - API read endpoints:           60 requests / minute
  - API write/trigger endpoints:  10 requests / minute
  - Global fallback:             120 requests / minute

On limit breach: 429 Too Many Requests with Retry-After header.
All breaches are logged to the security audit log.
"""
import logging
from fastapi import Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

logger = logging.getLogger("RateLimiter")


def _get_ip(request: Request) -> str:
    """
    Extract real client IP from X-Forwarded-For (ALB sets this).
    Falls back to direct connection IP.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = get_remote_address(request)
    return ip


# Module-level limiter — imported and mounted in app.py
limiter = Limiter(key_func=_get_ip, default_limits=["120/minute"])


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Returns 429 with Retry-After header and logs the breach."""
    ip = _get_ip(request)
    logger.warning(
        f"RATE_LIMIT | ip={ip} path={request.url.path} limit={exc.limit}"
    )
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": f"Too many requests. Limit: {exc.limit}. Try again later.",
            "path": str(request.url.path),
        },
        headers={"Retry-After": "60"},
    )
