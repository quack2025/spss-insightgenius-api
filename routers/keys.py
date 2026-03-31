"""Self-service API key management — create, list, revoke keys."""

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_auth, KeyConfig
from config import get_settings
from shared.response import success_response, error_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Keys"])


class CreateKeyRequest(BaseModel):
    name: str = "Default"


class RevokeKeyRequest(BaseModel):
    key_id: str


def _get_supabase():
    """Get Supabase client with service role key."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(503, detail=error_response(
            "SERVICE_UNAVAILABLE", "Key management requires Supabase configuration."
        ))
    import httpx
    return settings.supabase_url, {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


@router.post("/v1/keys", summary="Create a new API key")
async def create_key(
    body: CreateKeyRequest,
    auth_key: KeyConfig = Depends(require_auth),
):
    """Create a new API key for the authenticated user.

    Returns the raw key ONCE — it cannot be retrieved later.
    The key is stored as a SHA256 hash in Supabase.
    """
    # Generate key
    raw_key = f"sk_live_{secrets.token_hex(24)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    url, headers = _get_supabase()

    # Get user_id from auth (for now, use key name as user_id)
    user_id = auth_key.name

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/api_keys",
            headers={**headers, "Prefer": "return=representation"},
            json={
                "user_id": user_id,
                "name": body.name,
                "key_prefix": key_prefix,
                "key_hash": key_hash,
                "plan": auth_key.plan,
                "scopes": auth_key.scopes,
                "is_active": True,
            },
        )

        if resp.status_code not in (200, 201):
            logger.error("Supabase key creation failed: %s", resp.text)
            raise HTTPException(500, detail=error_response(
                "KEY_CREATION_FAILED", "Failed to create API key."
            ))

        db_key = resp.json()[0] if isinstance(resp.json(), list) else resp.json()

    return success_response({
        "key": raw_key,  # Shown ONCE
        "key_id": db_key["id"],
        "prefix": key_prefix,
        "name": body.name,
        "plan": auth_key.plan,
        "created_at": db_key.get("created_at"),
        "warning": "Save this key now — it cannot be retrieved later.",
    })


@router.get("/v1/keys", summary="List your API keys")
async def list_keys(
    auth_key: KeyConfig = Depends(require_auth),
):
    """List all API keys for the authenticated user. Raw keys are NOT returned."""
    url, headers = _get_supabase()
    user_id = auth_key.name

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/api_keys?user_id=eq.{user_id}&is_active=eq.true&select=id,name,key_prefix,plan,scopes,created_at,last_used_at",
            headers=headers,
        )

        if resp.status_code != 200:
            raise HTTPException(500, detail=error_response(
                "KEY_LIST_FAILED", "Failed to list API keys."
            ))

        keys = resp.json()

    return success_response({
        "keys": keys,
        "total": len(keys),
    })


@router.delete("/v1/keys/{key_id}", summary="Revoke an API key")
async def revoke_key(
    key_id: str,
    auth_key: KeyConfig = Depends(require_auth),
):
    """Revoke (deactivate) an API key. The key will no longer work."""
    url, headers = _get_supabase()
    user_id = auth_key.name

    import httpx
    async with httpx.AsyncClient() as client:
        # Verify ownership
        resp = await client.get(
            f"{url}/rest/v1/api_keys?id=eq.{key_id}&user_id=eq.{user_id}&select=id",
            headers=headers,
        )
        if resp.status_code != 200 or not resp.json():
            raise HTTPException(404, detail=error_response(
                "KEY_NOT_FOUND", "API key not found or not owned by you."
            ))

        # Revoke
        resp = await client.patch(
            f"{url}/rest/v1/api_keys?id=eq.{key_id}",
            headers=headers,
            json={
                "is_active": False,
                "revoked_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        if resp.status_code not in (200, 204):
            raise HTTPException(500, detail=error_response(
                "KEY_REVOKE_FAILED", "Failed to revoke API key."
            ))

    return success_response({"key_id": key_id, "status": "revoked"})
