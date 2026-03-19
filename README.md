# SPSS InsightGenius API

**Professional SPSS processing API for market research.** Upload .sav files, get crosstabs with significance testing, auto-detected question types, and publication-ready Excel exports.

**Live**: [spss.insightgenius.io](https://spss.insightgenius.io) | **API Docs**: [spss.insightgenius.io/docs](https://spss.insightgenius.io/docs)

---

## Quick Start

### Option 1: Web UI (no code needed)

1. Open [spss.insightgenius.io](https://spss.insightgenius.io)
2. Drag & drop your `.sav` file
3. Select a banner variable (e.g., Gender, Region)
4. Check Top 2 Box / Means options
5. Click **Generate Excel** → download your tabulation

### Option 2: curl

```bash
curl -X POST https://spss.insightgenius.io/v1/tabulate \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@survey.sav" \
  -F 'spec={"banner":"region","stubs":["_all_"],"significance_level":0.95}' \
  -o tabulation.xlsx
```

### Option 3: Python

```python
import requests, json

resp = requests.post(
    "https://spss.insightgenius.io/v1/tabulate",
    headers={"Authorization": "Bearer YOUR_API_KEY"},
    files={"file": open("survey.sav", "rb")},
    data={"spec": json.dumps({
        "banner": "region",
        "stubs": ["_all_"],
        "significance_level": 0.95,
        "nets": {
            "sat_overall": {"Top 2 Box": [4, 5], "Bottom 2 Box": [1, 2]}
        }
    })}
)

with open("tabulation.xlsx", "wb") as f:
    f.write(resp.content)
print(f"Done: {resp.headers['X-Stubs-Success']} tables generated")
```

---

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| **POST** | `/v1/tabulate` | **Full tabulation → Excel** with sig letters, nets, bases |
| POST | `/v1/metadata` | Variable names, labels, types, auto-detect |
| POST | `/v1/frequency` | Frequency table (counts + %) |
| POST | `/v1/crosstab` | Single crosstab with significance letters (A/B/C) |
| POST | `/v1/process` | Multi-operation pipeline (auto-detect or manual) |
| POST | `/v1/convert` | Convert .sav → xlsx, csv, parquet, dta |
| POST | `/v1/parse-ticket` | Parse Reporting Ticket .docx → tab plan (AI) |
| GET | `/v1/health` | Health check |
| GET | `/v1/usage` | Usage stats for your API key |

---

## POST /v1/tabulate — Full Tabulation

The core endpoint. Upload `.sav` + spec → professional Excel workbook.

### Spec Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `banner` | string | *required* | Demographic to cross by |
| `stubs` | string[] | `["_all_"]` | Questions to analyze (`_all_` = auto-select) |
| `significance_level` | float | `0.95` | 0.90, 0.95, or 0.99 |
| `weight` | string | `null` | Weight variable name |
| `nets` | object | `null` | Per-variable net definitions (see below) |
| `title` | string | `""` | Report title |

### Nets

```json
{
  "nets": {
    "satisfaction": {
      "Top 2 Box": [4, 5],
      "Bottom 2 Box": [1, 2]
    }
  }
}
```

### Excel Output

- **Summary sheet**: file info, column legend (A=London, B=South East...), stub index
- **One sheet per stub**: headers → letters → base (N) → data with `pct% SIG_LETTERS` → nets
- Significance letters in red (e.g., `60.0% C` = sig higher than column C)
- Nets in green rows

### Response Headers

```
X-Stubs-Total: 17
X-Stubs-Success: 17
X-Stubs-Failed: 0
X-Processing-Time-Ms: 359
```

---

## Significance Testing

Column proportion z-test with letter notation (A/B/C):
- Each column gets a letter (A, B, C...)
- Each cell tested vs every other column
- Significantly higher → other column's letter appears
- Supports weighted (Kish effective-n) and unweighted
- Confidence levels: 90%, 95%, 99%

---

## Authentication

All endpoints require: `Authorization: Bearer sk_live_...` or `sk_test_...`

### Rate Limits

| Plan | Requests/min | Max file size |
|------|-------------|---------------|
| Free | 10 | 5 MB |
| Pro | 60 | 50 MB |
| Business | 200 | 200 MB |

### Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `UNAUTHORIZED` | 401 | Missing/invalid API key |
| `FORBIDDEN` | 403 | Valid key, wrong scope |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `INVALID_FILE_FORMAT` | 400 | Not a .sav file |
| `FILE_TOO_LARGE` | 413 | Exceeds plan limit |
| `VARIABLE_NOT_FOUND` | 400 | Variable doesn't exist |
| `PROCESSING_FAILED` | 500 | Engine error |

---

## Local Development

```bash
git clone https://github.com/quack2025/spss-insightgenius-api.git
cd spss-insightgenius-api
pip install -r requirements.txt
cp .env.example .env  # Edit with your API key hash
python main.py        # → http://localhost:8000
python -m pytest tests/ -v  # 29 tests
```

## Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Pydantic v2 |
| Engine | QuantipyMRX (crosstab, sig testing, auto-detect) |
| AI | Claude Haiku (ticket parsing, smart labels) |
| Auth | API keys (SHA256, no DB) |
| Deploy | Railway (Docker, auto-deploy) |

Built by [Genius Labs](https://github.com/quack2025).
