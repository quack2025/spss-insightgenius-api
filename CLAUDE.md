# CLAUDE.md — SPSS InsightGenius API

> Internal development notes for AI-assisted sessions.

---

## Project: SPSS InsightGenius API

**Product**: REST API + MCP server + embedded UI for processing SPSS (.sav) files into professional market research deliverables (Excel crosstabs with significance testing).
**Backend**: FastAPI (Python 3.11) on Railway (Gunicorn multi-worker, Redis rate limiter)
**Engine**: QuantipyMRX (custom fork: `quack2025/QuantiyFork2026`)
**AI**: Claude Haiku (`claude-haiku-4-5-20251001`) — ticket parsing, smart labeling, executive summary
**Frontend**: Embedded single-page HTML at `/` (Tailwind CDN + vanilla JS, no separate repo)
**MCP**: SSE transport at `/mcp/sse` — 12 tools for AI agent integration

### Infrastructure

| Resource | Value |
|----------|-------|
| GitHub repo | `quack2025/spss-insightgenius-api` |
| Local path | `C:\Users\jorge\proyectos_python\quantipro-api` |
| Production URL | `https://spss.insightgenius.io` |
| Railway project | `spss-insightgenius-api` (auto-deploy from `master`) |
| Railway URL | `spss-insightgenius-api-production.up.railway.app` |
| API Docs (Swagger) | `https://spss.insightgenius.io/docs` |
| MCP Endpoint | `https://spss.insightgenius.io/mcp/sse` |
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
2. **API-first** — The product IS the API. Frontend and MCP are convenience wrappers.
3. **Contract-stable** — Response shapes never change without version bump.
4. **Haiku-only** — AI features use only Haiku (~$0.001/request). No Sonnet/Opus.
5. **MRX-first** — Engine delegates to QuantipyMRX when available, falls back to pandas.

### Request Flow

```
Client → Bearer auth → Rate limit check → Router → run_in_executor(engine) → Response
                                                          ↓
                                              QuantiProEngine (stateless)
                                                   ↓           ↓
                                             pyreadstat    QuantipyMRX
                                             (always)     (if available)
```

### File Structure

```
quantipro-api/
├── main.py                         # FastAPI app, middleware, router registration, MCP mount
├── config.py                       # Pydantic Settings (env vars)
├── auth.py                         # API key auth (SHA256, timing-safe, scopes)
├── public/
│   └── index.html                  # Embedded frontend (Tailwind CDN + vanilla JS)
├── routers/
│   ├── health.py                   # GET /v1/health, GET /v1/usage
│   ├── metadata.py                 # POST /v1/metadata (+ suggested_banners, detected_groups, preset_nets)
│   ├── frequency.py                # POST /v1/frequency (+ mean, std, median)
│   ├── crosstab.py                 # POST /v1/crosstab (+ chi2, chi2_pvalue)
│   ├── tabulate.py                 # POST /v1/tabulate (★ core — now with ticket parsing)
│   ├── convert.py                  # POST /v1/convert
│   ├── parse_ticket.py             # POST /v1/parse-ticket
│   ├── process.py                  # POST /v1/process
│   ├── correlation.py              # POST /v1/correlation (★ new)
│   ├── anova.py                    # POST /v1/anova (★ new)
│   ├── gap_analysis.py             # POST /v1/gap-analysis (★ new)
│   ├── satisfaction.py             # POST /v1/satisfaction-summary (★ new)
│   ├── auto_analyze.py             # POST /v1/auto-analyze (★ new — zero-config)
│   └── mcp_server.py              # MCP SSE server — 12 tools
├── services/
│   ├── quantipy_engine.py          # Core: load_spss, frequency, crosstab, nps (MRX delegation + pandas fallback)
│   ├── tabulation_builder.py       # Excel builder: multi/single-sheet, sig letters, nets, means, MRS, grids
│   ├── auto_planner.py             # Deterministic tab plan from metadata
│   ├── ticket_parser.py            # Haiku: .docx → structured tab plan
│   ├── smart_labeler.py            # Haiku: improve cryptic SPSS labels
│   ├── executive_summary.py        # Haiku: generate key findings from tabulation results
│   └── converter.py                # Format conversion: xlsx, csv, dta, parquet
├── schemas/
│   ├── requests.py                 # All request models
│   ├── responses.py                # All response models (contract) — synced with engine output
│   └── errors.py                   # ErrorCode enum + ErrorResponse
├── middleware/
│   ├── rate_limiter.py             # Redis-backed sliding window (fallback: in-memory)
│   ├── request_id.py               # X-Request-Id generation
│   ├── processing.py               # run_in_executor with concurrency control + timeout
│   └── usage_logger.py             # [USAGE] logs for billing
├── tests/                          # 68 tests (pytest)
├── agent_docs/                     # Product docs (pricing, roadmap, UX evaluation)
├── Dockerfile                      # Multi-stage: builder (git+wheels) → runtime (slim)
├── railway.toml                    # Railway deploy config (4 replicas)
└── requirements.txt                # All dependencies

```

