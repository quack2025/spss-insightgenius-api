# QuantiPro API

REST API for processing SPSS (.sav) files. Powered by QuantipyMRX for market research analysis.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: set API_KEYS_JSON and ANTHROPIC_API_KEY

# 3. Run
python main.py
# → http://localhost:8000/docs
```

## Generate an API Key

```python
import hashlib
key = "sk_test_my_dev_key_123"
print(hashlib.sha256(key.encode()).hexdigest())
```

Add the hash to `API_KEYS_JSON` in `.env`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/health` | Health check |
| POST | `/v1/metadata` | Extract variable metadata |
| POST | `/v1/frequency` | Frequency table |
| POST | `/v1/crosstab` | Crosstab with significance letters |
| POST | `/v1/convert` | Convert .sav to xlsx/csv/dta/parquet |
| POST | `/v1/parse-ticket` | Parse Reporting Ticket via Haiku |
| POST | `/v1/process` | Full pipeline |

## Example: Frequency

```bash
curl -X POST http://localhost:8000/v1/frequency \
  -H "Authorization: Bearer sk_test_my_dev_key_123" \
  -F "file=@survey.sav" \
  -F "variable=Q1"
```

## Example: Crosstab with Significance

```bash
curl -X POST http://localhost:8000/v1/crosstab \
  -H "Authorization: Bearer sk_test_my_dev_key_123" \
  -F "file=@survey.sav" \
  -F 'spec={"row": "Q1", "col": "gender", "significance_level": 0.95}'
```

## Example: Full Processing

```bash
curl -X POST http://localhost:8000/v1/process \
  -H "Authorization: Bearer sk_test_my_dev_key_123" \
  -F "file=@survey.sav" \
  -F 'operations=[{"type":"frequency","variable":"Q1"},{"type":"crosstab","variable":"Q1","cross_variable":"gender"}]'
```

## Deploy to Railway

```bash
railway up
```

Environment variables needed:
- `API_KEYS_JSON` — JSON array of key configs
- `ANTHROPIC_API_KEY` — For Haiku features (optional)
