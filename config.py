"""Application configuration via environment variables."""

import json
import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # App
    app_name: str = "SPSS InsightGenius API"
    app_env: str = "development"
    app_version: str = "1.0.0"
    port: int = 8000

    # Auth — JSON array of key configs
    # Format: [{"key_hash":"sha256hex","name":"Acme","plan":"pro","scopes":["process","metadata",...]}]
    api_keys_json: str = "[]"

    # Claude AI (Haiku for ticket parsing + smart labeling)
    anthropic_api_key: str = ""

    # Rate limits per plan (requests/minute)
    rate_limit_free: int = 10
    rate_limit_pro: int = 60
    rate_limit_business: int = 200

    # File limits
    max_file_size_mb: int = 100

    # Processing
    processing_timeout_seconds: int = 120
    max_concurrent_processing: int = 3  # max SPSS files processing per worker

    # Redis (for distributed rate limiting + MCP file sessions — optional)
    redis_url: str = ""

    # MCP file sessions
    spss_session_ttl_seconds: int = 1800  # 30 minutes sliding window
    redis_max_file_size_mb: int = 100

    # Base URL for download links
    base_url: str = "https://spss.insightgenius.io"

    # CORS
    cors_origins: str = '["*"]'

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def parsed_api_keys(self) -> list[dict]:
        try:
            return json.loads(self.api_keys_json)
        except json.JSONDecodeError:
            logger.error("Failed to parse API_KEYS_JSON")
            return []

    @property
    def parsed_cors_origins(self) -> list[str]:
        try:
            origins = json.loads(self.cors_origins)
            return origins if isinstance(origins, list) else ["*"]
        except json.JSONDecodeError:
            return ["*"]

    def rate_limit_for_plan(self, plan: str) -> int:
        limits = {
            "free": self.rate_limit_free,
            "pro": self.rate_limit_pro,
            "business": self.rate_limit_business,
        }
        return limits.get(plan, self.rate_limit_free)


@lru_cache
def get_settings() -> Settings:
    return Settings()
