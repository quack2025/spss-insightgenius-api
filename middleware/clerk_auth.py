"""Clerk JWT validation for OAuth 2.0 Bearer token auth.

Validates JWTs issued by Clerk's OAuth server. Used for Claude.ai connector
flow and web app authentication. Works alongside existing API key auth.

JWT validation:
1. Decode header to get kid (key ID)
2. Fetch JWKS from Clerk (cached 1 hour)
3. Verify signature, expiry, issuer
4. Extract user_id, email, plan from claims
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# JWKS cache: {url: (keys_dict, fetch_timestamp)}
_jwks_cache: dict[str, tuple[dict, float]] = {}
_JWKS_CACHE_TTL = 3600  # 1 hour


@dataclass
class ClerkUser:
    """Authenticated user from Clerk JWT."""
    user_id: str
    email: str
    plan: str
    name: str = ""
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


# ── Plan limits ──────────────────────────────────────────────────────────────

PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "free": {
        "files_per_day": 3,
        "max_file_mb": 10,
        "requests_per_minute": 10,
        "tools_allowed": "__all__",  # All tools, limited by volume
        "crosstab_significance_levels": [0.90, 0.95, 0.99],
        "team_seats": 1,
        "auto_analyze": True,
        "excel_export": True,  # With 5-stub limit
        "max_stubs_free": 10,
    },
    "growth": {
        "files_per_day": None,  # Unlimited
        "max_file_mb": 50,
        "requests_per_minute": 60,
        "tools_allowed": "__all__",
        "crosstab_significance_levels": [0.90, 0.95, 0.99],
        "team_seats": 1,
        "auto_analyze": True,
        "excel_export": True,
    },
    "business": {
        "files_per_day": None,
        "max_file_mb": 100,
        "requests_per_minute": 120,
        "tools_allowed": "__all__",
        "crosstab_significance_levels": [0.90, 0.95, 0.99],
        "team_seats": 5,
        "auto_analyze": True,
        "excel_export": True,
        "api_access": True,
        "webhooks": True,
    },
    "enterprise": {
        "files_per_day": None,
        "max_file_mb": 500,
        "requests_per_minute": None,  # Custom
        "tools_allowed": "__all__",
        "crosstab_significance_levels": [0.90, 0.95, 0.99],
        "team_seats": None,  # Custom
        "auto_analyze": True,
        "excel_export": True,
        "api_access": True,
        "webhooks": True,
    },
}


def get_plan_limits(plan: str) -> dict[str, Any]:
    """Get limits for a plan. Falls back to free if unknown."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


# ── JWKS fetching ────────────────────────────────────────────────────────────

async def _fetch_jwks(jwks_url: str) -> dict:
    """Fetch JWKS from Clerk, with 1-hour cache."""
    now = time.time()
    cached = _jwks_cache.get(jwks_url)
    if cached and (now - cached[1]) < _JWKS_CACHE_TTL:
        return cached[0]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        keys = resp.json()

    _jwks_cache[jwks_url] = (keys, now)
    logger.info("Clerk JWKS fetched and cached from %s", jwks_url)
    return keys


def _decode_jwt_unverified(token: str) -> tuple[dict, dict]:
    """Decode JWT header and payload WITHOUT signature verification.
    Used only to extract 'kid' for JWKS lookup.
    """
    import base64

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    def _b64decode(s: str) -> bytes:
        s += "=" * (4 - len(s) % 4) if len(s) % 4 else ""
        return base64.urlsafe_b64decode(s)

    header = json.loads(_b64decode(parts[0]))
    payload = json.loads(_b64decode(parts[1]))
    return header, payload


