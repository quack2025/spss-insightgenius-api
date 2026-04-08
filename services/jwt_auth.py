"""Supabase JWT verification service.

Verifies JWTs issued by Supabase Auth and syncs user to local DB.
Only ES256 algorithm accepted (no HS256 fallback — prevents algorithm confusion attacks).
"""

import logging

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models.user import User, UserPreferences

logger = logging.getLogger(__name__)


class JWTVerificationError(Exception):
    """Raised when JWT verification fails."""


def verify_supabase_jwt(token: str) -> dict:
    """Verify a Supabase JWT and return its claims.

    Returns dict with at least: sub, email, aud.
    Raises JWTVerificationError on any failure.
    """
    settings = get_settings()

    if not settings.supabase_jwt_secret:
        raise JWTVerificationError("Supabase JWT auth not configured on this server")

    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise JWTVerificationError("Token expired")
    except jwt.InvalidAudienceError:
        raise JWTVerificationError("Invalid token audience")
    except jwt.DecodeError as e:
        raise JWTVerificationError(f"Invalid token: {e}")
    except jwt.InvalidTokenError as e:
        raise JWTVerificationError(f"Token validation failed: {e}")

    if not payload.get("sub"):
        raise JWTVerificationError("Token missing 'sub' claim")

    return payload


async def get_or_create_user(db: AsyncSession, jwt_claims: dict) -> User:
    """Find or create a local user from Supabase JWT claims.

    On first login, creates the user and default preferences.
    On subsequent logins, returns existing user (updates email/name if changed).
    """
    supabase_uid = jwt_claims["sub"]
    email = jwt_claims.get("email", "")
    name = jwt_claims.get("user_metadata", {}).get("name", "") or email.split("@")[0]

    # Look up by supabase_uid
    result = await db.execute(
        select(User).where(User.supabase_uid == supabase_uid)
    )
    user = result.scalar_one_or_none()

    if user is not None:
        # Update email/name if changed in Supabase
        changed = False
        if email and user.email != email:
            user.email = email
            changed = True
        if name and user.name != name:
            user.name = name
            changed = True
        if changed:
            await db.flush()
        return user

    # Create new user
    user = User(
        supabase_uid=supabase_uid,
        email=email,
        name=name,
    )
    db.add(user)
    await db.flush()

    # Create default preferences
    prefs = UserPreferences(user_id=user.id)
    db.add(prefs)
    await db.flush()

    logger.info("Created new user: %s (%s)", email, supabase_uid[:8])
    return user
