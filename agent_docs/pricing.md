# SPSS InsightGenius API — Pricing

> Last updated: 2026-03-19

## Plans

| | **Starter** | **Pro** | **Business** | **Enterprise** |
|---|---|---|---|---|
| **Price** | Free | $99/mo | $299/mo | Custom |
| **API calls/month** | 100 | 2,000 | 10,000 | Unlimited |
| **Rate limit** | 10/min | 60/min | 200/min | Custom |
| **Max file size** | 5 MB | 50 MB | 200 MB | 500 MB |
| **Max variables** | 50 | Unlimited | Unlimited | Unlimited |
| **Tabulate endpoint** | 5 stubs max | Unlimited | Unlimited | Unlimited |
| **Multiple banners** | 1 banner | Up to 5 | Up to 10 | Unlimited |
| **Custom groups** | No | Up to 3 | Up to 10 | Unlimited |
| **MRS groups** | No | Yes | Yes | Yes |
| **Grid/Battery** | No | Yes | Yes | Yes |
| **Single-sheet mode** | No | Yes | Yes | Yes |
| **Significance testing** | 95% only | 90/95/99% | 90/95/99% | 90/95/99% |
| **Weighted analysis** | No | Yes | Yes | Yes |
| **Means + T-test** | No | Yes | Yes | Yes |
| **AI ticket parsing** | No | No | Yes | Yes |
| **AI smart labeling** | No | No | Yes | Yes |
| **Format conversion** | CSV only | All formats | All formats | All formats |
| **Support** | Community | Email (48h) | Email (24h) + Slack | Dedicated + SLA |
| **API key type** | `sk_test_` | `sk_live_` | `sk_live_` | `sk_live_` |

## Per-Request Pricing (alternative to subscription)

For clients who prefer pay-as-you-go:

| Endpoint | Cost per request |
|----------|-----------------|
| `/v1/metadata` | $0.01 |
| `/v1/frequency` | $0.02 |
| `/v1/crosstab` | $0.05 |
| `/v1/tabulate` | $0.10 + $0.02 per stub |
| `/v1/process` | $0.10 + $0.02 per operation |
| `/v1/convert` | $0.05 |
| `/v1/parse-ticket` | $0.25 (includes Haiku AI cost) |

Example: Tabulate 17 stubs × 3 banners = $0.10 + (17 × $0.02) = $0.44 per run

## Competitive Pricing Context

| Competitor | Model | Cost |
|-----------|-------|------|
| PSPP (open source) | Free | $0 but manual, no API, desktop only |
| WinCross | Annual license | ~$3,000-5,000/year per seat |
| Quantum | Enterprise license | ~$10,000-25,000/year |
| SPSS Statistics | Subscription | ~$99/mo per user (desktop) |
| Q Research | Annual license | ~$2,500-5,000/year |
| **InsightGenius API** | **SaaS / Pay-as-you-go** | **$99-299/mo or per-request** |

**Key differentiator**: No desktop install, no annual license, API-first, cloud-native, AI-powered ticket parsing. A single API call does what takes 30 minutes in PSPP.

## Revenue Model

### Phase 1: Direct API Sales (current)
- Self-serve signup at `spss.insightgenius.io`
- API key provisioned immediately
- Stripe billing (monthly subscription or per-request metered)

### Phase 2: Platform Integrations
- **Survey platforms** (Qualtrics, SurveyMonkey, Typeform) — embedded tabulation
- **BI tools** (Tableau, Power BI) — connector for live cross-tabs
- **Research agencies** — white-label API for their own platforms

### Phase 3: Enterprise
- On-premise deployment option
- SSO/SAML authentication
- Custom SLA with 99.9% uptime guarantee
- Dedicated infrastructure (isolated Railway instance)

## Margin Analysis

| Cost Component | Per tabulate request |
|---------------|---------------------|
| Railway compute (~512MB, ~200ms) | ~$0.0003 |
| Haiku AI (if ticket parsing) | ~$0.002 |
| Bandwidth (10-50KB response) | ~$0.00001 |
| **Total marginal cost** | **~$0.003** |
| **Pro plan price** | **~$0.05/request** (at 2,000 calls/mo) |
| **Gross margin** | **~94%** |

## Implementation Status

| Feature | Status | Notes |
|---------|--------|-------|
| API key auth | Live | SHA256 hashes, no DB needed |
| Rate limiting | Live | In-memory sliding window, per-plan |
| Usage logging | Live | `[USAGE]` logs in Railway, per-key/endpoint |
| Stripe integration | Pending | Need webhook for key provisioning |
| Self-serve signup | Pending | Need registration page + Stripe checkout |
| Usage dashboard | Pending | `GET /v1/usage` provides raw data |
| Metered billing | Pending | Railway logs → aggregate → Stripe metered |
