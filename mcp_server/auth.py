"""MCP authentication — API key, Clerk JWT, and OAuth free-tier support.

Provides _auth_async (async) and _auth (sync) for MCP tool validation,
plus _make_error for structured error responses and rate limiting.
"""

import base64
import json
import logging
import time

from fastmcp.exceptions import ToolError

from auth import KeyConfig, get_key_config
from config import get_settings

logger = logging.getLogger(__name__)

# ── Single source of truth for OAuth free-tier scopes ────────────────────────

OAUTH_FREE_SCOPES = [
    "process", "metadata", "convert", "crosstab", "frequency", "parse_ticket",
    "tabulate", "auto_analyze", "correlation", "anova", "gap_analysis", "satisfaction_summary",
]

OAUTH_PLACEHOLDER_KEYS = ("", "sk_test_default", "your_api_key", "YOUR_API_KEY")


# ── Error helper ─────────────────────────────────────────────────────────────

def _make_error(error_code: str, user_message: str, recovery_action: str, **extra) -> dict:
    """Standard error response for MCP tools. Claude can relay user_message directly."""
    return {
        "error": error_code,
        "user_message": user_message,
        "recovery_action": recovery_action,
        **extra,
    }


# ── JWT detection ────────────────────────────────────────────────────────────

def _is_jwt_token(value: str) -> bool:
    """Detect JWT tokens by attempting to decode header, not by counting dots."""
    if value.startswith("sk_"):
        return False
    parts = value.split(".")
    if len(parts) != 3:
        return False
    try:
        # JWT header should be valid base64-encoded JSON
        header = base64.urlsafe_b64decode(parts[0] + "==")
        json.loads(header)
        return True
    except Exception:
        return False


# ── Rate limiting for MCP ────────────────────────────────────────────────────

async def _check_mcp_rate_limit(key_config: KeyConfig) -> None:
    """Check rate limit for MCP tool calls. Uses same sliding window as REST."""
    from middleware.rate_limiter import _get_redis, _check_rate_redis, _check_rate_memory
    from fastapi import HTTPException

    settings = get_settings()
    limit = settings.rate_limit_for_plan(key_config.plan)
    now = time.time()
    r = _get_redis()
    try:
        if r:
            _check_rate_redis(r, key_config.key_hash, limit, now)
        else:
            _check_rate_memory(key_config.key_hash, limit, now)
    except HTTPException:
        raise ToolError(json.dumps(_make_error(
            "rate_limit_exceeded",
            f"Rate limit exceeded ({limit} requests/minute for {key_config.plan} plan). Please wait.",
            "Wait a moment and try again, or upgrade your plan.",
        )))


# ── Auth functions ───────────────────────────────────────────────────────────

async def _auth_async(api_key: str = "") -> KeyConfig:
    """Validate API key OR Clerk JWT token. Supports dual auth.

    - If api_key is empty: reject with auth_required error.
    - If api_key looks like a JWT: validate as Clerk OAuth token.
    - If api_key starts with sk_: validate as API key.
    """
    # Reject empty / placeholder keys — authentication is required
    if not api_key or api_key in OAUTH_PLACEHOLDER_KEYS:
        raise ToolError(json.dumps(_make_error(
            "auth_required",
            "Authentication is required. Provide a valid API key (sk_test_... or sk_live_...) "
            "or connect via OAuth on Claude.ai.",
            "Ask the user for their API key. They can get one at https://spss.insightgenius.io/account",
            docs_url="https://spss.insightgenius.io/docs/mcp#authentication",
        )))

    # Check if this is a Clerk JWT token
    if _is_jwt_token(api_key):
        try:
            from middleware.clerk_auth import validate_clerk_token
            user = await validate_clerk_token(api_key)
            return KeyConfig(
                key_hash="oauth",
                name=user.email or user.user_id,
                plan=user.plan,
                scopes=["process", "metadata", "convert", "crosstab", "frequency", "parse_ticket"],
            )
        except ValueError as e:
            raise ToolError(json.dumps(_make_error(
                "invalid_token",
                "Your OAuth session has expired or is invalid. "
                "Please reconnect Talk2Data in Claude.ai settings.",
                "Tell the user to go to Claude.ai Settings > Connectors > Talk2Data > Reconnect",
                details=str(e),
            )))

    # Standard API key validation
    try:
        key_config = get_key_config(api_key)
    except ValueError:
        raise ToolError(json.dumps(_make_error(
            "invalid_api_key",
            "The API key you provided is not valid. "
            "Please check your key at https://spss.insightgenius.io/account. "
            "It should look like sk_test_... or sk_live_...",
            "Ask the user to verify their API key. Do NOT retry with a different guessed key.",
            docs_url="https://spss.insightgenius.io/docs/mcp#authentication",
        )))

    # Rate limit for non-free plans
    if key_config.plan != "free":
        await _check_mcp_rate_limit(key_config)

    return key_config


def _auth(api_key: str = "") -> KeyConfig:
    """Sync wrapper for backwards compatibility. For new code, use _auth_async."""
    import asyncio

    # Reject empty / placeholder keys — authentication is required
    if not api_key or api_key in OAUTH_PLACEHOLDER_KEYS:
        raise ToolError(json.dumps(_make_error(
            "auth_required",
            "Authentication is required. Provide a valid API key (sk_test_... or sk_live_...) "
            "or connect via OAuth on Claude.ai.",
            "Ask the user for their API key. They can get one at https://spss.insightgenius.io/account",
            docs_url="https://spss.insightgenius.io/docs/mcp#authentication",
        )))

    # For JWT tokens, we need async. For API keys, sync is fine.
    if _is_jwt_token(api_key):
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise ToolError(
                "OAuth tokens require async auth. This tool should use _auth_async instead of _auth."
            )
        return loop.run_until_complete(_auth_async(api_key))

    # Standard API key
    try:
        return get_key_config(api_key)
    except ValueError:
        raise ToolError(json.dumps(_make_error(
            "invalid_api_key",
            "The API key you provided is not valid. "
            "Please check your key at https://spss.insightgenius.io/account. "
            "It should look like sk_test_... or sk_live_...",
            "Ask the user to verify their API key. Do NOT retry with a different guessed key.",
            docs_url="https://spss.insightgenius.io/docs/mcp#authentication",
        )))
