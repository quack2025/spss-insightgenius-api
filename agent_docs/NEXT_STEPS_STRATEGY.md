# Talk2Data InsightGenius — Strategic Next Steps

**Date:** 2026-03-24
**Status:** Active

---

## Core Positioning (Agreed)

### The Product Claim

> **Statistical Precision Guaranteed.**
> Same data + same spec = same results. Every time.
> No prompt variability. No hallucinated statistics. No rounding differences between runs.
> Powered by QuantipyMRX — a deterministic statistical engine, not an LLM.

### The Positioning Statement

> **Claude analyzes. InsightGenius certifies.**
> Use Claude to explore your data. Use InsightGenius when the numbers need to be right.

### Why This Matters

Claude/ChatGPT can analyze data — but:
- Results change between runs (non-deterministic)
- No significance letters (A/B/C industry standard)
- No publication-ready Excel output
- Can't be automated in pipelines
- Not auditable or reproducible

InsightGenius is the **certified deliverable**, not the exploration tool.

---

## Value Differentiators vs Claude Native

| Feature | Claude Native | InsightGenius | Real Difference? |
|---------|--------------|---------------|-----------------|
| Basic frequencies/crosstabs | Yes | Yes | No |
| **Sig letters (A/B/C)** | No | Yes | **YES** |
| **Publication-ready Excel** | No | Yes | **YES** |
| **MRS detection & tabulation** | No | Yes | **YES** |
| **Grid/Battery summaries** | No | Yes | **YES** |
| **Means with T-test sig** | No | Yes | **YES** |
| **Deterministic results** | No | Yes | **YES** |
| **Batch (200+ vars in 43s)** | No (20+ prompts) | Yes | **YES** |
| **Pipeline/automation (n8n/Make)** | Impossible | API + MCP | **YES** |
| **Reporting Ticket → Excel** | No | Haiku parses .docx | **YES** |

---

## Automation Use Cases (n8n / Make / Zapier)

### 1. Survey Closes → Excel in Inbox
```
Qualtrics/SurveyMonkey → Webhook → n8n
  → POST /v1/files/upload
  → POST /v1/auto-analyze
  → Email Excel to research director
```

### 2. Survey Closes → Gamma Presentation
```
Qualtrics → n8n → InsightGenius /v1/tabulate
  → content_blocks (structured JSON)
  → Gamma API: generate presentation
  → Slack/Email: "Presentation ready: [link]"
```

### 3. Weekly Tracker (Wave Comparison)
```
Every Friday 6pm:
  n8n cron → Download .sav from Qualtrics API
  → InsightGenius /v1/tabulate (same spec every week)
  → Save Excel to Google Drive /Tracker/Wave_N/
  → Slack: "Wave 12 ready. NPS up 3pp vs wave 11."
```
Same spec every week = comparable results. Impossible with Claude.

### 4. Multi-Country Panel
```
5 agencies in 5 countries upload .sav to Google Drive
  → Make detects new file
  → InsightGenius /v1/tabulate (same spec for all)
  → Consolidated Excel per country
  → Gamma: regional comparison presentation
```

### 5. Automated QA During Fieldwork
```
Qualtrics survey in progress (soft launch, n=50)
  → Every 24h: n8n downloads partial .sav
  → InsightGenius /v1/metadata → check valid n per variable
  → InsightGenius /v1/frequency → verify quota distribution
  → If quota > 10% deviation → Slack alert to PM
```

### 6. White-Label Client Portal
```
Your webapp → Client uploads .sav
  → Your backend calls POST /v1/tabulate
  → Client downloads Excel with YOUR branding
  → You charge $500/study, InsightGenius costs $0.003
```
Margin: 99.9%. Client never knows InsightGenius exists.

---

## Immediate Action Items

### Priority 1: MCP UX Improvements (P0 — blocks commercial launch)
See `SPEC_MCP_UX_IMPROVEMENTS.md`
- Change 1: Improve all 13 tool descriptions (Claude stops inventing API keys)
- Change 2: Actionable error responses (every error has recovery path)
- Change 3: Add `spss_get_started` onboarding tool
- **Effort:** ~4 hours
- **Impact:** Users can self-serve in Claude.ai without project instructions

### Priority 2: Frontend (insightgenius-front)
- Repo created: `quack2025/insightgenius-front`
- Design assets from Stitch in `design/` folder
- V0 prompts in `DESIGN_BRIEF.md`
- Supabase project: `piclftokhzkdywupdyjo`
- **Effort:** 1-2 days with V0
- **Impact:** Self-service signup, API key management, billing

### Priority 3: Landing Page Update
- Update positioning to "Statistical Precision Guaranteed"
- Add automation section (n8n/Make/Zapier examples)
- Add "Claude analyzes. InsightGenius certifies." messaging
- **Can be done in V0 as part of Priority 2**

### Priority 4: MCP Directory Submission
- Fix SSE vs Streamable HTTP (SSE for now, document clearly)
- Unify branding (support@insightgenius.io)
- Generate dedicated QA API key for Anthropic review
- Read and check Anthropic MCP Directory Policy
- **Blocked by:** Priority 1 (MCP UX improvements)

### Priority 5: Tier 2 Features
- T2-1: Chi-square p-value per table header
- T2-2: Filters / sub-populations
- T2-3: Auto-detect nets (improved)
- T2-5: Total as first column (DONE)
- **Not blocked** — can be done in parallel

---

## Pricing (Agreed)

| Plan | Price | Calls/mo | File Size | AI | Automation |
|------|-------|----------|-----------|-----|-----------|
| **Free** | $0 | 50 | 5 MB | No | No |
| **Growth** | $29/mo | 500 | 50 MB | No | Yes |
| **Business** | $99/mo | 5,000 | 200 MB | Yes (Haiku) | Yes + Priority |
| **Enterprise** | Custom | Unlimited | 500 MB | Yes | Yes + SLA |

Margins: Growth 93%, Business 82%.

---

## Architecture

| Component | Where | Deploy |
|-----------|-------|--------|
| **API + MCP** | `quack2025/spss-insightgenius-api` | Railway (auto-deploy from master) |
| **Frontend** | `quack2025/insightgenius-front` (new) | Vercel (auto-deploy) |
| **Auth + Users** | Supabase `piclftokhzkdywupdyjo` | Managed |
| **Domain** | `spss.insightgenius.io` (API) | Railway custom domain |
| **Domain** | `insightgenius.io` or `app.insightgenius.io` (Frontend) | Vercel |
