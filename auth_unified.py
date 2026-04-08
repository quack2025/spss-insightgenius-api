"""Unified authentication — supports both API keys and Supabase JWT.

Usage in endpoints:

    # Accept EITHER API key OR Supabase JWT:
    @router.post("/v1/projects")
    async def create_project(auth: AuthContext = Depends(get_auth_context)):
        ...

    # Require Supabase JWT (platform user with DB record):
    @router.get("/v1/users/me")
    async def get_me(auth: AuthContext = Depends(require_user)):
        ...

Existing endpoints continue using `require_auth` from auth.py (API keys only).
"""

import logging
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from auth import KeyConfig, require_auth
from config import get_settings
from db.database import get_db
from db.models.user import User
from services.jwt_auth import JWTVerificationError, get_or_create_user, verify_supabase_jwt

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Unified auth context available to all endpoints."""

    user_id: str  # UUID string (from JWT sub or API key name)
    auth_method: str  # "jwt" | "api_key"
    plan: str  # "free" | "pro" | "business" | "enterprise"
    scopes: list[str] = field(default_factory=list)
    db_user: User | None = None  # Only populated for JWT auth


def _is_api_key(token: str) -> bool:
    """Check if a Bearer token is an API key (sk_live_/sk_test_)."""
    return token.startswith(("sk_live_", "sk_test_"))


async def get_auth_context(request: Request) -> AuthContext:
    """FastAPI dependency: authenticate via API key OR Supabase JWT.

    Dispatches based on token prefix:
    - sk_live_* / sk_test_* → API key auth (existing system)
    - anything else → Supabase JWT verification + user sync
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Missing Authorization: Bearer <token> header"},
        )

    token = auth_header[7:]

    if _is_api_key(token):
        return await _auth_via_api_key(request, token)
    else:
        return await _auth_via_jwt(request, token)


async def _auth_via_api_key(request: Request, token: str) -> AuthContext:
    """Authenticate using existing API key system."""
    # Reuse the existing require_auth dependency logic
    key_config: KeyConfig = await require_auth(request)

    return AuthContext(
        user_id=key_config.name,
        auth_method="api_key",
        plan=key_config.plan,
        scopes=key_config.scopes,
        db_user=None,
    )


async def _auth_via_jwt(request: Request, token: str) -> AuthContext:
    """Authenticate using Supabase JWT and sync user to DB."""
    settings = get_settings()

    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "JWT auth not configured. Use an API key (sk_live_/sk_test_)."},
        )

    if not settings.has_database:
        raise HTTPException(
            status_code=503,
            detail={"code": "SERVICE_UNAVAILABLE", "message": "Database not configured. JWT auth requires PostgreSQL."},
        )

    try:
        claims = verify_supabase_jwt(token)
    except JWTVerificationError as e:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": str(e)},
        )

    # Get DB session and sync user
    db: AsyncSession
    async for db in get_db():
        user = await get_or_create_user(db, claims)

        # Attach to request state for middleware compatibility
        request.state.key_config = KeyConfig(
            key_hash="jwt",
            name=str(user.id),
            plan=user.plan.value,
            scopes=["metadata", "process", "convert", "ai", "library"],
        )

        return AuthContext(
            user_id=str(user.id),
            auth_method="jwt",
            plan=user.plan.value,
            scopes=["metadata", "process", "convert", "ai", "library"],
            db_user=user,
        )

    # Should never reach here
    raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Auth failed"})


async def require_user(request: Request) -> AuthContext:
    """FastAPI dependency: require Supabase JWT (platform user).

    Use this for endpoints that need a db_user (projects, conversations, etc.).
    API keys are NOT accepted.
    """
    auth = await get_auth_context(request)

    if auth.auth_method != "jwt":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "FORBIDDEN",
                "message": "This endpoint requires user authentication (Supabase JWT), not an API key.",
            },
        )

    return auth
