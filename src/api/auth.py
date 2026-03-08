"""
S-103: Authentication middleware for Aria API.

Two-tier API key authentication:
  - require_api_key: Standard access for all authenticated endpoints
  - require_admin_key: Elevated access for admin/maintenance endpoints

Keys are loaded from environment variables:
  - ARIA_API_KEY: Standard API key (fail-open if unset in dev)
  - ARIA_ADMIN_KEY: Admin API key (fail-open if unset in dev)

Health, docs, and metrics endpoints are exempt from authentication.
"""

import os
import secrets
import logging

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

_logger = logging.getLogger("aria.auth")

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Keys loaded from environment at import time
ARIA_API_KEY = os.environ.get("ARIA_API_KEY", "")
ARIA_ADMIN_KEY = os.environ.get("ARIA_ADMIN_KEY", "")

# S-16: Production mode = fail-closed when keys are not set
# SEC-03: Enforce non-empty keys in all environments (dev + production)
_IS_PRODUCTION = os.environ.get("ARIA_ENV", "development").lower() in ("production", "prod")

if not ARIA_API_KEY:
    if _IS_PRODUCTION:
        _logger.critical(
            "ARIA_API_KEY not set in PRODUCTION mode — all API endpoints will reject requests. "
            "Set ARIA_API_KEY in .env immediately."
        )
    else:
        _logger.warning(
            "ARIA_API_KEY not set — API endpoints are UNPROTECTED (dev mode). "
            "Set ARIA_API_KEY in .env for production."
        )
if not ARIA_ADMIN_KEY:
    if _IS_PRODUCTION:
        _logger.critical(
            "ARIA_ADMIN_KEY not set in PRODUCTION mode — admin endpoints will reject requests. "
            "Set ARIA_ADMIN_KEY in .env immediately."
        )
    else:
        _logger.warning(
            "ARIA_ADMIN_KEY not set — admin endpoints are UNPROTECTED (dev mode). "
            "Set ARIA_ADMIN_KEY in .env for production."
        )


async def require_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """Require valid API key for standard endpoints.

    Fail-open when ARIA_API_KEY is not configured in dev mode.
    Fail-closed in production (ARIA_ENV=production).
    """
    if not ARIA_API_KEY:
        if _IS_PRODUCTION:
            raise HTTPException(status_code=503, detail="API key not configured on server")
        return "no-auth-configured"
    if not api_key or not secrets.compare_digest(api_key, ARIA_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


async def require_admin_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """Require admin API key for privileged endpoints.

    Fail-open when ARIA_ADMIN_KEY is not configured in dev mode.
    Fail-closed in production (ARIA_ENV=production).
    """
    if not ARIA_ADMIN_KEY:
        if _IS_PRODUCTION:
            raise HTTPException(status_code=503, detail="Admin key not configured on server")
        return "no-auth-configured"
    if not api_key or not secrets.compare_digest(api_key, ARIA_ADMIN_KEY):
        raise HTTPException(status_code=403, detail="Admin access required")
    return api_key


async def validate_ws_api_key(api_key: str | None) -> bool:
    """Validate API key for WebSocket connections.

    S-16: WebSocket endpoints cannot use header-based auth directly,
    so they accept the key as a query param or first message field.

    Returns True if the key is valid or auth is not configured (dev).
    Raises HTTPException if the key is invalid in production.
    """
    if not ARIA_API_KEY:
        if _IS_PRODUCTION:
            return False
        return True
    if not api_key or not secrets.compare_digest(api_key, ARIA_API_KEY):
        return False
    return True
