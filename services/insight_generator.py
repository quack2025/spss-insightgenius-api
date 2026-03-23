"""Deterministic insight and content_blocks generation for MCP responses.

NO LLM calls. Pure template logic. Fast and predictable.
Used by MCP tools to generate insight_summary and content_blocks.
"""

from typing import Any


def generate_insight_summary(tool: str, results: dict[str, Any]) -> str:
    """One-paragraph insight from analysis results. Template-based, not LLM."""

    if tool == "spss_analyze_frequencies":
        parts = []
        for r in results.get("results", []):
            freqs = r.get("frequencies", [])
            var_label = r.get("label") or r.get("variable", "?")
            base = r.get("base", 0)
            if freqs:
                top = max(freqs, key=lambda x: x.get("percentage", 0))
                parts.append(
                    f"{var_label}: most common is '{top.get('label', '?')}' "
                    f"({top.get('percentage', 0):.1f}%, n={base})"
                )
        return ". ".join(parts) if parts else "Frequency analysis complete."

    elif tool == "spss_analyze_crosstab":
        ct = results.get("results", results)
        total = ct.get("total_responses", 0)
        row_var = ct.get("row_variable", "?")
        col_var = ct.get("col_variable", "?")
        chi2_p = ct.get("chi2_pvalue")
        if chi2_p is not None and chi2_p < 0.05:
            return (
                f"Significant relationship between {row_var} and {col_var} "
                f"(chi2 p={chi2_p:.4f}, n={total})."
            )
        return f"Cross-tabulation of {row_var} by {col_var} (n={total}). No significant overall relationship detected."

    elif tool == "spss_analyze_correlation":
        pairs = results.get("significant_pairs", [])
        n = results.get("n_cases", 0)
        method = results.get("method", "pearson")
        if pairs:
            strongest = max(pairs, key=lambda p: abs(p.get("r", 0)))
            return (
                f"{len(pairs)} significant correlation(s) found ({method}, n={n}). "
                f"Strongest: {strongest['var1']} x {strongest['var2']} (r={strongest['r']:.3f})."
            )
        return f"No significant correlations found ({method}, n={n})."

    elif tool == "spss_analyze_anova":
        f_stat = results.get("f_statistic", 0)
        p_val = results.get("p_value", 1)
        dep = results.get("dependent", "?")
        factor = results.get("factor", "?")
        sig = results.get("significant", False)
        if sig:
            means = results.get("group_means", {})
            if means:
                best_group = max(means, key=means.get)
                worst_group = min(means, key=means.get)
                return (
                    f"Significant difference in {dep} across {factor} groups "
                    f"(F={f_stat:.2f}, p={p_val:.4f}). "
                    f"Highest: {best_group} ({means[best_group]:.2f}), "
                    f"Lowest: {worst_group} ({means[worst_group]:.2f})."
                )
        return f"No significant difference in {dep} across {factor} groups (F={f_stat:.2f}, p={p_val:.4f})."

    elif tool == "spss_analyze_gap":
        items = results.get("items", [])
        high_priority = [i for i in items if i.get("priority") == "High"]
        if high_priority:
            top = high_priority[0]
            return (
                f"{len(high_priority)} high-priority gap(s) found. "
                f"Top: {top.get('item', '?')} (gap={top.get('gap', 0):.2f})."
            )
        return f"Gap analysis complete. {len(items)} items analyzed, no high-priority gaps."

    elif tool == "spss_summarize_satisfaction":
        summaries = results.get("summaries", [])
        if summaries:
            best = max(summaries, key=lambda s: s.get("mean") or 0)
            worst = min(summaries, key=lambda s: s.get("mean") or 999)
            return (
                f"Satisfaction summary: {len(summaries)} variables. "
                f"Highest: {best.get('variable', '?')} (mean={best.get('mean', '?')}). "
                f"Lowest: {worst.get('variable', '?')} (mean={worst.get('mean', '?')})."
            )
        return "Satisfaction summary complete."

    elif tool in ("spss_create_tabulation", "spss_auto_analyze"):
        stubs = results.get("stubs_success", results.get("total_stubs", 0))
        banners = results.get("banners", [])
        return (
            f"Tabulation complete: {stubs} tables generated across "
            f"{len(banners)} banner(s) ({', '.join(banners)})."
        )

    return "Analysis complete."


