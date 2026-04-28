"""
User authentication endpoints backed by Supabase Auth.

POST /user/signup  — create a new account
POST /user/login   — sign in with email/password
POST /user/logout  — sign out (invalidate session)
GET  /user/connections — list OAuth connection status per provider
POST /user/connections/{provider}/token — save a manual API token
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from supabase import create_client
from supabase_auth.errors import AuthApiError, AuthError

from app.api.dependencies import get_current_user
from app.api.limiter import limiter
from app.auth.encryption import decrypt_token_or_none, encrypt_token
from app.config import Settings, get_settings
from app.db.repositories import SupabaseOAuthConnectionRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["user-auth"])

_PROVIDERS = ("github", "notion", "linkedin", "medium")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    email: str


class SignupPendingResponse(BaseModel):
    status: str
    email: str
    message: str


class SaveTokenRequest(BaseModel):
    token: str = Field(..., min_length=1)
    extra: str | None = None


class ConnectionStatus(BaseModel):
    provider: str
    connected: bool
    token: str | None = None
    extra: str | None = None


class ConnectionsResponse(BaseModel):
    connections: list[ConnectionStatus]


class SaveTokenResponse(BaseModel):
    status: str


_MANUAL_TOKEN_PROVIDERS = {"github", "notion"}


# ---------------------------------------------------------------------------
# Dependency helper
# ---------------------------------------------------------------------------


def _get_oauth_repo(
    settings: Settings = Depends(get_settings),
) -> SupabaseOAuthConnectionRepository:
    client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )
    return SupabaseOAuthConnectionRepository(client)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=AuthResponse | SignupPendingResponse)
@limiter.limit("5/minute")
async def signup(
    request: Request,
    body: SignupRequest,
    settings: Settings = Depends(get_settings),
) -> AuthResponse | SignupPendingResponse:
    """Create a new user account via Supabase Auth."""
    client = create_client(
        settings.supabase_url,
        settings.supabase_anon_key.get_secret_value(),
    )
    try:
        result = client.auth.sign_up(
            {
                "email": body.email,
                "password": body.password,
                "options": {"email_redirect_to": settings.frontend_url},
            }
        )
    except AuthApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result.user:
        raise HTTPException(status_code=400, detail="Signup failed")

    if not result.session:
        return SignupPendingResponse(
            status="confirmation_pending",
            email=body.email,
            message="Check your email to confirm your account, then log in.",
        )

    return AuthResponse(
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
        user_id=result.user.id,
        email=result.user.email or body.email,
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    """Sign in with email and password."""
    client = create_client(
        settings.supabase_url,
        settings.supabase_anon_key.get_secret_value(),
    )
    try:
        result = client.auth.sign_in_with_password({"email": body.email, "password": body.password})
    except AuthApiError as exc:
        raise HTTPException(status_code=401, detail="Invalid credentials") from exc

    if not result.user or not result.session:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return AuthResponse(
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
        user_id=result.user.id,
        email=result.user.email or body.email,
    )


@router.post("/logout")
@limiter.limit("10/minute")
async def logout(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Sign out the current user."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            client = create_client(
                settings.supabase_url,
                settings.supabase_anon_key.get_secret_value(),
            )
            client.auth.sign_out()
        except (AuthApiError, AuthError) as exc:
            logger.warning("Logout error (non-fatal): %s", exc, exc_info=True)

    return {"status": "logged_out"}


@router.get("/connections", response_model=ConnectionsResponse)
@limiter.limit("20/minute")
async def get_connections(
    request: Request,
    user_id: str = Depends(get_current_user),
    oauth_repo: SupabaseOAuthConnectionRepository = Depends(_get_oauth_repo),
    settings: Settings = Depends(get_settings),
) -> ConnectionsResponse:
    """List OAuth connection status for all supported providers.

    For manual-token providers (github, notion), the decrypted token
    is returned so the frontend can restore it into session state.
    """
    kek = settings.blog_copilot_kek.get_secret_value()
    statuses: list[ConnectionStatus] = []
    for p in _PROVIDERS:
        conn = oauth_repo.get(user_id=user_id, provider=p)
        if conn is None:
            statuses.append(ConnectionStatus(provider=p, connected=False))
            continue
        token_val: str | None = None
        extra_val: str | None = None
        if p in _MANUAL_TOKEN_PROVIDERS:
            token_val = decrypt_token_or_none(conn.access_token_encrypted, kek)
            extra_val = decrypt_token_or_none(conn.refresh_token_encrypted, kek)
        statuses.append(
            ConnectionStatus(provider=p, connected=True, token=token_val, extra=extra_val)
        )
    return ConnectionsResponse(connections=statuses)


@router.post("/connections/{provider}/token", response_model=SaveTokenResponse)
@limiter.limit("10/minute")
async def save_token(
    request: Request,
    provider: str,
    body: SaveTokenRequest,
    user_id: str = Depends(get_current_user),
    oauth_repo: SupabaseOAuthConnectionRepository = Depends(_get_oauth_repo),
    settings: Settings = Depends(get_settings),
) -> SaveTokenResponse:
    """Save a manually-entered API token (GitHub PAT, Notion integration token)."""
    if provider not in _MANUAL_TOKEN_PROVIDERS:
        raise HTTPException(status_code=400, detail="Manual tokens not supported for this provider")

    kek = settings.blog_copilot_kek.get_secret_value()
    oauth_repo.upsert(
        user_id=user_id,
        provider=provider,
        access_token_encrypted=encrypt_token(body.token, kek),
        refresh_token_encrypted=encrypt_token(body.extra, kek) if body.extra else None,
        expires_at=None,
        scopes=None,
    )
    return SaveTokenResponse(status="saved")
