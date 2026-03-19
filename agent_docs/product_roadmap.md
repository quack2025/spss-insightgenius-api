# SPSS InsightGenius API — Product Roadmap

> Last updated: 2026-03-19

## Vision

Replace PSPP/WinCross/Quantum for 80% of market research tabulation use cases with a modern REST API + embedded UI. The product IS the API — the frontend is a convenience wrapper for testing and demos.

---

## Current State (Sprint 2 — Mar 19 2026)

### What Works

| Feature | Status |
|---------|--------|
| SPSS .sav upload + metadata extraction | Production |
| Auto-detect question types (QuantipyMRX) | Production |
| Frequency tables (weighted/unweighted) | Production |
| Single crosstab with sig letters (A/B/C) | Production |
| Full tabulation → Excel (`/v1/tabulate`) | Production |
| Nets in Excel (Top 2 Box, Bottom 2 Box) | Production |
| Weight support (Kish effective-n) | Production |
| Format conversion (.sav → xlsx/csv/dta/parquet) | Production |
| Reporting Ticket .docx parsing (Haiku) | Production |
| Smart label suggestions (Haiku) | Production |
| API key auth + per-plan rate limiting | Production |
| Usage logging for billing | Production |
| Embedded web UI (drag & drop) | Production |
| 29 automated tests | Production |

### What's Missing (by tier)

## Tier 1 — Table Stakes (without these, can't replace PSPP)

### T1-1: Means with Significance Testing
**Priority: P0 — CRITICAL**

Add a row of Mean / Std Dev / Median per banner column at the bottom of each crosstab sheet. T-test between pairs of columns, with significance letters (same A/B/C notation).

**User story**: "I need to see that average satisfaction in London (4.2A) is significantly higher than Scotland (3.1), not just the percentage breakdown."

**Implementation**:
- Add `include_means: true` to TabulateSpec
- For each stub that's numeric (scale), compute weighted/unweighted mean per banner column
- Independent samples T-test between each pair of columns
- Display: `Mean: 4.2 BC` (significantly higher than columns B and C)
- Add Std Dev, Median, N rows below

**Affected files**: `services/tabulation_builder.py`, `services/quantipy_engine.py` (new `compare_means_by_group` method), `routers/tabulate.py`

---

### T1-2: Multiple Banners (Side-by-Side)
**Priority: P0 — CRITICAL**

Allow `banners: ["gender", "region", "age_group"]` in a single tabulation. Columns appear side-by-side with continuous letter assignment (A/B for gender, C/D/E/F/G for region, H/I/J for age).

**User story**: "In every tabulation house, the standard deliverable is a table with Total + Gender + Region + Age as banner columns. I need all demographics in one table, not separate files."

**Implementation**:
- Change spec: `banner` (string) → `banners` (string[]), keep `banner` as alias for backwards compat
- Assign letters continuously across all banners: Total=no letter, Gender A/B, Region C/D/E/F/G, Age H/I/J
- Group headers in Excel: merge cells for each banner label above the column value labels
- Sig testing: test within each banner group only (A vs B within Gender, C vs D vs E within Region — never A vs C)

**Affected files**: `services/tabulation_builder.py` (major refactor), `services/quantipy_engine.py` (new `multi_banner_crosstab`), `routers/tabulate.py`

---

### T1-3: Multiple Response Sets (MRS)
**Priority: P0 — CRITICAL**

Group binary variables (Q5_1, Q5_2, Q5_3) as a single "select all that apply" question. Show each option as a row, with % = count / base (not 100% total).

**User story**: "Q5 is 'Which brands do you know?' with 6 binary columns. I need one table showing all 6 brands as rows, with % aware in each demographic column. The percentages should add up to MORE than 100% because people can select multiple brands."

**Implementation**:
- Add `mrs_groups` to spec: `{"Q5_awareness": ["Q5_1", "Q5_2", "Q5_3", "Q5_4", "Q5_5", "Q5_6"]}`
- Auto-detect MRS groups from variable name prefix (Q5_1..Q5_6)
- Each member variable becomes a row; base = total respondents (not sum of responses)
- Sig testing: z-test on proportions per cell (same as regular crosstab)

**Affected files**: `services/quantipy_engine.py` (new `mrs_crosstab` method), `services/tabulation_builder.py`, `routers/tabulate.py`

---

### T1-4: Dual Bases (Weighted + Unweighted)
**Priority: P1 — HIGH**

When weight is applied, show both weighted base and unweighted N in the table header.

**User story**: "Clients always want to see both: 'Base (weighted): 354' and 'Base (unweighted): 320'. The weighted base shows the effective sample, but the unweighted N tells them how many actual interviews were conducted."