def generate_content_blocks(tool: str, results: dict[str, Any]) -> dict[str, Any]:
    """Pre-digested content for ANY presentation tool (Gamma, PPTX, Canva, Slides).

    Returns tool-agnostic content blocks: title, subtitle, key_finding,
    chart_description, data_table_markdown.
    """
    blocks: dict[str, Any] = {
        "title": "",
        "subtitle": "",
        "key_finding": "",
        "chart_description": "",
        "data_table_markdown": "",
    }

    if tool == "spss_analyze_frequencies":
        r = (results.get("results") or [{}])[0] if results.get("results") else {}
        blocks["title"] = r.get("label") or r.get("variable", "Frequency Analysis")
        blocks["subtitle"] = f"n={r.get('base', '?')}"

        freqs = r.get("frequencies", [])
        if freqs:
            top = max(freqs, key=lambda x: x.get("percentage", 0))
            blocks["key_finding"] = (
                f"'{top.get('label', '?')}' is the most common response "
                f"({top.get('percentage', 0):.1f}%)"
            )
            blocks["chart_description"] = (
                f"Bar chart with {len(freqs)} categories. "
                f"Peak at '{top.get('label', '?')}' ({top.get('percentage', 0):.1f}%)."
            )
            lines = ["| Value | % | Count |", "|---|---|---|"]
            for f in freqs[:15]:
                lines.append(f"| {f.get('label', '?')} | {f.get('percentage', 0):.1f}% | {f.get('count', 0)} |")
            blocks["data_table_markdown"] = "\n".join(lines)

    elif tool == "spss_analyze_crosstab":
        ct = results.get("results", results)
        blocks["title"] = f"{ct.get('row_variable', '?')} by {ct.get('col_variable', '?')}"
        blocks["subtitle"] = f"n={ct.get('total_responses', '?')}, sig={ct.get('significance_level', 0.95)}"
        chi2_p = ct.get("chi2_pvalue")
        if chi2_p is not None and chi2_p < 0.05:
            blocks["key_finding"] = f"Significant relationship detected (p={chi2_p:.4f})"
        else:
            blocks["key_finding"] = "No significant overall relationship"

    elif tool == "spss_analyze_correlation":
        blocks["title"] = f"Correlation Matrix ({results.get('method', 'pearson')})"
        blocks["subtitle"] = f"n={results.get('n_cases', '?')}, {len(results.get('variables', []))} variables"
        pairs = results.get("significant_pairs", [])
        if pairs:
            strongest = max(pairs, key=lambda p: abs(p.get("r", 0)))
            blocks["key_finding"] = (
                f"Strongest: {strongest['var1']} x {strongest['var2']} "
                f"(r={strongest['r']:.3f}, p={strongest['p_value']:.4f})"
            )
        # Build matrix markdown
        matrix = results.get("matrix", {})
        if matrix:
            vars_list = list(matrix.keys())
            lines = ["| | " + " | ".join(vars_list) + " |"]
            lines.append("|---|" + "|".join(["---"] * len(vars_list)) + "|")
            for v in vars_list:
                row_vals = [f"{matrix[v].get(c, '-'):.3f}" if matrix[v].get(c) else "-" for c in vars_list]
                lines.append(f"| {v} | " + " | ".join(row_vals) + " |")
            blocks["data_table_markdown"] = "\n".join(lines)

    elif tool == "spss_analyze_anova":
        blocks["title"] = f"ANOVA: {results.get('dependent', '?')} by {results.get('factor', '?')}"
        f_stat = results.get("f_statistic", 0)
        p_val = results.get("p_value", 1)
        blocks["subtitle"] = f"F={f_stat:.2f}, p={p_val:.4f}"
        if results.get("significant"):
            means = results.get("group_means", {})
            best = max(means, key=means.get) if means else "?"
            blocks["key_finding"] = f"Significant. Highest mean: {best} ({means.get(best, '?'):.2f})"
        else:
            blocks["key_finding"] = "No significant differences between groups"
        # Tukey table
        tukey = results.get("post_hoc_tukey", [])
        if tukey:
            lines = ["| Group 1 | Group 2 | Mean Diff | p-value | Sig |", "|---|---|---|---|---|"]
            for t in tukey[:10]:
                sig_mark = "Yes" if t.get("significant") else ""
                lines.append(
                    f"| {t.get('group1', '?')} | {t.get('group2', '?')} | "
                    f"{t.get('mean_diff', 0):.3f} | {t.get('p_value', 0):.4f} | {sig_mark} |"
                )
            blocks["data_table_markdown"] = "\n".join(lines)

    elif tool == "spss_analyze_gap":
        blocks["title"] = "Importance-Performance Gap Analysis"
        items = results.get("items", [])
        blocks["subtitle"] = f"{len(items)} items analyzed"
        high = [i for i in items if i.get("priority") == "High"]
        if high:
            blocks["key_finding"] = f"{len(high)} high-priority gaps requiring action"
        lines = ["| Item | Importance | Performance | Gap | Priority | Quadrant |", "|---|---|---|---|---|---|"]
        for i in items[:15]:
            lines.append(
                f"| {i.get('item', '?')} | {i.get('importance', 0):.2f} | "
                f"{i.get('performance', 0):.2f} | {i.get('gap', 0):.2f} | "
                f"{i.get('priority', '?')} | {i.get('quadrant', '?')} |"
            )
        blocks["data_table_markdown"] = "\n".join(lines)

    elif tool == "spss_summarize_satisfaction":
        summaries = results.get("summaries", [])
        blocks["title"] = "Satisfaction Summary"
        blocks["subtitle"] = f"{len(summaries)} variables"
        if summaries:
            best = max(summaries, key=lambda s: s.get("mean") or 0)
            blocks["key_finding"] = f"Highest: {best.get('variable', '?')} (mean={best.get('mean', '?')})"
        lines = ["| Variable | Mean | T2B% | B2B% |", "|---|---|---|---|"]
        for s in summaries:
            lines.append(
                f"| {s.get('label') or s.get('variable', '?')} | "
                f"{s.get('mean', '-')} | {s.get('t2b', '-')}% | {s.get('b2b', '-')}% |"
            )
        blocks["data_table_markdown"] = "\n".join(lines)

    elif tool in ("spss_create_tabulation", "spss_auto_analyze"):
        banners = results.get("banners", [])
        stubs = results.get("stubs_success", results.get("total_stubs", 0))
        blocks["title"] = results.get("title", "Tabulation Results")
        blocks["subtitle"] = f"{stubs} tables, banners: {', '.join(banners)}"
        blocks["key_finding"] = f"Complete tabulation with significance testing across {len(banners)} banner(s)"

        # Per-table slide content
        tables_summary = results.get("tables_summary", [])
        if tables_summary:
            slides = []
            slides.append({
                "title": "Methodology & Sample",
                "content": f"n={results.get('sample_size', '?')} across {', '.join(banners)}.",
            })
            for t in tables_summary[:20]:
                slides.append({
                    "title": t.get("stub_label") or t.get("stub", "?"),
                    "content": t.get("top_finding", ""),
                })
            blocks["slides"] = slides

    return blocks
