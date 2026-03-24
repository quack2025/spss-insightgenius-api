# MCP Usage Examples

## Example 1: Quick Frequency Analysis

```
User: What's the distribution of satisfaction in my survey?

→ spss_upload_file(file_base64="...", filename="survey.sav")
← {file_id: "abc123", n_cases: 1000, n_variables: 19}

→ spss_analyze_frequencies(file_id="abc123", variables=["sat_overall"])
← {
    insight_summary: "Satisfaction: most common is 'Satisfied' (35.3%, n=1000)",
    content_blocks: {
      title: "Satisfaction Distribution",
      key_finding: "'Satisfied' is the most common response (35.3%)",
      data_table_markdown: "| Value | % | Count |..."
    },
    results: [{ variable: "sat_overall", frequencies: [...], mean: 3.72, ... }]
  }
```

## Example 2: Cross-tabulation by Region

```
User: Compare satisfaction across regions with significance testing

→ spss_get_metadata(file_id="abc123")
← { suggested_banners: [{variable: "region", confidence: 0.85}], ... }

→ spss_analyze_crosstab(
    file_id="abc123",
    row="sat_overall",
    col="region",
    significance_level=0.95,
    include_means=true
  )
← {
    insight_summary: "Significant relationship (chi2 p=0.013). London leads with 68.6% T2B.",
    content_blocks: {
      title: "Satisfaction by Region",
      key_finding: "London significantly higher than Scotland (68.6% vs 50.4%)"
    },
    results: { chi2_pvalue: 0.013, table: [...] }
  }
```

## Example 3: Zero-Config Auto-Analyze

```
User: Just analyze everything in this file

→ spss_upload_file(file_base64="...", filename="haircare_study.sav")
← {file_id: "xyz789", n_cases: 493, n_variables: 291}

→ spss_auto_analyze(file_id="xyz789")
← {
    download_url: "https://spss.insightgenius.io/downloads/tmp_abc.xlsx",
    download_expires_in_seconds: 300,
    stubs_processed: 62,
    banners_used: ["CLA_EDAD"],
    tables_summary: [
      {stub: "F1", stub_label: "Género", base_total: 493, top_finding: "100% Male"},
      {stub: "F3", stub_label: "Ciudad", base_total: 493, top_finding: "Most common: 'Medellín' (21%)"},
      ...
    ],
    insight_summary: "Tabulation complete: 62 tables across 1 banner (CLA_EDAD)."
  }
```

## Example 4: Composability with Gamma (Presentation)

```
User: Create a presentation from this analysis

→ spss_create_tabulation(
    file_id="abc123",
    banners=["gender", "region"],
    stubs=["_all_"],
    include_means=true
  )
← {
    content_blocks: {
      title: "Customer Satisfaction Study — Key Findings",
      slides: [
        {title: "Methodology & Sample", content: "n=1000 across 5 regions"},
        {title: "Overall Satisfaction by Region", content: "London leads with 68.6% T2B..."},
        {title: "NPS by Gender", content: "No significant gender difference (p=0.42)"}
      ]
    }
  }

→ gamma:generate(
    title: content_blocks.slides[0].title,
    content: content_blocks.slides[0].content,
    ...
  )
```

## Example 5: ANOVA + Gap Analysis Pipeline

```
User: Is there a significant difference in satisfaction by region? And what should we prioritize?

→ spss_analyze_anova(
    file_id="abc123",
    dependent="sat_overall",
    factor="region"
  )
← {
    insight_summary: "Significant difference (F=4.50, p=0.0013). Highest: London (3.85), Lowest: Scotland (3.42).",
    results: { significant: true, post_hoc_tukey: [...] }
  }

→ spss_analyze_gap(
    file_id="abc123",
    importance_vars=["imp_speed", "imp_price", "imp_comfort"],
    performance_vars=["sat_speed", "sat_price", "sat_comfort"]
  )
← {
    insight_summary: "2 high-priority gaps found. Top: Price (gap=1.23).",
    content_blocks: {
      key_finding: "2 high-priority gaps requiring action",
      data_table_markdown: "| Item | Importance | Performance | Gap | Priority |..."
    }
  }
```

## Example 6: Batch Frequencies (50 variables at once)

```
→ spss_analyze_frequencies(
    file_id="abc123",
    variables=["sat_speed", "sat_price", "sat_comfort", "sat_safety", "sat_app", "sat_driver", "sat_overall"]
  )
← {
    variables_analyzed: ["sat_speed", "sat_price", ...],
    results: [
      { variable: "sat_speed", mean: 3.71, ... },
      { variable: "sat_price", mean: 3.75, ... },
      ...
    ],
    insight_summary: "sat_speed: most common is 'Satisfied' (35.0%). sat_price: ..."
  }
```

## Example 7: n8n/Make Automation

```
Trigger: Webhook receives .sav file
→ spss_upload_file(api_key="sk_live_...", file_base64="...", filename="weekly_tracker.sav")
→ spss_auto_analyze(api_key="sk_live_...", file_id="...")
→ GET download_url → save Excel
→ Email Excel to client
```
