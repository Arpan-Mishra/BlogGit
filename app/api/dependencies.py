"""
FastAPI dependencies for user authentication.

get_current_user — requires a valid Supabase JWT; raises 401 if missing/invalid.
get_optional_user — returns user_id from JWT or "anonymous" if no token provided.
"""

import logging

from fastapi import Depends, HTTPException, Request
from supabase import create_client
from supabase_auth.errors import AuthApiError, AuthError

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


async def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    """Extract and validate user_id from the Authorization header.

    Raises HTTPException 401 if the token is missing or invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")

    token = auth_header[7:]
    try:
        client = create_client(
            settings.supabase_url,
            settings.supabase_anon_key.get_secret_value(),
        )
        user_response = client.auth.get_user(token)
    except (AuthApiError, AuthError) as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid auth token") from exc

    if not user_response or not user_response.user:
        raise HTTPException(status_code=401, detail="Invalid auth token")

    return user_response.user.id


async def get_optional_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    """Extract user_id from JWT if present, otherwise return 'anonymous'."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return "anonymous"

    token = auth_header[7:]
    try:
        client = create_client(
            settings.supabase_url,
            settings.supabase_anon_key.get_secret_value(),
        )
        user_response = client.auth.get_user(token)
    except (AuthApiError, AuthError) as exc:
        logger.warning("Optional JWT validation failed: %s", exc)
        return "anonymous"

    if not user_response or not user_response.user:
        return "anonymous"

    return user_response.user.id
