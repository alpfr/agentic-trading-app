"""
Auth Router — /api/auth/*
==========================
Endpoints for JWT login, MFA verification, token refresh, logout,
and TOTP setup/QR code generation.

Flow:
  1. POST /api/auth/login     { username, password }
     → validates credentials
     → if MFA enabled: returns { mfa_required: true, session_token }
     → if MFA disabled: returns { access_token, refresh_token }

  2. POST /api/auth/mfa/verify   { session_token, totp_code }
     → validates TOTP code
     → returns { access_token, refresh_token }

  3. POST /api/auth/refresh  { refresh_token }
     → validates refresh token
     → returns { access_token }

  4. POST /api/auth/logout   (requires auth)
     → revokes access + refresh tokens

  5. GET  /api/auth/mfa/setup (requires auth)
     → returns provisioning URI + QR code (first-time setup)

  6. GET  /api/auth/me  (requires auth)
     → returns current user info
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends
from pydantic import BaseModel

from trading_interface.security import (
    verify_password, create_access_token, create_refresh_token,
    decode_token, revoke_token, verify_totp,
    get_totp_provisioning_uri, generate_totp_secret,
    require_auth, _ADMIN_USERNAME, _ADMIN_PASS_HASH, _ADMIN_TOTP_KEY,
    _JWT_SECRET, _JWT_ALGORITHM, _ACCESS_TTL_MIN,
)
from trading_interface.security.audit_log import audit_from_request

logger = logging.getLogger("AuthRouter")
router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── In-memory MFA session store (use Redis in multi-replica prod) ──────────
# Maps session_token → { username, expires_at }
_MFA_SESSIONS: dict = {}
_MFA_SESSION_TTL_SECONDS = 300   # 5-minute window to enter TOTP code

def _mfa_enabled() -> bool:
    """Check at request time so secret updates take effect after restart."""
    return bool(os.getenv("ADMIN_TOTP_SECRET", ""))


# ── Request/Response models ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class MFAVerifyRequest(BaseModel):
    session_token: str
    totp_code: str

class RefreshRequest(BaseModel):
    refresh_token: str

class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int  # seconds

class MFARequiredResponse(BaseModel):
    mfa_required: bool = True
    session_token: str
    message: str = "Enter your 6-digit authenticator code."


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("/login", response_model=None, summary="Login with username + password")
async def login(body: LoginRequest, request: Request):
    """
    Step 1 of auth flow.
    Returns MFARequiredResponse if MFA is enabled, else TokenResponse.
    """
    import secrets as _secrets

    # Validate credentials
    if body.username != _ADMIN_USERNAME():
        audit_from_request(request, "LOGIN_FAILED", body.username,
                            detail="Unknown username", success=False)
        # Constant-time response — don't reveal whether username exists
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid username or password.")

    if not _ADMIN_PASS_HASH():
        # Dev mode — no password hash set → allow access with warning
        logger.warning("AUTH | no password hash set — dev mode login accepted")
        audit_from_request(request, "LOGIN_SUCCESS", body.username,
                            detail="dev-mode (no password hash configured)")
    elif not verify_password(body.password, _ADMIN_PASS_HASH()):
        audit_from_request(request, "LOGIN_FAILED", body.username,
                            detail="Wrong password", success=False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid username or password.")

    # If MFA is enabled, issue a short-lived session token
    if _mfa_enabled():
        session_token = _secrets.token_urlsafe(32)
        import time
        _MFA_SESSIONS[session_token] = {
            "username":   body.username,
            "expires_at": time.time() + _MFA_SESSION_TTL_SECONDS,
        }
        audit_from_request(request, "MFA_CHALLENGE_ISSUED", body.username,
                            detail="Password OK — MFA required")
        return MFARequiredResponse(session_token=session_token)

    # MFA disabled — issue tokens directly
    access  = create_access_token(body.username)
    refresh, _ = create_refresh_token(body.username)
    audit_from_request(request, "LOGIN_SUCCESS", body.username,
                        detail="MFA not enabled")
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=_ACCESS_TTL_MIN * 60,
    )


@router.post("/mfa/verify", response_model=TokenResponse, summary="Verify TOTP code")
async def mfa_verify(body: MFAVerifyRequest, request: Request):
    """Step 2: verify the 6-digit TOTP code and return real tokens."""
    import time

    session = _MFA_SESSIONS.get(body.session_token)
    if not session:
        audit_from_request(request, "MFA_FAILED", detail="Invalid session token", success=False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired MFA session.")

    if time.time() > session["expires_at"]:
        del _MFA_SESSIONS[body.session_token]
        audit_from_request(request, "MFA_FAILED", session["username"],
                            detail="MFA session expired", success=False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="MFA session expired. Please login again.")

    if not verify_totp(body.totp_code.strip()):
        audit_from_request(request, "MFA_FAILED", session["username"],
                            detail="Wrong TOTP code", success=False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid authenticator code.")

    # TOTP verified — issue tokens and clear session
    username = session["username"]
    del _MFA_SESSIONS[body.session_token]

    access  = create_access_token(username)
    refresh, _ = create_refresh_token(username)

    audit_from_request(request, "MFA_SUCCESS", username,
                        detail="TOTP verified — tokens issued")
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=_ACCESS_TTL_MIN * 60,
    )


@router.post("/refresh", response_model=TokenResponse, summary="Refresh access token")
async def refresh_token_endpoint(body: RefreshRequest, request: Request):
    """Exchange a valid refresh token for a new access token."""
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Expected refresh token.")
    username = payload["sub"]
    # Rotate: revoke old refresh token, issue new pair
    revoke_token(payload["jti"])
    access       = create_access_token(username)
    refresh, _   = create_refresh_token(username)
    audit_from_request(request, "TOKEN_REFRESHED", username)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=_ACCESS_TTL_MIN * 60,
    )


@router.post("/logout", summary="Logout and revoke tokens")
async def logout(request: Request, username: str = Depends(require_auth)):
    """
    Revokes the current access token.
    Client should also delete stored refresh token.
    """
    # Extract JTI from authorization header to revoke it
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            from jose import jwt as _jwt
            payload = _jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
            revoke_token(payload.get("jti", ""))
        except Exception:
            pass
    audit_from_request(request, "LOGOUT", username)
    return {"message": "Logged out successfully."}


@router.get("/mfa/setup", summary="Get TOTP setup QR code (first-time)")
async def mfa_setup(username: str = Depends(require_auth)):
    """
    Returns the TOTP provisioning URI.
    Encode as QR code and scan with Google Authenticator or Authy.
    Only useful if ADMIN_TOTP_SECRET is not yet set — for initial enrollment.
    """
    new_secret = generate_totp_secret()
    uri = get_totp_provisioning_uri(new_secret, username)
    return {
        "totp_secret": new_secret,
        "provisioning_uri": uri,
        "instructions": (
            "1. Copy the totp_secret and store it as ADMIN_TOTP_SECRET in your K8s secret. "
            "2. Scan the provisioning_uri as a QR code with Google Authenticator or Authy. "
            "3. Restart the pod to activate MFA. "
            "Never share the totp_secret — treat it like a password."
        ),
    }


@router.get("/me", summary="Get current user info")
async def get_me(username: str = Depends(require_auth)):
    return {
        "username":    username,
        "mfa_enabled": MFA_ENABLED,
        "token_ttl_minutes": _ACCESS_TTL_MIN,
    }
