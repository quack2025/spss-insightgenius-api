# CLAUDE.md — SPSS InsightGenius API

> Internal development notes for AI-assisted sessions.

---

## Project: SPSS InsightGenius API

**Product**: REST API + embedded UI for processing SPSS (.sav) files into market research deliverables.
**Backend**: FastAPI (Python 3.11) on Railway
**Engine**: QuantipyMRX (custom fork: `quack2025/QuantiyFork2026`)
**AI**: Claude Haiku (`claude-haiku-4-5-20251001`) — ticket parsing + smart labeling only
**Frontend**: Embedded single-page HTML at `/` (no separate repo)

### Infrastructure

| Resource | Value |
|----------|-------|
| GitHub repo | `quack2025/spss-insightgenius-api` |
| Local path | `C:\Users\jorge\proyectos_python\quantipro-api` |
| Production URL | `https://spss.insightgenius.io` |
| Railway project | `spss-insightgenius-api` (auto-deploy from `master`) |
| Railway URL | `spss-insightgenius-api-production.up.railway.app` |
| API Docs | `https://spss.insightgenius.io/docs` |
| Branch | `master` |

### API Keys (Test)

| Key | Plan | Rate Limit |
|-----|------|-----------|
| `sk_test_2a441a40c84ba0afe73efd47d6bb1066aac82ad5453360f3` | Pro | 60/min |
| `sk_live_02099ac95ed0761759c81a13a84cd68adce99920ae7254db` | Business | 200/min |

Keys are SHA256-hashed in `API_KEYS_JSON` env var. Raw keys never stored server-side.

---

## Architecture

### Design Principles

1. **Stateless** — No database. Files uploaded, processed, returned. Nothing persisted.
2. **API-first** — The product IS the API. Frontend is a convenience wrapper.
3. **Contract-stable** — Response shapes never change without version bump.
4. **Haiku-only** — AI features use only Haiku (~$0.001/request). No Sonnet/Opus.
5. **Single service** — No Celery, no Redis, no workers. Files < 100MB process synchronously.

### Request Flow

```
Client → Bearer auth → Rate limit check → Router → asyncio.to_thread(engine) → Response
                                                          ↓
                                              QuantiProEngine (stateless)
                                                   ↓           ↓
                                             pyreadstat    QuantipyMRX
                                             (always)     (if available)
```

### File Structure

```
quantipro-api/
├── main.py                         # FastAPI app, middleware, router registration
├── config.py                       # Pydantic Settings (env vars)
├── auth.py                         # API key auth (SHA256, timing-safe, scopes)
├── public/
│   └── index.html                  # Embedded frontend (Tailwind CDN + vanilla JS)
├── routers/
│   ├── health.py                   # GET /v1/health, GET /v1/usage
│   ├── metadata.py                 # POST /v1/metadata
│   ├── frequency.py                # POST /v1/frequency
│   ├── crosstab.py                 # POST /v1/crosstab
│   ├── tabulate.py                 # POST /v1/tabulate (★ core endpoint)
│   ├── convert.py                  # POST /v1/convert
│   ├── parse_ticket.py             # POST /v1/parse-ticket
│   └── process.py                  # POST /v1/process
├── services/
│   ├── quantipy_engine.py          # Core: load_spss, frequency, crosstab_with_significance, nps, t2b, nets
│   ├── tabulation_builder.py       # Excel builder: multi-sheet crosstab workbook with sig letters
│   ├── auto_planner.py             # Deterministic tab plan from metadata (no LLM)
│   ├── ticket_parser.py            # Haiku: .docx → structured tab plan
│   ├── smart_labeler.py            # Haiku: improve cryptic SPSS labels
│   └── converter.py                # Format conversion: xlsx, csv, dta, parquet
├── schemas/
│   ├── requests.py                 # FrequencyRequest, CrosstabSpec, ConvertRequest
│   ├── responses.py                # All response models (contract)
│   └── errors.py                   # ErrorCode enum + ErrorResponse
├── middleware/
│   ├── rate_limiter.py             # Sliding window per-key (in-memory)
│   ├── request_id.py               # X-Request-Id generation
│   └── usage_logger.py             # [USAGE] logs for billing
├── tests/                          # 29 tests (pytest)
├── Dockerfile                      # Multi-stage: builder (git+wheels) → runtime (slim)
├── railway.toml                    # Railway deploy config
└── requirements.txt                # All dependencies
```

---

## Endpoints

| Method | Path | Auth Scope | Description |
|--------|------|-----------|-------------|
| GET | `/v1/health` | None | Health check + engine status |
| GET | `/v1/usage` | Any | Per-key usage counters (since last deploy) |
| POST | `/v1/metadata` | `metadata` | Variable names, labels, types, auto-detect |
| POST | `/v1/frequency` | `frequency` | Frequency table (counts + %) |
| POST | `/v1/crosstab` | `crosstab` | Single crosstab with sig letters (A/B/C) |
| POST | `/v1/tabulate` | `process` | ★ Full tabulation → Excel (multi-sheet, sig, nets) |
| POST | `/v1/process` | `process` | Multi-operation pipeline (auto or manual) |
| POST | `/v1/convert` | `convert` | .sav → xlsx/csv/dta/parquet |
| POST | `/v1/parse-ticket` | `parse_ticket` | .docx Reporting Ticket → tab plan (Haiku) |
| GET | `/` | None | Embedded frontend |
| GET | `/docs` | None | Swagger UI |

