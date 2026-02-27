"""
Security middleware and utilities for the Agentic Trading App.
"""

import os
import re
import logging
from typing import Optional
from fastapi import Security, HTTPException, status, Query
from fastapi.security.api_key import APIKeyHeader

logger = logging.getLogger("SecurityLayer")

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_APP_API_KEY = os.getenv("APP_API_KEY", "")

_VALID_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


async def require_api_key(
    api_key_header: Optional[str] = Security(API_KEY_HEADER),
    api_key_query: Optional[str] = Query(default=None, alias="api_key"),
) -> str:
    """
    Validates the API key from either:
      - X-API-Key request header (standard axios/fetch calls)
      - ?api_key= query param (SSE EventSource — cannot set headers natively)
    """
    api_key = api_key_header or api_key_query

    if not _APP_API_KEY:
        logger.warning(
            "APP_API_KEY is not set. All requests are UNAUTHENTICATED. "
            "Set APP_API_KEY immediately for any non-local deployment."
        )
        return "dev-unauthenticated"

    if api_key != _APP_API_KEY:
        logger.warning("Rejected request — invalid or missing API key.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key.",
        )
    return api_key


def sanitize_ticker(raw: str) -> str:
    """Validates and normalises a ticker symbol to A-Z, 1-5 chars."""
    cleaned = raw.strip().upper()
    if not _VALID_TICKER_RE.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid ticker '{raw}'. Must be 1-5 uppercase letters (A-Z).",
        )
    return cleaned
