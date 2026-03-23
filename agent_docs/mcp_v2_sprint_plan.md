# MCP Server v2 — Sprint Plan (Revised)

> Based on: `MCP_SERVER_V2_IMPLEMENTATION_SPEC.md`
> Date: 2026-03-23
> FastMCP: 2.14.5 (Streamable HTTP confirmed available)
> Current MCP: v1 with 12 tools, SSE transport, api_key per tool call
> **Revised with 7 adjustments from Jorge**

---

## Overview

5 sprints, each independently deployable. Each sprint has a clear deliverable and test criteria.

| Sprint | Epic | Deliverable | Effort |
|--------|------|------------|--------|
| **S1** | Foundation | Pydantic models + insight generator + response formatter + downloads endpoint | ~3h |
| **S2** | Core Rewrite | New mcp_server.py: 13 tools, file sessions, content_blocks, annotations, conditional registration, tabulation JSON summary | ~5h |
| **S3** | Transport & Auth | Streamable HTTP mount + transport-level auth + SSE deprecation | ~2h |
| **S4** | Multi-Format | .csv/.xlsx upload + auto-detect + format-agnostic analysis + complete insight templates | ~2h |
| **S5** | Quality & Publish | Evaluation suite + server_info polish + server.json manifest | ~2h |

**Total estimated: ~14h**

---

## Sprint 1: Foundation (New Files) — COMPLETE

### Delivered
- `schemas/mcp_models.py` — 13 Pydantic input models, FileReference base, ResponseFormat enum, validators
- `services/insight_generator.py` — deterministic templates for freq, crosstab, correlation, ANOVA, gap, satisfaction, tabulation (Adj 4: freq/crosstab/tabulation are complete, others are functional stubs)
- `services/response_formatter.py` — build_mcp_response() envelope + markdown formatters per tool
- `routers/downloads.py` — GET /downloads/{token}, Redis-backed, 5-min TTL, no auth
- `config.py` — spss_session_ttl_seconds, redis_max_file_size_mb, base_url

---

## Sprint 2: MCP Server Rewrite (Core)

### Goal
Rewrite `routers/mcp_server.py` with all 13 tools, Pydantic models, content_blocks, file sessions, **annotations from day one**, **conditional registration**, and **tabulation JSON summary**.

### Adjustments Applied
- **Adj 1**: Annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) on every tool from the start (spec section 4.2)
- **Adj 2**: Conditional registration — tools 7-10 only registered if `QUANTIPYMRX_AVAILABLE`
- **Adj 3**: Tabulation JSON summary — decide between Option A (refactor builder) or Option B (read Excel back). Decision after reading tabulation_builder.py.
- **Adj 5**: `_resolve_file()` returns `(file_bytes, format_string)` from the start. `_load_data()` accepts `format` param. Sprint 2 only handles "sav". Sprint 4 adds csv/xlsx branches.
- **Adj 6**: E2E test chain: upload → metadata → frequencies → tabulation → download

### Deliverables

**2a. File session system**
- `spss_upload_file` tool — base64 → Redis with sliding TTL
- `_resolve_file(file_id, file_base64, filename) -> (bytes, format)` — multi-format ready (Adj 5)
- `_load_data(file_bytes, format, filename) -> SPSSData` — "sav" only in S2, branches for csv/xlsx in S4
- Redis keys: `spss:file:{file_id}`, `spss:meta:{file_id}`

**2b. 13 tools with Pydantic models + annotations (Adj 1)**

| # | Tool | readOnly | destructive | idempotent | openWorld | Conditional |
|---|------|----------|-------------|------------|-----------|-------------|
| 1 | `spss_upload_file` | false | false | true | false | — |
| 2 | `spss_get_metadata` | true | false | true | false | — |
| 3 | `spss_describe_variable` | true | false | true | false | — |
| 4 | `spss_get_server_info` | true | false | true | false | — |
| 5 | `spss_analyze_frequencies` | true | false | true | false | — |
| 6 | `spss_analyze_crosstab` | true | false | true | false | — |
| 7 | `spss_analyze_correlation` | true | false | true | false | MRX only (Adj 2) |
| 8 | `spss_analyze_anova` | true | false | true | false | MRX only (Adj 2) |
| 9 | `spss_analyze_gap` | true | false | true | false | MRX only (Adj 2) |
| 10 | `spss_summarize_satisfaction` | true | false | true | false | MRX only (Adj 2) |
| 11 | `spss_auto_analyze` | true | false | true | false | — |
| 12 | `spss_create_tabulation` | true | false | true | false | — |
| 13 | `spss_export_data` | true | false | true | false | — |

**2c. Tabulation JSON summary (Adj 3)**

