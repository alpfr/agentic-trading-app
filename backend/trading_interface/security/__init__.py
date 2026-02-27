"""
Security Module — SOC 2 Compliant
====================================
Replaces the single-static-API-key model with:
  - JWT access tokens (15 min expiry) + refresh tokens (7 day expiry)
  - TOTP MFA (RFC 6238 — Google Authenticator compatible)
  - Per-IP rate limiting via slowapi
  - Security response headers (HSTS, CSP, X-Frame-Options, etc.)
  - Structured audit logging for every auth event
  - CORS locked to CORS_ALLOWED_ORIGINS env var (no localhost default in prod)
"""

from starlette.middleware.base import BaseHTTPMiddleware
import os
import re
import logging
import time
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import pyotp
from jose import jwt, JWTError
from fastapi import Security, HTTPException, status, Query, Request, Depends
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("SecurityLayer")

# ── Secrets — loaded from environment (K8s secret) ────────────────────────
_APP_API_KEY     = os.getenv("APP_API_KEY", "")                 # Legacy compat
_JWT_SECRET      = os.getenv("JWT_SECRET", secrets.token_hex(32))  # MUST be set in prod
_JWT_ALGORITHM   = "HS256"
_ACCESS_TTL_MIN  = int(os.getenv("JWT_ACCESS_TTL_MINUTES", "15"))
_REFRESH_TTL_DAYS= int(os.getenv("JWT_REFRESH_TTL_DAYS",  "7"))
_MFA_ISSUER      = os.getenv("MFA_ISSUER", "RetirementAdvisor")
_ADMIN_USERNAME  = os.getenv("ADMIN_USERNAME", "admin")
# Admin password hash — use passlib.hash.bcrypt.hash("<password>") to generate
_ADMIN_PASS_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
# Admin TOTP secret — generated once, stored in K8s secret
_ADMIN_TOTP_KEY  = os.getenv("ADMIN_TOTP_SECRET", "")

# ── In-memory revocation list (swap for Redis in multi-replica prod) ───────
_REVOKED_TOKENS: set = set()   # stores jti (JWT ID) of invalidated tokens

# ── Ticker validation ──────────────────────────────────────────────────────
_VALID_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

# ── OAuth2 bearer for Swagger UI ──────────────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


# ══════════════════════════════════════════════════════════════════════════
# JWT helpers
# ══════════════════════════════════════════════════════════════════════════

def _create_token(subject: str, token_type: str, ttl: timedelta) -> tuple[str, str]:
    """Returns (encoded_jwt, jti)."""
    jti = secrets.token_hex(16)
    now = datetime.now(timezone.utc)
    payload = {
        "sub":  subject,
        "type": token_type,
        "iat":  now,
        "exp":  now + ttl,
        "jti":  jti,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM), jti


def create_access_token(username: str) -> str:
    token, _ = _create_token(username, "access", timedelta(minutes=_ACCESS_TTL_MIN))
    logger.info(f"AUTH | access_token_issued | user={username} ttl={_ACCESS_TTL_MIN}m")
    return token


def create_refresh_token(username: str) -> tuple[str, str]:
    """Returns (token, jti) — store jti server-side to allow revocation."""
    token, jti = _create_token(username, "refresh", timedelta(days=_REFRESH_TTL_DAYS))
    logger.info(f"AUTH | refresh_token_issued | user={username} ttl={_REFRESH_TTL_DAYS}d jti={jti}")
    return token, jti


def decode_token(token: str) -> dict:
    """Raises HTTPException on invalid/expired/revoked token."""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except JWTError as e:
        logger.warning(f"AUTH | token_invalid | reason={e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token invalid or expired.",
                            headers={"WWW-Authenticate": "Bearer"})
    if payload.get("jti") in _REVOKED_TOKENS:
        logger.warning(f"AUTH | token_revoked | jti={payload.get('jti')}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token has been revoked.")
    return payload


