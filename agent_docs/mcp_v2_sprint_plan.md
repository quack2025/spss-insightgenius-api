# MCP Server v2 — Sprint Plan

> Based on: `MCP_SERVER_V2_IMPLEMENTATION_SPEC.md`
> Date: 2026-03-23
> FastMCP: 2.14.5 (Streamable HTTP confirmed available)
> Current MCP: v1 with 12 tools, SSE transport, api_key per tool call

---

## Overview

5 sprints, each independently deployable. Each sprint has a clear deliverable and test criteria.

| Sprint | Epic | Deliverable | Effort |
|--------|------|------------|--------|
| **S1** | Foundation | Pydantic models + insight generator + response formatter + downloads endpoint | ~3h |
| **S2** | Core Rewrite | New mcp_server.py with 13 tools, file sessions, content_blocks | ~4h |
| **S3** | Transport & Auth | Streamable HTTP mount + transport-level auth + SSE deprecation | ~2h |
| **S4** | Multi-Format | .csv/.xlsx upload + auto-detect + format-agnostic analysis | ~2h |
| **S5** | Quality & Publish | Evaluation suite + conditional registration + server_info + final polish | ~2h |

**Total estimated: ~13h**

---

## Sprint 1: Foundation (New Files)

### Goal
Create all supporting files that the MCP rewrite will need. No changes to existing code.

### Deliverables

**1a. `schemas/mcp_models.py`** (NEW)
- All 13 Pydantic input models from spec Section 5
- `FileReference` base class (file_id OR file_base64)
- `ResponseFormat` enum (json/markdown)
- Field validators (significance_level normalization, method validation)

**1b. `services/insight_generator.py`** (NEW)
- `generate_insight_summary(tool, results)` — deterministic template-based
- `generate_content_blocks(tool, results)` — title, subtitle, key_finding, chart_description, data_table_markdown
- Templates for: frequencies, crosstab, correlation, ANOVA, gap, satisfaction, tabulation
- **NO LLM calls** — pure logic

**1c. `services/response_formatter.py`** (NEW)
- `format_frequency_markdown(result)` → markdown table
- `format_crosstab_markdown(result)` → markdown with sig letters
- `format_correlation_markdown(result)` → matrix as markdown
- `format_anova_markdown(result)` → F-test + Tukey table
- `to_response(tool, results, format, file_id)` → wraps in standard envelope

**1d. `routers/downloads.py`** (NEW)
- `GET /downloads/{token}` — serve temp file from Redis
- UUID v4 tokens, 5-min TTL, no auth (token IS the secret)
- Content-Disposition header with meaningful filename
- 404 with helpful message after expiry

**1e. `config.py`** additions
- `spss_session_ttl_seconds: int = 1800`
- `redis_max_file_size_mb: int = 100`

### Tests
- `tests/test_insight_generator.py` — templates produce non-empty strings for each tool type
- `tests/test_downloads.py` — store + retrieve + expiry
- Import all models: `from schemas.mcp_models import *`

### Verification
```bash
python -m pytest tests/test_insight_generator.py tests/test_downloads.py -v
```

---

## Sprint 2: MCP Server Rewrite (Core)

### Goal
Rewrite `routers/mcp_server.py` with all 13 tools, Pydantic models, content_blocks, file sessions.

### Deliverables

**2a. File session system**
- `spss_upload_file` tool — base64 → Redis with 30-min sliding TTL
- `_resolve_file(file_id, file_base64, filename)` helper — shared by all tools
- `_load_data(file_bytes, format, filename)` → SPSSData
- Redis keys: `spss:file:{file_id}`, `spss:meta:{file_id}`

**2b. 13 tools with Pydantic models**

| # | Tool | Input Model | Key Changes vs v1 |
|---|------|------------|-------------------|
| 1 | `spss_upload_file` | `UploadFileInput` | NEW — file sessions |
| 2 | `spss_get_metadata` | `GetMetadataInput` | Uses file_id, adds response_format |
| 3 | `spss_describe_variable` | `DescribeVariableInput` | Renamed from get_variable_info |
| 4 | `spss_get_server_info` | — (no input) | NEW — reports available tools |
| 5 | `spss_analyze_frequencies` | `AnalyzeFrequenciesInput` | **Batch**: 1-50 variables |
| 6 | `spss_analyze_crosstab` | `AnalyzeCrosstabInput` | Pydantic, multi-banner support |
| 7 | `spss_analyze_correlation` | `AnalyzeCorrelationInput` | Pydantic |
| 8 | `spss_analyze_anova` | `AnalyzeAnovaInput` | Pydantic |
| 9 | `spss_analyze_gap` | `AnalyzeGapInput` | Pydantic |
| 10 | `spss_summarize_satisfaction` | `SummarizeSatisfactionInput` | Pydantic |
| 11 | `spss_auto_analyze` | `AutoAnalyzeInput` | Returns download_url |
| 12 | `spss_create_tabulation` | `CreateTabulationInput` | Returns download_url |
| 13 | `spss_export_data` | `ExportDataInput` | Returns download_url |

**2c. Response envelope**
Every analysis tool returns:
```json
{
  "tool": "spss_analyze_frequencies",
  "file_id": "abc123",
  "variables_analyzed": [...],
  "sample_size": 796,
  "weighted": false,
  "results": [...],
  "insight_summary": "...",
  "content_blocks": { "title": "...", "key_finding": "...", "data_table_markdown": "..." }
}
```

**2d. Download URLs for Excel output**
- `spss_create_tabulation`, `spss_auto_analyze`, `spss_export_data` → store bytes in Redis → return download_url
- Uses `routers/downloads.py` from Sprint 1

