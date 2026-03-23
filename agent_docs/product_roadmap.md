# SPSS InsightGenius — Product Roadmap

> Last updated: 2026-03-23

## Vision

Replace PSPP/WinCross/Quantum for 80% of market research tabulation use cases with a modern REST API + MCP server + embedded UI. The product IS the API — the frontend is a convenience wrapper for testing and demos. Competitive moat: AI-powered auto-analyze (zero-config) that no competitor offers.

---

## Current State (Sprint 6 — Mar 23 2026)

### What's Live

| Feature | Status | Endpoint |
|---------|--------|----------|
| SPSS .sav/.por/.zsav upload + metadata extraction | Production | `/v1/metadata` |
| Auto-detect question types (QuantipyMRX) | Production | in metadata response |
| Smart metadata: suggested_banners, detected_groups, preset_nets | Production | in metadata response |
| Frequency tables (weighted/unweighted, mean/std/median) | Production | `/v1/frequency` |
| Single crosstab with sig letters + chi2 p-value | Production | `/v1/crosstab` |
| Full tabulation → Excel (multi/single-sheet) | Production | `/v1/tabulate` |
| Means with T-test significance | Production | in tabulate |
| Multiple banners side-by-side (A/B + C/D/E) | Production | in tabulate |
| MRS groups (select-all-that-apply) | Production | in tabulate |
| Grid/Battery summary (T2B/Mean compact table) | Production | in tabulate |
| Custom groups (custom breaks with AND conditions) | Production | in tabulate |
| Total column as first column | Production | in tabulate |
| Nets (Top 2 Box, Bottom 2 Box, custom) | Production | in tabulate |
| Weight support (Kish effective-n, dual bases) | Production | in tabulate |
| Ticket → tabulate (.docx auto-parsed by Haiku) | Production | in tabulate |
| Correlation matrix (Pearson/Spearman/Kendall) | Production | `/v1/correlation` |
| One-way ANOVA with Tukey HSD post-hoc | Production | `/v1/anova` |
| Importance-Performance gap analysis | Production | `/v1/gap-analysis` |
| Satisfaction summary (T2B/B2B/Mean compact) | Production | `/v1/satisfaction-summary` |
| Auto-analyze (zero-config → complete Excel) | Production | `/v1/auto-analyze` |
| Format conversion (.sav → xlsx/csv/dta/parquet) | Production | `/v1/convert` |
| Reporting Ticket .docx parsing (Haiku) | Production | `/v1/parse-ticket` |
| Smart label suggestions (Haiku) | Built | not wired to endpoint |
| Executive summary generation (Haiku) | Built | `services/executive_summary.py` |
| API key auth + per-plan rate limiting (Redis) | Production | middleware |
| Usage logging for billing | Production | middleware + `/v1/usage` |
| Embedded web UI (drag & drop, auto-analyze) | Production | `/` |
| MCP server (12 tools, SSE transport) | Production | `/mcp/sse` |
| 68 automated tests | Production | pytest |

### Key Metrics

| Metric | Value |
|--------|-------|
| Total endpoints | 14 |
| MCP tools | 12 |
| Tests | 68 |
| Analysis types | 7 (frequency, crosstab, correlation, ANOVA, gap, satisfaction, auto) |
| AI services | 3 (ticket parser, smart labeler, executive summary) |
| Tabulate features | 10 (sig, means, nets, MRS, grids, custom groups, Total, multi/single-sheet, dual bases, ticket) |

---

## Completed Sprints

### Sprint 1: Initial Release (Mar 18)
7 endpoints, QuantipyMRX engine, API key auth, rate limiting, 22 tests.

### Sprint 2: Tabulate + Frontend (Mar 19)
`/v1/tabulate`, embedded frontend, 29 tests.

### Sprint 3: Tier 1 Features (Mar 19)
Means, multiple banners, MRS, dual bases, Total column, single-sheet mode, Grid/Battery, custom groups.

### Sprint 4: MRX Integration (Mar 20)
Engine delegates to MRX. Smart metadata (suggest_banners, detect_groups, preset_nets). Frontend connected.

### Sprint 5: Scaling + MCP (Mar 21)
Redis rate limiter, Gunicorn multi-worker, concurrency control, MCP server (7 tools).

### Sprint 6: Complete Features + UX (Mar 23)
- Schema sync (chi2, mean/std/median, metadata fields)
- 5 new endpoints: correlation, anova, gap-analysis, satisfaction-summary, auto-analyze
- Auto-analyze: smart grouping (excludes MRS/Grid members from individual stubs)
- 5 new MCP tools (total: 12)
- AI features: executive summary service, ticket → tabulate wiring
- 10 UX quick wins from external evaluation

---

## Next Up

### Tier 2: Core Improvements
| Item | Impact | Effort |
|------|--------|--------|
| Chi-square p-value in Excel sheet headers | Medium | Low |
| Filters / sub-populations in tabulate | High | Medium |
| Save/Load configuration (localStorage + JSON export) | High | Medium |
| "Try with sample data" button | High for conversion | Low |

### AI Features (Business plan)
| Feature | Status | Notes |
|---------|--------|-------|
| Prompt → Excel (NL → TabulateSpec via Haiku) | Not started | Highest-value AI feature |
| Executive Summary in Excel | Service built, not wired to tabulate | Wire `include_summary: true` |
| Smart Suggest (AI recommends full tab plan) | Partially done via suggest_banners | Expand to full spec |

### Deferred
| Item | Notes |
|------|-------|
| Builder refactor (MRS/means/prop sig → MRX) | Internal cleanup, no user impact. Current code works. |
| Google Sheets export | Needs Google service account credentials |
| PowerPoint export | Low priority — Excel is the product |
| User accounts / session persistence | Stateless by design |

---

## Pricing

| Plan | Price | Calls/mo | Max file | AI features |
|------|-------|----------|----------|-------------|
| Free | $0 | 50 | 5 MB | No |
| Growth | $29/mo | 500 | 50 MB | No |
| Business | $99/mo | 5,000 | 200 MB | Yes |
| Enterprise | Custom | Unlimited | 500 MB | Yes + priority |

Margins: 82-93% (compute cost ~$0.0003/request without AI, ~$0.0025 with AI).

---

## Competitive Position

| vs | InsightGenius wins | They win |
|----|-------------------|----------|
| PSPP (free) | UX, auto-analyze, API, Excel output, speed | Price (both free), trust (established) |
| SPSS (IBM) | Simplicity, auto-analyze, API | Depth, brand, data security, feature completeness |
| Displayr (web) | Simplicity, auto-analyze, one-click | Variable browser, PPT export, polish, collaboration |
| Q Research (web) | Simplicity, approachability | Depth, charting, agency features |

**True moat**: AI-powered Auto-Analyze. No competitor offers zero-config "upload → complete Excel".
