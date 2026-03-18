"""API key authentication — no database required.

Keys are stored as SHA256 hashes in the API_KEYS_JSON env var.
The raw key (sk_live_xxx / sk_test_xxx) is only known to the client.
"""

import hashlib
import hmac
import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class KeyConfig:
    key_hash: str
    name: str
    plan: str  # "free", "pro", "business"
    scopes: list[str]


# Registry populated at startup
_KEY_REGISTRY: dict[str, KeyConfig] = {}


def init_key_registry() -> None:
    """Parse API_KEYS_JSON into the in-memory registry. Called during app lifespan."""
    _KEY_REGISTRY.clear()
    settings = get_settings()
    for entry in settings.parsed_api_keys:
        key_hash = entry.get("key_hash", "")
        if not key_hash:
            continue
        _KEY_REGISTRY[key_hash] = KeyConfig(
            key_hash=key_hash,
            name=entry.get("name", "unknown"),
            plan=entry.get("plan", "free"),
            scopes=entry.get("scopes", []),
        )
    logger.info("Loaded %d API key(s) into registry", len(_KEY_REGISTRY))


def _hash_key(raw: str) -> str:
    """SHA256 hash of a raw API key."""
    return hashlib.sha256(raw.encode()).hexdigest()


async def require_auth(request: Request) -> KeyConfig:
    """FastAPI dependency: validate Bearer token and return KeyConfig."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Missing Authorization: Bearer <api_key> header"},
        )

    raw_key = auth_header[7:]
    if not raw_key.startswith(("sk_live_", "sk_test_")):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid API key format. Keys must start with sk_live_ or sk_test_"},
        )

    key_hash = _hash_key(raw_key)

    # Timing-safe comparison against all known hashes
    matched_config: KeyConfig | None = None
    for stored_hash, config in _KEY_REGISTRY.items():
        if hmac.compare_digest(key_hash, stored_hash):
            matched_config = config
            break

    if matched_config is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid API key"},
        )

    # Attach to request state for rate limiting and logging
    request.state.key_config = matched_config
    return matched_config


def require_scope(scope: str):
    """Factory: returns a dependency that checks the key has a specific scope."""

    async def _check(key: KeyConfig = Depends(require_auth)) -> KeyConfig:
        if scope not in key.scopes:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FORBIDDEN",
                    "message": f"API key does not have the '{scope}' scope",
                },
            )
        return key

    return _check
