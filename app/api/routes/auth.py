"""
OAuth2 start/callback routes.

GET  /auth/{provider}/start
    — Generates a CSRF state token, stores it in a signed cookie,
      and redirects the user to the provider's authorization page.

GET  /auth/{provider}/callback
    — Validates the CSRF state, exchanges the authorization code for tokens,
      encrypts and persists the tokens, then redirects to the app home.

POST /auth/medium/token
    — Validates a Medium integration token, encrypts and persists it.
"""

import logging
from typing import Annotated, Any, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from supabase import create_client

from app.auth.encryption import encrypt_token, encrypt_token_or_none
from app.auth.oauth import (
    OAuthError,
    OAuthStateError,
    TokenResponse,
    build_authorization_url,
    exchange_code,
    generate_state,
    validate_state,
)
from app.auth.providers import PROVIDERS
from app.config import Settings, get_settings
from app.db.repositories import SupabaseOAuthConnectionRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_STATE_COOKIE = "oauth_state"


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def get_kek(settings: Settings = Depends(get_settings)) -> str:
    return settings.blog_copilot_kek.get_secret_value()


def get_oauth_repo(settings: Settings = Depends(get_settings)) -> SupabaseOAuthConnectionRepository:
    client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )
    return SupabaseOAuthConnectionRepository(client)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{provider}/start")
async def auth_start(
    provider: str,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Redirect the user to the OAuth provider's authorization page."""
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider!r}")

    state = generate_state()
    authorization_url = build_authorization_url(provider, state=state, settings=settings)

    response = RedirectResponse(url=authorization_url, status_code=302)
    response.set_cookie(
        key=_STATE_COOKIE,
        value=state,
        httponly=True,
        samesite="lax",
        secure=False,  # set to True in production behind HTTPS
        max_age=600,  # 10-minute window to complete the flow
    )
    return response


@router.get("/{provider}/callback")
async def auth_callback(
    provider: str,
    request: Request,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    settings: Settings = Depends(get_settings),
    kek: str = Depends(get_kek),
    oauth_repo: SupabaseOAuthConnectionRepository = Depends(get_oauth_repo),
) -> RedirectResponse:
    """Handle the provider callback: validate CSRF, exchange code, persist tokens."""
    # Provider-level error (e.g. user denied access)
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth provider error: {error}")

    if code is None:
        raise HTTPException(status_code=422, detail="Missing required query parameter: code")

    # CSRF validation
    stored_state = request.cookies.get(_STATE_COOKIE)
    try:
        validate_state(expected=stored_state or "", actual=state or "")
    except OAuthStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Exchange code for tokens
    try:
        tokens: TokenResponse = await exchange_code(
            provider, code=code, settings=settings
        )
    except OAuthError as exc:
        logger.exception("Token exchange failed for provider %s", provider)
        raise HTTPException(status_code=400, detail="Token exchange failed") from exc

    # Encrypt and persist
    # user_id: for now, extracted from JWT in a follow-up (Sprint 2).
    # Use a placeholder that will be replaced when Supabase Auth is wired up.
    user_id = request.headers.get("x-user-id", "anonymous")

    oauth_repo.upsert(
        user_id=user_id,
        provider=provider,
        access_token_encrypted=encrypt_token(tokens.access_token, kek),
        refresh_token_encrypted=encrypt_token_or_none(tokens.refresh_token, kek),
        expires_at=None,
        scopes=tokens.scope.split(",") if tokens.scope else None,
    )

    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key=_STATE_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Medium integration token
# ---------------------------------------------------------------------------

_MEDIUM_ME_URL = "https://api.medium.com/v1/me"


class MediumTokenError(Exception):
    """Raised when a Medium integration token fails validation."""


class MediumTokenRequest(BaseModel):
    token: str = Field(..., min_length=1, description="Medium integration token")


async def validate_medium_token(token: str) -> dict[str, Any]:
    """Call Medium API to verify the token and return the user profile.

    Raises:
        MediumTokenError: if the token is rejected or the request fails.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _MEDIUM_ME_URL,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise MediumTokenError(
            f"Medium rejected the token (HTTP {exc.response.status_code})"
        ) from exc
    except httpx.RequestError as exc:
        raise MediumTokenError("Could not reach Medium API") from exc

    body: dict[str, Any] = resp.json()
    if "data" not in body:
        raise MediumTokenError("Unexpected Medium API response format")
    return cast(dict[str, Any], body["data"])


@router.post("/medium/token")
async def medium_token(
    body: MediumTokenRequest,
    request: Request,
    kek: str = Depends(get_kek),
    oauth_repo: SupabaseOAuthConnectionRepository = Depends(get_oauth_repo),
) -> dict[str, str]:
    """Validate a Medium integration token, then encrypt and persist it."""
    try:
        await validate_medium_token(body.token)
    except MediumTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user_id = request.headers.get("x-user-id", "anonymous")

    oauth_repo.upsert(
        user_id=user_id,
        provider="medium",
        access_token_encrypted=encrypt_token(body.token, kek),
        refresh_token_encrypted=None,
        expires_at=None,
        scopes=None,
    )

    return {"status": "connected"}
