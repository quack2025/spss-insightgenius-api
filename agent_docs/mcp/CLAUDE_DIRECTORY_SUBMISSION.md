# Talk2Data InsightGenius — Claude Connectors Directory Submission

**Submission form:** https://docs.google.com/forms/d/e/1FAIpQLSeafJF2NDI7oYx1r8o0ycivCSVLNq92Mpc1FPxMKSw1CzDkqA/viewform
**Directory policy:** https://support.claude.com/en/articles/11697096-anthropic-mcp-directory-policy
**Directory terms:** https://support.claude.com/en/articles/11697081-anthropic-mcp-directory-terms-and-conditions

---

## Form Fields — Copy-Paste Ready

### Server Name
```
Talk2Data InsightGenius
```

### Server URL (SSE endpoint)
```
https://spss.insightgenius.io/mcp/sse
```

### Brief Description (1-2 sentences)
```
Professional SPSS data processing and market research analysis MCP server. Upload survey data files (.sav, .csv, .xlsx), get crosstabs with significance testing, auto-detected question types, correlation, ANOVA, gap analysis, and publication-ready Excel exports — all through natural conversation with Claude.
```

### Detailed Description
```
Talk2Data InsightGenius lets market researchers analyze survey data by talking to Claude instead of wrestling with desktop software. Upload an SPSS (.sav), CSV, or Excel file once and run unlimited analyses through 13 specialized tools.

What it does:
- Frequency tables with mean, standard deviation, and median
- Cross-tabulations with column proportion z-test significance letters (A/B/C notation)
- Correlation matrices (Pearson, Spearman, Kendall) with p-values
- One-way ANOVA with Tukey HSD post-hoc comparisons
- Importance-Performance gap analysis with quadrant classification
- Satisfaction summaries (Top 2 Box / Bottom 2 Box / Mean)
- Zero-config auto-analyze: AI detects banners, groups MRS/Grid variables, applies nets, generates complete Excel
- Professional Excel tabulation export with significance letters, nets, means, MRS groups, and Grid/Battery summaries

Every response includes structured content_blocks (title, key_finding, data_table_markdown) designed for composability — pipe results directly to Gamma, PowerPoint, Canva, or any presentation tool.

File sessions: upload once, analyze many times. No re-uploading 50MB files on every query. 30-minute sliding TTL.
```

### Features List
```
- Upload once, analyze unlimited: File sessions with 30-min sliding TTL (Redis-backed)
- 13 analysis tools: frequencies, crosstabs, correlation, ANOVA, gap analysis, satisfaction summary, auto-analyze, tabulation, export, metadata, variable profiling
- Multi-format: .sav (SPSS), .csv, .tsv, .xlsx, .xls with auto-detection
- Significance testing: Column proportion z-test at 90/95/99% confidence with letter notation
- Zero-config auto-analyze: Upload a file, get complete Excel with AI-detected banners, MRS groups, grids, and nets
- Composable responses: content_blocks in every response for direct use with Gamma, PowerPoint, Canva, or any presentation tool
- Professional Excel output: Publication-ready workbooks with significance letters, dual bases, nets, means, MRS, and Grid summaries
- Download URLs: Temporary 5-minute links for Excel files (n8n/Make compatible)
- Batch analysis: Analyze up to 50 variables in a single frequency call
```

### Authentication Type
```
API Key (passed as api_key parameter in each tool call)
```

### Authentication Details
```
API keys in format sk_test_... or sk_live_... passed as the api_key parameter in each tool call. The SSE transport does not use Authorization headers — instead, every tool accepts api_key as a required parameter. Keys are SHA256-hashed server-side — raw keys are never stored. Users obtain keys at https://spss.insightgenius.io
```

### Test Credentials (for Anthropic QA team)
```
API Key: sk_test_2a441a40c84ba0afe73efd47d6bb1066aac82ad5453360f3
Plan: Pro (60 requests/min, 50MB max file)
Scopes: All (metadata, frequency, crosstab, process, convert, parse_ticket)

SSE endpoint: https://spss.insightgenius.io/mcp/sse
Health check: https://spss.insightgenius.io/v1/health

To test with MCP Inspector:
  npx @anthropic-ai/mcp-inspector https://spss.insightgenius.io/mcp/sse

The server accepts CSV and Excel files for testing without SPSS software.
A simple test: call spss_get_server_info with api_key to verify connectivity.
```