---

## Endpoints (14 total)

| Method | Path | Auth Scope | Description |
|--------|------|-----------|-------------|
| GET | `/v1/health` | None | Health check + engine status |
| GET | `/v1/usage` | Any | Per-key usage counters (since last deploy) |
| POST | `/v1/metadata` | `metadata` | Variables, labels, types, suggested_banners, detected_groups, preset_nets |
| POST | `/v1/frequency` | `frequency` | Frequency table (counts, %, mean, std, median) |
| POST | `/v1/crosstab` | `crosstab` | Single crosstab with sig letters + chi2 p-value |
| POST | `/v1/tabulate` | `process` | ★ Full tabulation → Excel (multi/single-sheet, sig, nets, means, MRS, grids, custom groups). Accepts optional .docx ticket for AI-powered auto-config. |
| POST | `/v1/process` | `process` | Multi-operation pipeline (auto or manual) |
| POST | `/v1/convert` | `convert` | .sav → xlsx/csv/dta/parquet |
| POST | `/v1/parse-ticket` | `parse_ticket` | .docx Reporting Ticket → tab plan (Haiku) |
| POST | `/v1/correlation` | `crosstab` | Correlation matrix (Pearson/Spearman/Kendall) with p-values |
| POST | `/v1/anova` | `crosstab` | One-way ANOVA with Tukey HSD post-hoc |
| POST | `/v1/gap-analysis` | `crosstab` | Importance-Performance gap analysis with quadrants |
| POST | `/v1/satisfaction-summary` | `crosstab` | Compact T2B/B2B/Mean for multiple scale variables |
| POST | `/v1/auto-analyze` | `process` | ★ Zero-config: upload .sav → AI detects banners, groups, nets → complete Excel |
| GET | `/` | None | Embedded frontend |
| GET | `/docs` | None | Swagger UI |

## MCP Server (12 tools)

Mounted at `/mcp/sse` (SSE transport). All tools require `api_key` parameter. Files passed as base64.

| Tool | Wraps | Description |
|------|-------|-------------|
| `get_spss_metadata` | `/v1/metadata` | Variable metadata + auto-detect |
| `get_variable_info` | — | Single variable detail |
| `analyze_frequencies` | `/v1/frequency` | Frequency table |
| `analyze_crosstabs` | `/v1/crosstab` | Crosstab with sig letters |
| `export_data` | `/v1/convert` | Format conversion |
| `create_tabulation` | `/v1/tabulate` | Full tabulation → Excel (base64) |
| `list_files` | — | Available tools listing |
| `analyze_correlation` | `/v1/correlation` | Correlation matrix |
| `analyze_anova` | `/v1/anova` | ANOVA + Tukey HSD |
| `analyze_gap` | `/v1/gap-analysis` | Gap analysis |
| `summarize_satisfaction` | `/v1/satisfaction-summary` | Satisfaction summary |
| `auto_analyze` | `/v1/auto-analyze` | Zero-config → Excel (base64) |

---

## Key Patterns

### SPSSData Dataclass

All routers receive `SPSSData` from `QuantiProEngine.load_spss()`:
```python
@dataclass
class SPSSData:
    df: pd.DataFrame          # Always available
    meta: Any                 # pyreadstat metadata
    mrx_dataset: Any = None   # QuantipyMRX DataSet (may be None)
    file_name: str = ""
```
**Critical**: Access as `data.df`, `data.meta`, `data.mrx_dataset` — NOT `data["df"]`.

### MRX Delegation Pattern

Engine tries MRX first, falls back to pandas:
```python
if QUANTIPYMRX_AVAILABLE and data.mrx_dataset:
    result = mrx_function(data.mrx_dataset, ...)
else:
    result = pandas_fallback(data.df, ...)
```

### Metadata Smart Fields

`extract_metadata()` returns these AI-detected fields (can be `None` — always use `or []`/`or {}`):
- `suggested_banners`: list of `{variable, label, n_categories, confidence}`
- `detected_groups`: list of `{name, display_name, question_type, variables}` — types: `awareness`, `scale`, `top_of_mind`
- `preset_nets`: dict of `{var_name: {"Top 2 Box": [4,5], "Bottom 2 Box": [1,2]}}`
- `detected_weights`: list of weight variable names

### Auto-Analyze Smart Grouping

`/v1/auto-analyze` excludes grouped variables from individual stubs:
1. Variables in `awareness`/`top_of_mind` groups → MRS sheets
2. Variables in `scale` groups → Grid summary sheets
3. Remaining ungrouped variables → individual crosstab sheets

This reduces a 291-variable file from ~214 sheets to ~63 (18 MRS + 2 Grid + ~43 individual).

### Tabulate with Ticket

`/v1/tabulate` accepts optional `ticket` (.docx file). If provided:
1. Haiku parses ticket → extracts banners, stubs, weight
2. Extracted plan overrides empty spec fields
3. Falls back gracefully if no ANTHROPIC_API_KEY

