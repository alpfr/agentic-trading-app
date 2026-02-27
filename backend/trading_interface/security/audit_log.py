"""
Structured Security Audit Log — SOC 2 Control
================================================
Every authentication event is written as a structured JSON log entry
to stdout so Kubernetes → CloudWatch Logs can ingest, search, and alert.

Log format is JSON-Lines (one JSON object per line) for easy parsing
by CloudWatch Logs Insights, Splunk, Datadog, etc.

Events logged:
  LOGIN_SUCCESS, LOGIN_FAILED, MFA_SUCCESS, MFA_FAILED,
  TOKEN_ISSUED, TOKEN_REVOKED, TOKEN_EXPIRED, TOKEN_INVALID,
  API_KEY_ACCEPTED, API_KEY_REJECTED,
  RATE_LIMIT_BREACH, PERMISSION_DENIED,
  PASSWORD_CHANGE, TOTP_SETUP, LOGOUT
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

_audit_logger = logging.getLogger("SecurityAudit")
# Ensure this logger writes to stdout as JSON regardless of root logger config
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
_audit_logger.addHandler(_handler)
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False


def audit(
    event:       str,
    username:    Optional[str] = None,
    ip:          Optional[str] = None,
    user_agent:  Optional[str] = None,
    detail:      Optional[str] = None,
    success:     bool = True,
    extra:       Optional[dict] = None,
):
    """
    Emit a single structured audit log entry.

    Args:
        event:      Event type string (e.g. 'LOGIN_SUCCESS')
        username:   Authenticated username or None
        ip:         Client IP address
        user_agent: User-Agent header value
        detail:     Human-readable description
        success:    True = success, False = failure/anomaly
        extra:      Additional key-value pairs to include
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service":   "retirement-advisor",
        "log_type":  "security_audit",
        "event":     event,
        "success":   success,
        "username":  username or "anonymous",
        "ip":        ip or "unknown",
        "user_agent": (user_agent or "")[:200],   # truncate
        "detail":    detail or "",
    }
    if extra:
        entry.update(extra)

    level = logging.INFO if success else logging.WARNING
    _audit_logger.log(level, json.dumps(entry, default=str))


def audit_from_request(request, event: str, username: Optional[str] = None,
                        detail: Optional[str] = None, success: bool = True,
                        extra: Optional[dict] = None):
    """Convenience wrapper that extracts IP + UA from a FastAPI Request object."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else str(request.client.host if request.client else "unknown")
    ua = request.headers.get("User-Agent", "")
    audit(event=event, username=username, ip=ip, user_agent=ua,
          detail=detail, success=success, extra=extra)
