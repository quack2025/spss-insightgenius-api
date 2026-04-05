"""Library service: persistent file storage + metadata indexing in Supabase.

Replaces ephemeral Redis sessions with permanent Supabase Storage + DB.
Files are stored in Supabase Storage, metadata in PostgreSQL tables.
Redis is still used as hot cache for active analysis sessions.
"""

import hashlib
import io
import json
import logging
import uuid
from typing import Any

import httpx

from config import get_settings

logger = logging.getLogger(__name__)


class LibraryService:
    """Manages persistent SPSS file library in Supabase."""

    def __init__(self):
        settings = get_settings()
        self.supabase_url = settings.supabase_url
        self.service_key = settings.supabase_service_role_key
        if not self.supabase_url or not self.service_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required for library")
        self.rest_url = f"{self.supabase_url}/rest/v1"
        self.storage_url = f"{self.supabase_url}/storage/v1"
        self.headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
        }
        self.bucket = "spss-files"

    # ── Storage ──────────────────────────────────────────────────

    async def _ensure_bucket(self):
        """Create storage bucket if it doesn't exist."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.storage_url}/bucket/{self.bucket}",
                headers=self.headers,
            )
            if resp.status_code == 404:
                await client.post(
                    f"{self.storage_url}/bucket",
                    headers={**self.headers, "Content-Type": "application/json"},
                    json={"id": self.bucket, "name": self.bucket, "public": False},
                )
                logger.info("Created storage bucket: %s", self.bucket)

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str = "demo",
        metadata: dict | None = None,
    ) -> dict:
        """Upload file to Supabase Storage + index metadata in DB.

        Returns: {library_id, file_id (Redis), filename, n_cases, n_variables, ...}
        """
        await self._ensure_bucket()

        library_id = str(uuid.uuid4())
        storage_path = f"{user_id}/{library_id}/{filename}"

        # 1. Upload to Supabase Storage
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.storage_url}/object/{self.bucket}/{storage_path}",
                headers={
                    **self.headers,
                    "Content-Type": "application/octet-stream",
                    "x-upsert": "true",
                },
                content=file_bytes,
            )
            if resp.status_code not in (200, 201):
                logger.error("Storage upload failed: %s %s", resp.status_code, resp.text[:200])
                raise ValueError(f"Storage upload failed: {resp.status_code}")

        # 2. Extract metadata if not provided
        if not metadata:
            metadata = self._extract_metadata(file_bytes, filename)

        # 3. Insert file record
        file_record = {
            "id": library_id,
            "user_id": user_id,
            "filename": filename,
            "original_name": filename,
            "display_name": metadata.get("file_label") or filename.rsplit(".", 1)[0],
            "file_type": filename.rsplit(".", 1)[-1].lower() if "." in filename else "sav",
            "storage_path": storage_path,
            "size_bytes": len(file_bytes),
            "n_cases": metadata.get("n_cases", 0),
            "n_variables": metadata.get("n_variables", 0),
            "file_label": metadata.get("file_label"),
            "detected_groups": json.dumps(metadata.get("detected_groups", [])),
            "suggested_banners": json.dumps(metadata.get("suggested_banners", [])),
            "preset_nets": json.dumps(metadata.get("preset_nets", {})),
            "detected_weights": metadata.get("detected_weights", []),
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.rest_url}/library_files",
                headers={**self.headers, "Content-Type": "application/json", "Prefer": "return=representation"},
                json=file_record,
            )
            if resp.status_code not in (200, 201):
                logger.error("DB insert failed: %s %s", resp.status_code, resp.text[:200])
                raise ValueError(f"DB insert failed: {resp.status_code}")

        # 4. Index variables
        variables = metadata.get("variables", [])
        if variables:
            await self._index_variables(library_id, variables)

        # 5. Generate AI summary for better search (async, non-blocking)
        try:
            import asyncio
            asyncio.create_task(self._generate_file_summary(library_id, metadata))
        except Exception:
            pass  # Non-critical — text search still works

        logger.info("[LIBRARY] Stored %s: %d cases × %d vars, library_id=%s",
                     filename, metadata.get("n_cases", 0), metadata.get("n_variables", 0), library_id)

        return {
            "library_id": library_id,
            "filename": filename,
            "n_cases": metadata.get("n_cases", 0),
            "n_variables": metadata.get("n_variables", 0),
            "storage_path": storage_path,
        }

    def _extract_metadata(self, file_bytes: bytes, filename: str) -> dict:
        """Extract metadata from file using the engine."""
        from services.quantipy_engine import QuantiProEngine
        engine = QuantiProEngine()
        data = engine.load_spss(file_bytes, filename)
        return engine.extract_metadata(data)

    async def _index_variables(self, library_id: str, variables: list[dict]):
        """Bulk insert variable metadata into library_variables."""
        rows = []
        for v in variables:
            vl = v.get("value_labels") or {}
            rows.append({
                "file_id": library_id,
                "name": v["name"],
                "label": v.get("label"),
                "var_type": v.get("type"),
                "detected_type": v.get("detected_type"),
                "n_categories": len(vl),
                "value_labels": json.dumps(vl) if vl else None,
                "n_valid": v.get("n_valid", 0),
                "n_missing": v.get("n_missing", 0),
            })

        # Batch insert (Supabase accepts arrays)
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Insert in chunks of 100
            for i in range(0, len(rows), 100):
                chunk = rows[i:i+100]
                resp = await client.post(
                    f"{self.rest_url}/library_variables",
                    headers={**self.headers, "Content-Type": "application/json"},
                    json=chunk,
                )
                if resp.status_code not in (200, 201):
                    logger.warning("Variable index failed for chunk %d: %s", i, resp.text[:200])

    async def _generate_file_summary(self, library_id: str, metadata: dict):
        """Generate an AI summary of the file for better search. Uses Haiku (~$0.001)."""
        settings = get_settings()
        if not settings.anthropic_api_key:
            return

        # Build a compact description of the file
        vars_desc = []
        for v in metadata.get("variables", [])[:50]:
            label = v.get("label", "")
            vl = v.get("value_labels") or {}
            n_cats = len(vl) if isinstance(vl, dict) else 0
            sample = list(vl.values())[:3] if isinstance(vl, dict) and vl else []
            sample_str = " [" + ", ".join(str(s) for s in sample) + "]" if sample else ""
            vars_desc.append(f"{v['name']}: {label} ({n_cats} cats){sample_str}")

        groups = metadata.get("detected_groups", [])
        groups_desc = [f"{g.get('question_type','?')}: {g.get('display_name','')[:50]} ({len(g.get('variables',[]))} vars)" for g in groups[:10]]

        vars_text = "\n".join(vars_desc)
        groups_text = "\n".join(groups_desc) if groups_desc else "none"

        prompt = (
            "Describe this survey dataset in 2-3 sentences. Include: topic/industry, "
            "country if detectable, key question themes, and notable demographics. "
            "Write in English even if labels are in another language.\n\n"
            f"File: {metadata.get('file_name', 'unknown')}\n"
            f"Cases: {metadata.get('n_cases', 0)} | Variables: {metadata.get('n_variables', 0)}\n"
            f"File label: {metadata.get('file_label', 'none')}\n\n"
            f"Variables (first 50):\n{vars_text}\n\n"
            f"Detected groups: {groups_text}\n\n"
            "Also generate 10 relevant search keywords (English + original language if not English), comma-separated."
        )

        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = resp.content[0].text

            # Store summary in description + tags
            # Parse keywords from last line
            lines = summary.strip().split("\n")
            keywords_line = lines[-1] if lines else ""
            description = "\n".join(lines[:-1]).strip()
            tags = [t.strip().lower() for t in keywords_line.split(",") if t.strip()][:15]

            async with httpx.AsyncClient() as client:
                await client.patch(
                    f"{self.rest_url}/library_files?id=eq.{library_id}",
                    headers={**self.headers, "Content-Type": "application/json"},
                    json={"description": description, "tags": tags},
                )
            logger.info("[LIBRARY] AI summary generated for %s: %d tags", library_id, len(tags))
        except Exception as e:
            logger.warning("[LIBRARY] AI summary failed for %s: %s", library_id, e)

    # ── Retrieval ────────────────────────────────────────────────

    async def list_files(self, user_id: str = "demo") -> list[dict]:
        """List all files for a user."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.rest_url}/library_files?user_id=eq.{user_id}&order=created_at.desc",
                headers={**self.headers},
            )
            return resp.json() if resp.status_code == 200 else []

    async def get_file_metadata(self, library_id: str) -> dict | None:
        """Get file metadata by library_id."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.rest_url}/library_files?id=eq.{library_id}",
                headers={**self.headers},
            )
            files = resp.json() if resp.status_code == 200 else []
            return files[0] if files else None

    async def get_file_variables(self, library_id: str) -> list[dict]:
        """Get all variables for a file."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.rest_url}/library_variables?file_id=eq.{library_id}&order=name",
                headers={**self.headers},
            )
            return resp.json() if resp.status_code == 200 else []

    async def download_file(self, library_id: str) -> tuple[bytes, str] | None:
        """Download file bytes from Supabase Storage.

        Returns (file_bytes, filename) or None if not found.
        """
        file_meta = await self.get_file_metadata(library_id)
        if not file_meta:
            return None

        storage_path = file_meta["storage_path"]
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{self.storage_url}/object/{self.bucket}/{storage_path}",
                headers=self.headers,
            )
            if resp.status_code == 200:
                return resp.content, file_meta["filename"]
        return None

    async def load_to_redis(self, library_id: str) -> str | None:
        """Load a library file into Redis for active analysis. Returns file_id."""
        result = await self.download_file(library_id)
        if not result:
            return None

        file_bytes, filename = result
        settings = get_settings()
        if not settings.redis_url:
            return None

        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=False)
        try:
            # Reuse library_id as file_id for simplicity
            file_id = library_id
            ttl = settings.spss_session_ttl_seconds

            # Load to get metadata
            from services.quantipy_engine import QuantiProEngine
            data = QuantiProEngine.load_spss(file_bytes, filename)

            meta_info = json.dumps({
                "filename": filename,
                "format": filename.rsplit(".", 1)[-1].lower(),
                "n_cases": len(data.df),
                "n_variables": len(data.df.columns),
                "size_bytes": len(file_bytes),
                "library_id": library_id,
            })

            await r.set(f"spss:file:{file_id}", file_bytes, ex=ttl)
            await r.set(f"spss:meta:{file_id}", meta_info.encode(), ex=ttl)
            await r.aclose()

            # Update last_accessed_at
            async with httpx.AsyncClient() as client:
                await client.patch(
                    f"{self.rest_url}/library_files?id=eq.{library_id}",
                    headers={**self.headers, "Content-Type": "application/json"},
                    json={"last_accessed_at": "now()"},
                )

            return file_id
        except Exception as e:
            try:
                await r.aclose()
            except Exception:
                pass
            logger.error("Failed to load library file to Redis: %s", e)
            return None

    # ── Delete ───────────────────────────────────────────────────

    async def delete_file(self, library_id: str) -> bool:
        """Delete file from Storage + DB (cascade deletes variables + analyses)."""
        file_meta = await self.get_file_metadata(library_id)
        if not file_meta:
            return False

        # Delete from storage
        storage_path = file_meta["storage_path"]
        async with httpx.AsyncClient() as client:
            await client.delete(
                f"{self.storage_url}/object/{self.bucket}/{storage_path}",
                headers=self.headers,
            )

        # Delete from DB (cascade handles variables + analyses)
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self.rest_url}/library_files?id=eq.{library_id}",
                headers=self.headers,
            )
            return resp.status_code in (200, 204)

    # ── Search ───────────────────────────────────────────────────

    @staticmethod
    def _sanitize_postgrest_query(value: str) -> str:
        """Escape characters that have special meaning in PostgREST filter values."""
        import urllib.parse
        # Remove PostgREST operators and dangerous characters, then URL-encode
        sanitized = value.replace("(", "").replace(")", "").replace("&", "").replace(",", "").replace("%", "")
        return urllib.parse.quote(sanitized, safe="")

    async def search_files(self, user_id: str, query: str) -> list[dict]:
        """Text search across files, descriptions, tags, and variables."""
        query_lower = query.lower().strip()[:100]  # Cap length
        safe_q = self._sanitize_postgrest_query(query_lower)

        # Search in file names + descriptions + display_name + tags
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.rest_url}/library_files?user_id=eq.{user_id}"
                f"&or=(filename.ilike.%25{safe_q}%25,description.ilike.%25{safe_q}%25,"
                f"display_name.ilike.%25{safe_q}%25,tags.cs.{{{safe_q}}})",
                headers=self.headers,
            )
            file_results = resp.json() if resp.status_code == 200 else []

        # Search in variable labels
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.rest_url}/library_variables?"
                f"or=(name.ilike.%25{safe_q}%25,label.ilike.%25{safe_q}%25)"
                f"&select=file_id,name,label",
                headers=self.headers,
            )
            var_results = resp.json() if resp.status_code == 200 else []

        # Merge: add variable matches to file results
        var_file_ids = {v["file_id"] for v in var_results}
        existing_ids = {f["id"] for f in file_results}

        # Fetch files that matched via variables but not directly
        missing_ids = var_file_ids - existing_ids
        if missing_ids:
            ids_str = ",".join(f'"{fid}"' for fid in missing_ids)
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.rest_url}/library_files?id=in.({','.join(missing_ids)})",
                    headers=self.headers,
                )
                extra = resp.json() if resp.status_code == 200 else []
                file_results.extend(extra)

        # Add matched_variables info
        var_by_file = {}
        for v in var_results:
            var_by_file.setdefault(v["file_id"], []).append({"name": v["name"], "label": v["label"]})

        for f in file_results:
            f["matched_variables"] = var_by_file.get(f["id"], [])

        return file_results