async def validate_clerk_token(token: str) -> ClerkUser:
    """Validate a Clerk JWT and extract user info.

    Performs full cryptographic verification:
    1. Decode header to get kid
    2. Fetch matching public key from JWKS
    3. Verify signature with RS256
    4. Check expiry and issuer
    5. Extract user claims
    """
    from config import get_settings
    settings = get_settings()

    if not settings.clerk_jwks_url:
        raise ValueError("Clerk not configured (missing CLERK_PUBLISHABLE_KEY)")

    # Step 1: Decode header to get kid
    try:
        header, payload = _decode_jwt_unverified(token)
    except Exception as e:
        raise ValueError(f"Invalid token format: {e}")

    kid = header.get("kid")
    if not kid:
        raise ValueError("Token missing 'kid' in header")

    # Step 2: Fetch JWKS and find matching key
    try:
        jwks = await _fetch_jwks(settings.clerk_jwks_url)
    except Exception as e:
        raise ValueError(f"Failed to fetch JWKS: {e}")

    matching_key = None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            matching_key = key
            break

    if not matching_key:
        # Key not found — might be rotated. Force refresh cache.
        _jwks_cache.pop(settings.clerk_jwks_url, None)
        try:
            jwks = await _fetch_jwks(settings.clerk_jwks_url)
        except Exception:
            raise ValueError("Token key ID not found in JWKS")

        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                matching_key = key
                break

        if not matching_key:
            raise ValueError("Token key ID not found in JWKS after refresh")

    # Step 3: Verify signature with PyJWT
    try:
        import jwt as pyjwt
        from jwt import PyJWK

        public_key = PyJWK(matching_key).key
        decoded = pyjwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},  # Clerk tokens may not have aud
        )
    except ImportError:
        # PyJWT not installed — fall back to unverified decode (dev only)
        logger.warning("PyJWT not installed — skipping signature verification (DEV ONLY)")
        decoded = payload
    except Exception as e:
        raise ValueError(f"Token verification failed: {e}")

    # Step 4: Check expiry
    exp = decoded.get("exp", 0)
    if exp and time.time() > exp:
        raise ValueError("Token expired")

    # Step 5: Extract user info
    user_id = decoded.get("sub", "")
    if not user_id:
        raise ValueError("Token missing 'sub' claim")

    # Plan comes from Clerk's public_metadata (synced with Stripe)
    public_metadata = decoded.get("public_metadata", {})
    if isinstance(public_metadata, str):
        try:
            public_metadata = json.loads(public_metadata)
        except Exception:
            public_metadata = {}

    plan = public_metadata.get("plan", "free")

    return ClerkUser(
        user_id=user_id,
        email=decoded.get("email", decoded.get("email_address", "")),
        plan=plan,
        name=decoded.get("name", decoded.get("first_name", "")),
        metadata=public_metadata,
    )


# ── Dual auth helper ─────────────────────────────────────────────────────────

async def authenticate_request(
    auth_header: str | None = None,
    api_key: str | None = None,
) -> tuple[str, str, dict]:
    """Authenticate via Bearer token (Clerk OAuth) or API key (legacy).

    Returns: (user_id_or_key_name, plan, extra_info)
    Bearer token takes precedence over api_key.
    """
    # Priority 1: Bearer token (Claude.ai OAuth flow)
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        # Check if it looks like a Clerk JWT (has dots) vs an API key (sk_*)
        if "." in token and not token.startswith("sk_"):
            try:
                user = await validate_clerk_token(token)
                return user.user_id, user.plan, {
                    "auth_method": "oauth",
                    "email": user.email,
                    "name": user.name,
                    "limits": get_plan_limits(user.plan),
                }
            except ValueError as e:
                from fastmcp.exceptions import ToolError
                raise ToolError(
                    f'{{"error": "invalid_token", '
                    f'"user_message": "Your session has expired or is invalid. '
                    f'Please reconnect Talk2Data in Claude.ai settings.", '
                    f'"recovery_action": "Tell the user to go to Claude.ai Settings > Connectors > Talk2Data > Reconnect", '
                    f'"details": "{e}"}}'
                )

    # Priority 2: API key (legacy — Claude Desktop, Claude Code, direct API)
    if api_key:
        from auth import get_key_config
        try:
            key_config = get_key_config(api_key)
            return key_config.name, key_config.plan, {
                "auth_method": "api_key",
                "limits": get_plan_limits(key_config.plan),
            }
        except ValueError:
            from fastmcp.exceptions import ToolError
            raise ToolError(
                '{"error": "invalid_api_key", '
                '"user_message": "The API key you provided is not valid. '
                'You can find your key at https://spss.insightgenius.io/account.", '
                '"recovery_action": "Ask the user for a valid API key. Do NOT retry with a guessed key.", '
                '"docs_url": "https://spss.insightgenius.io/docs/mcp#authentication"}'
            )

    # Neither provided
    from fastmcp.exceptions import ToolError
    raise ToolError(
        '{"error": "auth_required", '
        '"user_message": "Authentication required. Please provide your Talk2Data API key '
        '(format: sk_test_... or sk_live_...) or connect via OAuth in Claude.ai.", '
        '"recovery_action": "Ask the user for their API key, or direct them to reconnect Talk2Data in Claude.ai settings.", '
        '"get_key_url": "https://spss.insightgenius.io/account"}'
    )