**Implementation**:
- Add row "Base (unweighted)" below "Base (N)" when weight is specified
- Unweighted = simple count, Weighted = sum of weights

**Affected files**: `services/tabulation_builder.py` (add row)

---

## Tier 2 — Differentiators (win against competition)

### T2-1: Chi-Square Test per Table
**Priority: P1**

Global significance test per table: "Is there a statistically significant relationship between satisfaction and region?" (p-value for the entire table, not per cell).

**Implementation**: `scipy.stats.chi2_contingency()` on the raw crosstab matrix. Display p-value in the sheet header.

---

### T2-2: Filters / Sub-populations
**Priority: P1**

Apply filter conditions before running crosstabs: "Only respondents who are aware of the brand (Q5_1 == 1)" or "Only females aged 25-34".

**Implementation**: Add `filters` to spec: `[{"variable": "Q5_1", "operator": "eq", "value": 1}]`. Apply to DataFrame before crosstab.

---

### T2-3: Auto-Detect Nets
**Priority: P2**

Automatically detect Likert scales (5pt, 7pt, 10pt) and generate Top 2 Box / Bottom 2 Box nets without manual `nets` definition.

**Implementation**: In `auto_planner.py`, detect value label patterns ("Very dissatisfied"..."Very satisfied") and infer scale endpoints.

---

### T2-4: Row % + Count Display Options
**Priority: P2**

Currently only shows column %. Add options for:
- Row percentages (% of row total)
- Counts only
- Both counts and %
- Column % + counts in same cell

**Implementation**: Add `display_mode` to spec: `"col_pct"` (default), `"row_pct"`, `"count"`, `"col_pct_and_count"`

---

### T2-5: Total Column with Sig Testing
**Priority: P2**

Add a "Total" column (all respondents) as the first column before banner breaks. Often used as reference point.

**Implementation**: Add Total as a virtual banner column with all cases. Assign it a letter or leave it unlettered.

---

## Tier 3 — Premium / AI-Powered

### T3-1: Reporting Ticket → Excel (Zero Config)
Upload .sav + .docx → Haiku parses ticket → auto-generates complete tabulation Excel. No manual banner/stub selection needed.

### T3-2: Smart Banner Detection
Haiku analyzes variables and suggests which are good banner candidates (demographics with 2-8 categories, high fill rate).

### T3-3: Executive Summary Generation
Haiku reads the tabulation results and generates a 1-page executive summary of key findings, significant differences, and recommendations.

### T3-4: PowerPoint Export
Generate presentation slides from tabulation results (via python-pptx or Gamma API). Each slide = one table formatted for projection.

### T3-5: Wave/Tracking Comparison
Compare results across time periods (Q1 vs Q2) with significance testing on the differences. Show arrows (↑↓) for directional changes.

### T3-6: Banner Nesting
Nested banners: "Gender within Region" (Male London, Female London, Male Manchester...). Common in large tracking studies.

### T3-7: Open-End Coding Integration
Connect to Survey Coder Pro API for auto-coding open-ended responses, then include coded results as crosstab rows.

---

## Sprint Plan

### Sprint 3: Tier 1 Complete (target: next session)
1. **T1-1**: Means row with T-test sig letters in Excel
2. **T1-2**: Multiple banners side-by-side with grouped headers
3. **T1-3**: MRS groups as crosstab rows
4. **T1-4**: Dual bases (weighted + unweighted)

### Sprint 4: Tier 2 Core
1. **T2-1**: Chi-square p-value per table
2. **T2-2**: Filters
3. **T2-3**: Auto-detect nets

### Sprint 5: AI Integration
1. **T3-1**: Reporting Ticket → Excel (end-to-end)
2. **T3-2**: Smart banner detection
3. **T3-3**: Executive summary

---

## Competitive Landscape

| Feature | PSPP | WinCross | Quantum | **InsightGenius** |
|---------|------|----------|---------|-------------------|
| REST API | No | No | No | **Yes** |
| Crosstab + sig letters | Yes | Yes | Yes | **Yes** |
| Means + T-test | Yes | Yes | Yes | Sprint 3 |
| Multiple banners | Yes | Yes | Yes | Sprint 3 |
| MRS | Yes | Yes | Yes | Sprint 3 |
| AI ticket parsing | No | No | No | **Yes** |
| Web UI | No | No | No | **Yes** |
| Excel export | Yes | Yes | Yes | **Yes** |
| Auto-detect types | No | No | Limited | **Yes** |
| Per-request pricing | No | License | License | **Yes** |
| Cloud / no install | No | No | No | **Yes** |

**Key differentiator**: InsightGenius is the only cloud-native, API-first tabulation engine with AI-powered features. Legacy tools require desktop licenses and manual configuration.
