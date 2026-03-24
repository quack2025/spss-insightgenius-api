# SPSS InsightGenius — MCP Server Technical Documentation

> Server name: `spss_mcp` | Version: 2.0.0 | 14 tools | Streamable HTTP + SSE

---

## Quick Start

### Connect from Claude Desktop / Cursor

Add to your MCP settings:

```json
{
  "mcpServers": {
    "spss_insightgenius": {
      "url": "https://spss.insightgenius.io/mcp/http",
      "headers": {
        "Authorization": "Bearer sk_test_YOUR_API_KEY"
      }
    }
  }
}
```

### Connect from n8n / Make

SSE endpoint (legacy): `https://spss.insightgenius.io/mcp/sse`
Pass `api_key` as parameter in each tool call.

### First Conversation

```
User: I have a survey file. Analyze it.
Claude: [calls spss_upload_file with the base64 file]
Claude: [calls spss_get_metadata with file_id]
Claude: "Your file has 1000 cases, 19 variables. I see 3 suggested banners:
         gender, age_group, region. Let me run the analysis..."
Claude: [calls spss_auto_analyze with file_id]
Claude: "Done! Here's a summary of findings: ..."
Claude: [provides download link for Excel]
```

---

## Architecture

```
Client (Claude Desktop / Cursor / n8n)
    │
    │ Streamable HTTP: POST /mcp/http
    │ SSE (deprecated): GET /mcp/sse + POST /mcp/messages/
    │ Auth: Authorization: Bearer sk_live_...
    │
    ▼
┌────────────────────────────────────────────┐
│  FastMCP (spss_mcp)                        │
│                                            │
│  14 tools → _resolve_file() → _load_data() │
│       ↓                                    │
│  QuantiProEngine (stateless)               │
│       ↓              ↓                     │
│  pyreadstat    QuantipyMRX                 │
│  (always)     (if available)               │
│                                            │
│  → build_mcp_response()                    │
│       ↓                                    │
│  insight_summary + content_blocks          │
│       ↓                                    │
│  JSON response (or download_url)           │
└────────────────────────────────────────────┘
        │
        ├── Redis: file sessions (spss:file:{id}, 30-min TTL)
        ├── Redis: downloads (dl:{token}, 5-min TTL)
        └── Redis: rate limiting + SSE relay
```

---

## Transports

| Transport | Endpoint | Status | Auth |
|-----------|----------|--------|------|
| **Streamable HTTP** | `/mcp/http` | Primary (MCP standard 2025-11) | `Authorization: Bearer` header |
| **SSE** | `/mcp/sse` | Deprecated (removed 2026-06-01) | `api_key` parameter per tool |

Streamable HTTP is stateless per-request — works across all Gunicorn workers without session relay.

SSE requires Redis pub/sub relay for cross-replica session routing (Railway numReplicas > 1).

---

## File Sessions

### Upload Once, Analyze Many

Instead of sending 50MB of base64 on every tool call:

1. `spss_upload_file(file_base64, filename)` → `{file_id: "abc123", ttl_seconds: 1800}`
2. All subsequent tools: pass `file_id="abc123"` instead of `file_base64`
3. TTL refreshes on every access (sliding window)
4. After 30 minutes of inactivity, session expires

### Backwards Compatibility

Every tool accepts BOTH:
- `file_id` (preferred — from upload)
- `file_base64` (inline — no upload needed)

If both provided, `file_id` takes precedence.

### Supported Formats

| Format | Extension | Parser | Metadata |
|--------|-----------|--------|----------|
| SPSS | .sav, .por, .zsav | pyreadstat + QuantipyMRX | Full (labels, types, value labels) |
| CSV | .csv, .tsv | pandas (auto-detect delimiter) | Inferred from dtypes |
| Excel | .xlsx, .xls | pandas.read_excel | Inferred from dtypes |

Non-SPSS files: `metadata_inferred: true` in upload response. Column names used as variable names.

---

## Response Envelope

Every analysis tool returns this structure:

```json
{
  "tool": "spss_analyze_frequencies",
  "file_id": "abc123",
  "variables_analyzed": ["Q1_satisfaction"],
  "sample_size": 796,
  "weighted": false,
  "format_detected": "sav",
  "results": { ... },
  "insight_summary": "Q1 satisfaction: most common is 'Satisfied' (38.2%, n=796)",
  "content_blocks": {
    "title": "Customer Satisfaction Distribution",
    "subtitle": "Q1: Overall satisfaction (n=796)",
    "key_finding": "'Satisfied' is the most common response (38.2%)",
    "chart_description": "Bar chart with 5 categories. Peak at 'Satisfied' (38.2%).",
    "data_table_markdown": "| Value | % | Count |\n|---|---|---|\n| Very satisfied | 34.2% | 272 |..."
  }
}
```

### content_blocks — Composability

`content_blocks` is tool-agnostic: works with ANY presentation tool:
- **Gamma MCP**: pass `content_blocks.title` + `content_blocks.key_finding` → auto-generate slides
- **python-pptx**: use `content_blocks.data_table_markdown` → render as table
- **Canva MCP**: use `content_blocks.title` + `content_blocks.subtitle`
- **Google Slides API**: use `content_blocks.slides[]` for tabulation results

### response_format

Every analysis tool accepts `response_format`:
- `"json"` (default): full structured data in `results`
- `"markdown"`: human-readable tables in `results_markdown`

### Download URLs (Excel-producing tools)

`spss_create_tabulation`, `spss_auto_analyze`, `spss_export_data` return:
```json
{
  "download_url": "https://spss.insightgenius.io/downloads/{token}",
  "download_expires_in_seconds": 300,
  "filename": "tabulation_region_survey.xlsx"
}
```

`GET /downloads/{token}` serves the file. No auth needed (token is the secret). 5-minute TTL.

Falls back to `data_base64` in the response if Redis is unavailable.