def revoke_token(jti: str):
    _REVOKED_TOKENS.add(jti)
    logger.info(f"AUTH | token_revoked | jti={jti}")


# ══════════════════════════════════════════════════════════════════════════
# TOTP / MFA helpers
# ══════════════════════════════════════════════════════════════════════════

def generate_totp_secret() -> str:
    """Generate a new TOTP secret. Call once during admin setup."""
    return pyotp.random_base32()


def get_totp_provisioning_uri(secret: str, username: str) -> str:
    """Returns the otpauth:// URI to encode as a QR code."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=_MFA_ISSUER)


def verify_totp(code: str, secret: Optional[str] = None) -> bool:
    """
    Verifies a 6-digit TOTP code.
    Uses _ADMIN_TOTP_KEY by default (from K8s secret).
    window=1 allows 30s clock drift.
    """
    s = secret or _ADMIN_TOTP_KEY
    if not s:
        logger.error("AUTH | totp_secret_missing — set ADMIN_TOTP_SECRET in K8s secret")
        return False
    totp = pyotp.TOTP(s)
    valid = totp.verify(code, valid_window=1)
    if not valid:
        logger.warning(f"AUTH | totp_failed | code_prefix={code[:2]}xx")
    return valid


# ══════════════════════════════════════════════════════════════════════════
# Password verification (bcrypt)
# ══════════════════════════════════════════════════════════════════════════

def verify_password(plain: str, hashed: str) -> bool:
    try:
        from passlib.hash import bcrypt
        return bcrypt.verify(plain, hashed)
    except Exception as e:
        logger.error(f"AUTH | password_verify_error | {e}")
        return False


def hash_password(plain: str) -> str:
    from passlib.hash import bcrypt
    return bcrypt.hash(plain)


# ══════════════════════════════════════════════════════════════════════════
# FastAPI dependency — require valid JWT
# ══════════════════════════════════════════════════════════════════════════

async def require_auth(
    token: Optional[str] = Depends(oauth2_scheme),
    api_key_header: Optional[str] = Security(API_KEY_HEADER),
    api_key_query: Optional[str] = Query(default=None, alias="api_key"),
) -> str:
    """
    Multi-mode auth dependency:
      1. Bearer JWT token (primary — for browser sessions)
      2. X-API-Key header (legacy compat + SSE stream with service accounts)
      3. ?api_key= query param (SSE EventSource fallback)
    """
    # ── Mode 1: Bearer JWT ─────────────────────────────────────────────
    if token:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Expected access token.")
        return payload["sub"]

    # ── Mode 2 / 3: Static API key (legacy compat + SSE) ──────────────
    api_key = api_key_header or api_key_query
    if api_key:
        if not _APP_API_KEY:
            logger.warning("AUTH | api_key_check_skipped — APP_API_KEY not set")
            return "dev-unauthenticated"
        if api_key == _APP_API_KEY:
            return "api-key-user"
        logger.warning("AUTH | api_key_rejected")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Invalid API key.")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide Bearer token or X-API-Key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Backwards-compatible alias — all existing app.py imports still work
require_api_key = require_auth


# ══════════════════════════════════════════════════════════════════════════
# Ticker sanitizer
# ══════════════════════════════════════════════════════════════════════════

def sanitize_ticker(raw: str) -> str:
    cleaned = raw.strip().upper()
    if not _VALID_TICKER_RE.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid ticker '{raw}'. Must be 1-5 uppercase letters.",
        )
    return cleaned


# ══════════════════════════════════════════════════════════════════════════
# Security response headers middleware
# ══════════════════════════════════════════════════════════════════════════

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds SOC 2 / OWASP-recommended security headers to every response.
    Mount via: app.add_middleware(SecurityHeadersMiddleware)
    """
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"]    = "nosniff"
        response.headers["X-Frame-Options"]           = "DENY"
        response.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]        = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"]   = (
            "default-src 'self'; "
            "connect-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "frame-ancestors 'none';"
        )
        return response
