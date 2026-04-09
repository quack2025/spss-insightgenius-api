# SPSS InsightGenius API — CLAUDE.md

## What this project is

REST API + MCP server for deterministic market research data analysis. Processes SPSS files and generates professional Excel tabulations with significance testing. The product IS the API — frontends are convenience wrappers.

**URL:** https://spss.insightgenius.io
**GitHub:** quack2025/spss-insightgenius-api
**Deploy:** Railway (auto-deploy from `master`, 4 replicas)
**Engine:** QuantipyMRX (Python 3.11 + pandas + scipy)

## Stack

- **Backend:** FastAPI + Gunicorn + UvicornWorker
- **Engine:** QuantipyMRX fork (quantipy for Python 3.11+) — ALL stats through this engine
- **AI:** Anthropic Claude (Sonnet for NL chat/reports, Haiku for labeling/help)
- **Database:** PostgreSQL via SQLAlchemy async (optional — stateless mode if no DATABASE_URL)
- **Cache/Sessions:** Redis (file sessions 30min TTL, rate limiting, idempotency, query cache)
- **Auth:** Dual — SHA-256 API keys (existing) + Supabase JWT (platform users)
- **Storage:** Supabase (API keys, usage, library, project files)
- **MCP:** FastMCP SSE transport at `/mcp/sse`
- **Migrations:** Alembic (async, asyncpg)

## Key Architecture Decisions

### Middleware: Pure ASGI only
**NEVER use Starlette `BaseHTTPMiddleware`** — it causes `AssertionError` on streaming/empty responses and blocks Railway deploys. All middleware uses raw ASGI `send_wrapper` pattern. See `middleware/response_headers.py` and `middleware/idempotency.py`.

### Auth pattern — Dual Authentication
```python
# Existing API endpoints (unchanged):
key: KeyConfig = Depends(require_auth)       # API key only
key: KeyConfig = Depends(require_scope("process"))  # key with specific scope

# New platform endpoints (Phase 1+):
auth: AuthContext = Depends(get_auth_context)  # API key OR Supabase JWT
auth: AuthContext = Depends(require_user)      # Supabase JWT only (needs db_user)
```
`AuthContext.user_id` = UUID (from JWT) or key name. `AuthContext.db_user` only for JWT auth.

### File flow
1. Upload via `/v1/files/upload` or MCP `spss_upload_file` → stored in Redis with 30min sliding TTL
2. Returns `file_id` (UUID)
3. All analysis endpoints accept `file_id` parameter
4. File re-parsed from Redis bytes on each request (no parsed cache yet)

### Response envelope
```json
{"success": true, "data": {...}, "meta": {"request_id": "abc", "processing_time_ms": 123}}
{"success": false, "error": {"code": "VARIABLE_NOT_FOUND", "message": "..."}}
```

## Endpoints (~90 REST + 13 MCP)

### Stateless API (API key auth — original 29 endpoints)
| Category | Endpoints |
|----------|-----------|
| System | GET /v1/health, GET /v1/usage |
| Files | POST /v1/files/upload, GET /downloads/{token} |
| Library | POST/GET/PATCH/DELETE /v1/library/* |
| Metadata | POST /v1/metadata |
| Analysis | /v1/frequency, /v1/crosstab, /v1/anova, /v1/correlation, /v1/gap-analysis, /v1/satisfaction-summary |
| Tabulation | POST /v1/tabulate, POST /v1/auto-analyze |
| AI | POST /v1/smart-spec, /v1/parse-ticket, /v1/chat, /v1/chat-stream |
| Weighting | POST /v1/weight/preview, /v1/weight/compute |
| Wave | POST /v1/wave-compare |
| Jobs | GET /v1/jobs/{job_id} |
| Keys | POST/GET/DELETE /v1/keys |
| MCP | 13 tools at /mcp/sse |

### Platform API (Supabase JWT auth — 60+ new endpoints)
| Category | Endpoints |
|----------|-----------|
| Projects | CRUD /v1/projects/*, /files/upload, /files |
| Conversations | CRUD + POST /query, GET /suggestions |
| Data Prep | CRUD /data-prep/rules, /preview, /reorder |
| Variable Groups | CRUD + POST /auto-detect |
| Waves | CRUD + POST /compare |
| Explore | GET /variables, POST /run, CRUD /bookmarks |
| Segments | CRUD + POST /preview |
| Metadata | GET/PUT /overrides |
| Generate Tables | POST /tables/preview, /generate, /export + templates |
| Exports | POST/GET /exports, GET /banners, /stubs |
| Reports | POST/GET /reports |
| Teams | CRUD /teams/*, POST/DELETE /members |
| Dashboards | CRUD + /publish, /widgets |
| Share | CRUD /share, GET /public/dashboards/{token} |
| Users | GET/PATCH /users/me, /preferences |
| Help | POST /help-chat |
| Merge | POST /merge/validate, POST /merge |
| Clustering | POST /clustering/auto-k, /run |

## Testing

```bash
python -m pytest tests/ -x -q --tb=short  # 234 tests, ~78s
```

- `tests/test_auth_unified.py` — JWT verification + dual auth dispatch (13 tests)
- `tests/test_projects.py` — project CRUD + metadata extraction (15 tests)
- `tests/test_conversations.py` — NL chat executor + fuzzy matching + charts (26 tests)
- `tests/test_phase4.py` — data prep rules + segment filters (28 tests)
- `tests/test_phase5.py` — report generator + table wizard (16 tests)
- `tests/test_phase6_7.py` — teams/dashboards/clustering (22 tests)
- `tests/test_tabulation_real.py` — golden standard tests vs R export
- `tests/test_mcp.py` — MCP tool tests

## Deployment

- Push to `master` → Railway auto-deploys
- Dockerfile: multi-stage, non-root user, gunicorn 4 workers
- Healthcheck: `GET /v1/health`
- `python-pptx` is required (quantipymrx imports it internally)
- Security headers injected via ASGI middleware (not BaseHTTPMiddleware)

### Enabling Platform Features
The backend runs in **stateless API-only mode** by default. To enable platform features:
1. Add PostgreSQL plugin on Railway → provides `DATABASE_URL`
2. Set `SUPABASE_JWT_SECRET` (from Supabase project settings → API → JWT Secret)
3. Run `alembic upgrade head` (via Railway deploy command or manually)
4. Platform endpoints activate automatically when DATABASE_URL is set

### Database
- **20 tables** — migration: `alembic/versions/001_initial_platform_tables.py`
- `alembic upgrade head` creates all tables
- `alembic downgrade base` drops all tables

## npm SDK

`@insightgenius/sdk` at `C:\Users\jorge\proyectos_python\insightgenius-sdk`

```typescript
const ig = new InsightGenius("sk_test_...");
const { file_id } = await ig.upload(file, "survey.sav");
const meta = await ig.getMetadata(file_id);
const ct = await ig.crosstab(file_id, { row: "Q1", col: "Gender" });
const excel = await ig.tabulate(file_id, { banners: ["Gender"], stubs: ["_all_"] });
```

## Enterprise Standards

See `~/.claude/projects/C--Users-jorge/memory/enterprise_api_standards.md` for the full checklist that this project and all Genius Labs API products must follow.