`spss_create_tabulation` and `spss_auto_analyze` return:
```json
{
  "tool": "spss_create_tabulation",
  "download_url": "https://spss.insightgenius.io/downloads/{token}",
  "download_expires_in_seconds": 300,
  "stubs_processed": 17,
  "stubs_failed": 0,
  "banners_used": ["region"],
  "tables_summary": [
    {"stub": "Q1", "stub_label": "Overall satisfaction", "base_total": 796, "top_finding": "North 72% T2B"}
  ],
  "content_blocks": { "title": "...", "slides": [...] },
  "insight_summary": "..."
}
```

Decision on approach documented in code comment at top of implementation.

**2d. Response envelope**
Every analysis tool returns standard envelope via `build_mcp_response()` from Sprint 1.

### Tests
- `tests/test_mcp_v2.py` — unit tests per tool (mock data)
- **E2E chain test (Adj 6)**: upload → metadata → frequencies → tabulation → GET /downloads/{token} → 200

### Verification
```bash
python -m pytest tests/test_mcp_v2.py -v
# Live: connect Claude Desktop to /mcp/sse, run multi-tool chain
```

---

## Sprint 3: Transport & Auth

### Goal
Add Streamable HTTP transport (MCP standard 2025-11) + transport-level auth.

### Deliverables

**3a. Streamable HTTP mount in `main.py`**
- Use `mcp.http_app()` from fastmcp 2.14
- Mount at `/mcp`
- Keep SSE at `/mcp/sse` with `X-MCP-Deprecated` header

**3b. Transport-level auth in `auth.py`**
- `auth_from_header(authorization: str) -> KeyConfig`
- MCP middleware reads `Authorization` header → stores `key_config` in context
- `api_key` parameter becomes OPTIONAL (backwards compat for SSE clients)
- Scope validation per tool

**3c. SSE deprecation**
- Header: `X-MCP-Deprecated: Use /mcp instead. SSE removed 2026-06-01.`
- Log warning on SSE connections

### Tests
- Streamable HTTP responds to `tools/list`
- Auth via header works (no api_key in tool call)
- SSE still works with api_key parameter
- Scope validation rejects unauthorized tools

---

## Sprint 4: Multi-Format Support + Complete Insight Templates

### Goal
Accept .csv, .xlsx, .xls files. Complete insight_generator templates for all tool types.

### Deliverables

**4a. Multi-format in `_load_data()`**
- Add branches for csv/tsv (pandas.read_csv + csv.Sniffer) and xlsx/xls (pandas.read_excel)
- SPSSData with `meta=None`, `mrx_dataset=None` for non-SPSS
- All analysis tools handle missing metadata gracefully

**4b. Multi-format upload in `spss_upload_file`**
- Response includes `format_detected` and `metadata_inferred: true`

**4c. Complete insight templates (Adj 4)**
- Flesh out correlation, ANOVA, gap, satisfaction templates in `insight_generator.py`
- Full markdown formatters in `response_formatter.py`

### Tests
- Upload .csv → frequency → verify result shape matches .sav
- Upload .xlsx → metadata → verify inferred types
- Insight templates return meaningful text for all 7 tool types

---

## Sprint 5: Quality & Publishing

### Goal
Pass quality bar for Claude Directory / MCP Registry submission.

### Deliverables

**5a. `spss_get_server_info` tool**
- Engine status, available/unavailable tools (with reasons), plan limits, version

**5b. Evaluation suite**
- `tests/evaluation.xml` — 10 QA pairs using demo .sav
- `tests/evaluation.py` — runner, 8/10 pass target

**5c. `server.json` manifest (Adj 7)**
- Schema: `static.modelcontextprotocol.io/schemas/2025-07-09/server.schema.json`
- Remote endpoint: `"type": "streamable-http"` → `https://spss.insightgenius.io/mcp`
- Name, description, version, tool list

**5d. Final polish**
- Docstrings: what, when to use, when NOT to use, return schema, examples
- Server name: `spss_mcp`
- Instructions field in FastMCP init
- Icons/website_url

### Tests
- Evaluation: 8/10 pass
- server.json validates against schema
- `spss_get_server_info` returns correct tool list

---

## Deployment Strategy

1. Sprint 1: Foundation deployed (no behavior change) — **DONE**
2. Sprint 2: MCP v2 replaces v1 (backwards compat via api_key + file_base64)
3. Sprint 3: Streamable HTTP alongside SSE
4. Sprint 4: Multi-format (additive)
5. Sprint 5: Quality + publishing artifacts

**Rollback**: Each sprint is one commit. `git revert` if issues.

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| Streamable HTTP mount conflicts with FastAPI | Test `mcp.http_app()` integration in Sprint 3 |
| Redis memory pressure (100MB files) | `maxmemory-policy allkeys-lru` + MAX_FILE_SIZE_MB |
| Breaking MCP v1 clients | Keep api_key param + file_base64 as alternatives |
| Tabulation JSON summary too complex | Start with Option B (read Excel), upgrade to A later |
| fastmcp API changes | Pin version in requirements.txt |