### Tests
- `tests/test_mcp_v2.py` — test all 13 tools with mock data
- Test file upload → file_id → reuse in subsequent tool
- Test content_blocks non-empty for each analysis type

### Verification
```bash
python -m pytest tests/test_mcp_v2.py -v
# Live: connect Claude Desktop to /mcp/sse and run a multi-tool chain
```

---

## Sprint 3: Transport & Auth

### Goal
Add Streamable HTTP transport (MCP standard 2025-11) + transport-level auth.

### Deliverables

**3a. Streamable HTTP mount in `main.py`**
- Mount FastMCP's HTTP app at `/mcp`
- Use `mcp.http_app()` or equivalent from fastmcp 2.14
- Keep SSE at `/mcp/sse` with `X-MCP-Deprecated` header

**3b. Transport-level auth in `auth.py`**
- `auth_from_header(authorization: str) -> KeyConfig` — extracts Bearer token from HTTP header
- MCP middleware/dependency that reads `Authorization` header and stores `key_config` in context
- Tools read auth from context — `api_key` parameter becomes OPTIONAL (backwards compat)
- Scope validation per tool

**3c. SSE deprecation**
- SSE still works but adds response header: `X-MCP-Deprecated: Use /mcp instead. SSE removed 2026-06-01.`
- Log warning on SSE connections

### Tests
- Test Streamable HTTP endpoint responds
- Test auth via header (no api_key in tool call)
- Test SSE still works with api_key parameter
- Test scope validation

### Verification
```bash
# Test Streamable HTTP
curl -X POST https://spss.insightgenius.io/mcp \
  -H "Authorization: Bearer sk_test_..." \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/list"}'
```

---

## Sprint 4: Multi-Format Support

### Goal
Accept .csv, .xlsx, .xls files in addition to .sav.

### Deliverables

**4a. Multi-format upload in `spss_upload_file`**
- Auto-detect format from filename extension
- .sav/.por/.zsav → pyreadstat (existing)
- .csv/.tsv → pandas.read_csv with delimiter auto-detect (csv.Sniffer)
- .xlsx/.xls → pandas.read_excel
- Response includes `format_detected` and `metadata_inferred: true` for non-SPSS

**4b. `_load_data()` multi-format handler**
- SPSSData with `meta=None` for CSV/Excel (no pyreadstat metadata)
- `mrx_dataset=None` for non-SPSS (no QuantipyMRX support)
- All analysis tools handle missing metadata gracefully (use column names as labels)

**4c. Metadata for non-SPSS**
- Infer variable types from pandas dtypes (int/float → numeric, object → string)
- Auto-detect value labels: for columns with < 20 unique values, create labels from unique values
- Flag `metadata_inferred: true` in response

### Tests
- Upload .csv → analyze → verify results
- Upload .xlsx → analyze → verify results
- Mixed: upload .csv, run frequency → same result shape as .sav

### Verification
```bash
# Test with CSV
echo "gender,age,satisfaction\nM,25,4\nF,30,5\nM,45,3" > /tmp/test.csv
base64 /tmp/test.csv | ...  # Upload via MCP
```

---

## Sprint 5: Quality & Publishing

### Goal
Pass quality bar for Claude Directory / MCP Registry submission.

### Deliverables

**5a. Tool annotations**
- Every tool: `@mcp.tool(annotations={"readOnlyHint": True, ...})`
- Comprehensive docstrings: what, when to use, when NOT to use, return schema, examples

**5b. `spss_get_server_info` tool**
- Reports: engine status, available tools (with reasons for missing), plan limits, version

**5c. Conditional tool registration**
- Tools 7-10 (correlation, ANOVA, gap, satisfaction) only registered if `QUANTIPYMRX_AVAILABLE`
- Warning logged at startup for each skipped tool

**5d. Evaluation suite**
- `tests/evaluation.xml` — 10 QA pairs using demo .sav
- Questions require multi-tool chains (upload → metadata → analysis)
- `tests/evaluation.py` — runner script, pass/fail per question
- Target: 8/10 pass

**5e. Publishing metadata**
- Server name: `spss_mcp`
- Version from config
- Proper `instructions` field in FastMCP init
- Icons/website_url if fastmcp supports

### Tests
- Full evaluation suite: 8/10 pass
- `spss_get_server_info` returns correct tool list
- Conditional registration: mock QUANTIPYMRX_AVAILABLE=False → tools 7-10 absent

### Verification
```bash
python tests/evaluation.py  # 8/10 pass
# Submit to Claude Directory staging
```

---

## Deployment Strategy

Each sprint is independently deployable:
1. Sprint 1: Foundation files deployed (no behavior change)
2. Sprint 2: MCP v2 replaces v1 (breaking for MCP clients — coordinate with users)
3. Sprint 3: Streamable HTTP available alongside SSE
4. Sprint 4: Multi-format support (additive, no breaking changes)
5. Sprint 5: Quality polish (additive)

**Rollback**: Each sprint is one commit. `git revert` if issues.

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| Streamable HTTP mount conflicts with FastAPI routes | Test `mcp.http_app()` integration before Sprint 3 |
| Redis file storage memory pressure (100MB files) | `maxmemory-policy allkeys-lru` + MAX_FILE_SIZE_MB config |
| Breaking change for existing MCP v1 clients | Sprint 2 keeps backwards compat via `api_key` param + `file_base64` |
| fastmcp 2.14 API changes | Pin version in requirements.txt |
| Evaluation suite instability | Use deterministic assertions, not LLM-dependent |