### Excel Sheet Name Sanitization

Excel prohibits `: / \ * ? [ ]` in sheet names. `_sanitize_sheet_name()` replaces them.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEYS_JSON` | Yes | JSON array of `{key_hash, name, plan, scopes}` |
| `ANTHROPIC_API_KEY` | No | Enables Haiku features (ticket parser, smart labeler, executive summary) |
| `REDIS_URL` | No | Redis for rate limiting + MCP SSE relay across replicas |
| `APP_ENV` | No | `production` or `development` (default) |
| `PORT` | No | Server port (default: 8000, Railway sets automatically) |
| `CORS_ORIGINS` | No | JSON array of allowed origins (default: `["*"]`) |
| `PROCESSING_TIMEOUT_SECONDS` | No | Max processing time per request (default: 120) |
| `MAX_CONCURRENT_JOBS` | No | Max concurrent file processing (default: 3) |

---

## Testing

```bash
# Run all 68 tests
cd C:\Users\jorge\proyectos_python\quantipro-api
python -m pytest tests/ -v

# Test with real .sav files
SAV="C:\Users\jorge\OneDrive\0. Download HP\uber_nps_uk_demo_n1000.sav"
KEY="Bearer sk_test_2a441a40c84ba0afe73efd47d6bb1066aac82ad5453360f3"

# Tabulate
curl -X POST https://spss.insightgenius.io/v1/tabulate \
  -H "Authorization: $KEY" -F "file=@$SAV" \
  -F 'spec={"banners":["region"],"stubs":["_all_"],"include_means":true}' -o tab.xlsx

# Auto-analyze (zero config)
curl -X POST https://spss.insightgenius.io/v1/auto-analyze \
  -H "Authorization: $KEY" -F "file=@$SAV" -o auto.xlsx

# Correlation
curl -X POST https://spss.insightgenius.io/v1/correlation \
  -H "Authorization: $KEY" -F "file=@$SAV" \
  -F 'spec={"variables":["sat_speed","sat_price","sat_overall"]}'

# ANOVA
curl -X POST https://spss.insightgenius.io/v1/anova \
  -H "Authorization: $KEY" -F "file=@$SAV" \
  -F 'spec={"dependent":"sat_overall","factor":"region","post_hoc":true}'
```

Test .sav files:
- `uber_nps_uk_demo_n1000.sav` (1000 cases x 19 vars — English, simple, 0 detected groups)
- `spss.sav` on Desktop (493 cases x 291 vars — Spanish, complex, 21 detected groups)
- `Example 3 - LA Formulations Patient\Raw datat.sav` (85 cases x 175 vars)

---

## Deployment

- Auto-deploy on `git push origin master` (Railway connected to GitHub)
- Docker multi-stage build (python:3.11-slim, git for quantipymrx wheel)
- Gunicorn multi-worker (4 replicas via `railway.toml`)
- Redis for rate limiting + MCP SSE session relay across replicas
- Health check: `/v1/health` (30s interval)
- Custom domain: `spss.insightgenius.io`
- Build time: ~2-3 minutes

---

## Pricing

| Plan | Price | Calls/mo | Max file | AI features |
|------|-------|----------|----------|-------------|
| Free | $0 | 50 | 5 MB | No |
| Growth | $29/mo | 500 | 50 MB | No |
| Business | $99/mo | 5,000 | 200 MB | Yes (ticket parsing, executive summary, smart suggest) |
| Enterprise | Custom | Unlimited | 500 MB | Yes + priority |

---

## Sprint History

### Sprint 1: Initial Release (Mar 18 2026)
- 7 endpoints, QuantipyMRX engine, API key auth, rate limiting, 22 tests

### Sprint 2: Tabulate + Frontend (Mar 19 2026)
- `/v1/tabulate`, embedded frontend, 29 tests

### Sprint 3: Tier 1 Features (Mar 19 2026)
- Means with T-test, multiple banners, MRS groups, dual bases, Total first column, single-sheet mode, Grid/Battery summary, custom groups

### Sprint 4: MRX Integration (Mar 20 2026)
- Engine delegates crosstab/frequency/NPS to MRX. Smart metadata (suggest_banners, detect_groups, preset_nets). Frontend connected to backend smart features.

### Sprint 5: Scaling + MCP (Mar 21 2026)
- Redis rate limiter, Gunicorn multi-worker, concurrency control, timeouts
- MCP server with SSE transport — 7 tools

### Sprint 6: Complete Features (Mar 23 2026)
- Response schemas synced (chi2, mean/std/median, metadata smart fields)
- 4 new analysis endpoints: correlation, anova, gap-analysis, satisfaction-summary
- Auto-analyze endpoint (zero-config SPSS → Excel with smart grouping)
- 5 new MCP tools (total: 12)
- AI features: executive summary service, ticket → tabulate wiring
- 10 UX quick wins from external evaluation (tooltips, examples, error recovery, brand unification)
- 68 tests total