### Connection Instructions (for Claude Desktop / Claude.ai)
```json
{
  "mcpServers": {
    "talk2data_insightgenius": {
      "url": "https://spss.insightgenius.io/mcp/sse"
    }
  }
}
```

Note: This server uses SSE transport. The api_key is passed as a parameter in each tool call, not as a connection header.

For Claude Code:
```bash
claude mcp add --transport sse talk2data_insightgenius https://spss.insightgenius.io/mcp/sse
```

### Tools List (13 tools)
```
1. spss_upload_file — Upload .sav/.csv/.xlsx file, get reusable file_id (30-min session)
2. spss_get_metadata — Variable metadata + AI-detected banners, groups, nets
3. spss_describe_variable — Deep single-variable profile: distribution, labels, missing
4. spss_get_server_info — Engine status, available tools, plan limits
5. spss_analyze_frequencies — Frequency tables (batch 1-50 variables)
6. spss_analyze_crosstab — Cross-tabulation with significance letters (A/B/C) + chi-square
7. spss_analyze_correlation — Correlation matrix (Pearson/Spearman/Kendall) with p-values
8. spss_analyze_anova — One-way ANOVA with Tukey HSD post-hoc comparisons
9. spss_analyze_gap — Importance-Performance gap analysis with quadrants
10. spss_summarize_satisfaction — Compact T2B/B2B/Mean summary for scale variables
11. spss_auto_analyze — Zero-config: upload file, get complete Excel with AI-detected analysis
12. spss_create_tabulation — Full professional Excel tabulation with sig, nets, means, MRS, grids
13. spss_export_data — Convert file to xlsx/csv/parquet/dta
```

---

## Required: Minimum 3 Working Examples

### Example 1: Quick Frequency Analysis
```
User: "I have a customer satisfaction survey. What's the distribution of overall satisfaction?"

Claude calls: spss_upload_file(api_key="sk_test_...", file_base64="[base64 of survey.sav]", filename="survey.sav")
→ Returns: {file_id: "abc123", n_cases: 1000, n_variables: 19}

Claude calls: spss_analyze_frequencies(api_key="sk_test_...", file_id="abc123", variables=["sat_overall"])
→ Returns: {
    insight_summary: "Overall satisfaction: most common is 'Satisfied' (35.3%, n=1000)",
    content_blocks: {
      title: "Satisfaction Distribution",
      key_finding: "'Satisfied' is the most common response (35.3%)",
      data_table_markdown: "| Rating | % | Count |\n|---|---|---|\n| Very satisfied | 34.2% | 342 |..."
    },
    results: [{ variable: "sat_overall", frequencies: [...], mean: 3.72 }]
  }

Claude responds: "Your satisfaction data shows a positive skew — 35.3% of respondents are 'Satisfied' and 34.2% are 'Very satisfied', giving you a combined Top 2 Box of 69.5%. The mean satisfaction score is 3.72 on the 5-point scale."
```

### Example 2: Cross-tabulation with Significance Testing
```
User: "Compare satisfaction across regions. Are there significant differences?"

Claude calls: spss_get_metadata(api_key="sk_test_...", file_id="abc123")
→ Identifies region as a suggested banner variable

Claude calls: spss_analyze_crosstab(api_key="sk_test_...", file_id="abc123", row="sat_overall", col="region", significance_level=0.95, include_means=true)
→ Returns: {
    insight_summary: "Significant relationship (chi2 p=0.013). London leads with 68.6% T2B.",
    content_blocks: {
      title: "Satisfaction by Region",
      key_finding: "London significantly higher than Scotland (68.6% vs 50.4%)",
      data_table_markdown: "| | London (A) n=198 | Scotland (B) n=212 | Wales (C) n=386 |\n|---|---|---|---|\n| Very satisfied | 45.2% BC | 31.1% | 28.8% |..."
    },
    results: { chi2_pvalue: 0.013, table: [...], means: {...} }
  }

Claude responds: "There are significant regional differences in satisfaction (chi-square p=0.013). London leads with 68.6% Top 2 Box — significantly higher than both Scotland (50.4%) and Wales (53.2%). The mean satisfaction in London (4.2) is also significantly above the other regions."
```