---

## Key Patterns

### Crosstab with Significance Letters

The engine assigns uppercase letters (A, B, C, ...) to banner columns sorted by value. For each cell, a z-test compares that column's proportion to every other column. If p < alpha AND this proportion > other, the other column's letter appears.

- **Unweighted**: `proportions_ztest` from statsmodels
- **Weighted**: effective-n via Kish design effect: `n_eff = (Σw)² / Σ(w²)`

### Tabulation Builder (`/v1/tabulate`)

Generates professional Excel workbook:
- **Summary sheet**: file metadata, column legend (letter → label), stub index
- **One sheet per stub**: title, sig note, column headers (labels + letters), base (N), data rows with `pct% SIG_LETTERS`, Total column
- **Nets section**: Top 2 Box / Bottom 2 Box as green rows at bottom
- **Freeze panes**: row labels + headers frozen for scrolling
- `stubs: ["_all_"]` auto-selects all variables with ≥2 value labels

### Auth

- Keys prefixed `sk_live_` (production) or `sk_test_` (testing)
- SHA256 hashes stored in `API_KEYS_JSON` env var (no DB)
- Timing-safe comparison via `hmac.compare_digest`
- Each key has: `name`, `plan` (free/pro/business), `scopes` (list)

### Rate Limiting

In-memory sliding window (60s). Per plan:
- Free: 10/min, 5MB max
- Pro: 60/min, 50MB max
- Business: 200/min, 200MB max

### Usage Logging

Every authenticated request logs:
```
[USAGE] key=Acme plan=pro method=POST endpoint=/v1/tabulate status=200 request_bytes=4096 response_bytes=26064 time_ms=359
```
Queryable via Railway logs. In-memory counters at `GET /v1/usage`.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEYS_JSON` | Yes | JSON array of `{key_hash, name, plan, scopes}` |
| `ANTHROPIC_API_KEY` | No | Enables Haiku features (ticket parser, smart labeler) |
| `APP_ENV` | No | `production` or `development` (default) |
| `PORT` | No | Server port (default: 8000, Railway sets automatically) |
| `CORS_ORIGINS` | No | JSON array of allowed origins (default: `["*"]`) |

---

## Testing

```bash
# Run all 29 tests
cd C:\Users\jorge\proyectos_python\quantipro-api
python -m pytest tests/ -v

# Test with real .sav file
curl -X POST https://spss.insightgenius.io/v1/tabulate \
  -H "Authorization: Bearer sk_test_2a441a40c84ba0afe73efd47d6bb1066aac82ad5453360f3" \
  -F "file=@survey.sav" \
  -F 'spec={"banner":"region","stubs":["_all_"],"significance_level":0.95}' \
  -o tabulation.xlsx
```

Test .sav files: `C:\Users\jorge\OneDrive\Desktop\talk2data\`
- `Example 3 - LA Formulations Patient\Raw datat.sav` (85 cases × 175 vars)
- `uber_nps_uk_demo_n1000.sav` (1000 cases × 19 vars — in `0. Download HP`)

---

## Deployment

- Auto-deploy on `git push origin master` (Railway connected to GitHub)
- Docker multi-stage build (python:3.11-slim, git for quantipymrx wheel)
- Health check: `/v1/health` (30s interval)
- Custom domain: `spss.insightgenius.io` (DNS configured by user)
- Build time: ~2-3 minutes (mostly pip wheels)

---

## Dependencies (non-obvious)

- `quantipymrx`: Custom fork with `auto_detect`, crosstab, MRS analysis
- `python-pptx`: Required by quantipymrx import chain (RGBColor at init)
- `statsmodels`: `proportions_ztest` for significance testing
- `pyreadstat`: SPSS .sav read/write
- `python-docx`: .docx text extraction for Reporting Ticket parser
- `openpyxl`: Excel workbook generation (tabulation builder)

---

## Sprint History

### Sprint 1: Initial Release (Mar 18 2026)
- 7 endpoints: health, metadata, frequency, crosstab, convert, parse-ticket, process
- QuantipyMRX engine: auto-detect, frequency, crosstab with sig letters (A/B/C)
- API key auth, per-plan rate limiting, usage logging
- 22 tests, Dockerfile, Railway deploy

### Sprint 2: Tabulate + Frontend (Mar 19 2026)
- `POST /v1/tabulate` — full tabulation → professional Excel workbook
  - Multi-sheet (Summary + one per stub), sig letters, nets, column bases
  - `stubs=["_all_"]` auto-select, weight support, freeze panes
- Embedded frontend at `/` — drag & drop .sav, configure banner/stubs/nets, download Excel
- 29 tests total
- Deployed to `spss.insightgenius.io`