### Example 3: Zero-Config Auto-Analyze with Excel Export
```
User: "Just analyze everything in this file and give me the Excel."

Claude calls: spss_upload_file(api_key="sk_test_...", file_base64="[base64 of haircare_study.sav]", filename="haircare_study.sav")
→ Returns: {file_id: "xyz789", n_cases: 493, n_variables: 291}

Claude calls: spss_auto_analyze(api_key="sk_test_...", file_id="xyz789")
→ Returns: {
    download_url: "https://spss.insightgenius.io/downloads/tmp_abc.xlsx",
    download_expires_in_seconds: 300,
    stubs_processed: 62,
    banners_used: ["age_group"],
    tables_summary: [
      {stub: "F1", stub_label: "Gender", base_total: 493, top_finding: "100% Male"},
      {stub: "Q1", stub_label: "Overall Satisfaction", base_total: 493, top_finding: "T2B 72%"}
    ],
    insight_summary: "Tabulation complete: 62 tables across 1 banner (age_group).",
    content_blocks: {
      slides: [
        {title: "Methodology", content: "n=493, banner: age_group"},
        {title: "Overall Satisfaction", content: "72% Top 2 Box..."}
      ]
    }
  }

Claude responds: "Done! I auto-detected age_group as the best banner and generated 62 crosstab tables with significance testing. Here's the download link for your Excel (valid for 5 minutes): [link]. Key finding: Overall satisfaction T2B is 72%."
```

---

## Privacy Policy URL
```
https://spss.insightgenius.io/privacy
```

## Documentation URL
```
https://spss.insightgenius.io/docs/mcp
```

## Support Contact
```
support@surveycoder.io
```

## Company / Vendor
```
Genius Labs
https://spss.insightgenius.io
```

## Categories / Tags
```
data-analysis, market-research, spss, survey-data, crosstabs, significance-testing, excel, tabulation
```

---

## Pre-Submission Checklist

- [x] Privacy policy page is live at https://spss.insightgenius.io/privacy
- [x] MCP docs page is live at https://spss.insightgenius.io/docs/mcp
- [x] SSE endpoint responds: `curl -s https://spss.insightgenius.io/mcp/sse` → 200 OK text/event-stream
- [x] Test key works — verified via MCP Inspector (13 tools loaded, tool calls return results)
- [x] Health check returns OK: `curl https://spss.insightgenius.io/v1/health`
- [x] server.json in repo root with SSE transport URL
- [x] Tool annotations on all 13 tools (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
- [x] SSE stream delivers responses end-to-end (initialize → tools/list → tools/call)
- [ ] Reviewed Anthropic MCP Directory Policy
- [ ] Reviewed Anthropic MCP Directory Terms
- [ ] Submitted form

---

## Parallel Submissions (same week)

### Smithery.ai
Submit at: https://smithery.ai/submit
Use the same description and examples above.

### Glama.ai
Submit at: https://glama.ai/mcp/servers/submit
Use the same description and examples.

### awesome-mcp-servers (GitHub PR)
Repo: https://github.com/punkpeye/awesome-mcp-servers
Add under "Data Analysis" category:
```markdown
- [Talk2Data InsightGenius](https://spss.insightgenius.io) 🐍 ☁️ - Professional SPSS processing: crosstabs with significance testing, auto-detect, zero-config analysis, Excel export. Upload .sav/.csv/.xlsx, get publication-ready market research deliverables.
```

### MCP.so
Submit at: https://mcp.so/submit
Use the same description.

### PulseMCP
Submit at: https://pulsemcp.com/submit
Use the same description.
