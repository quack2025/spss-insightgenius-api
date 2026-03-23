"""Response formatting for MCP tools.

Wraps analysis results in the standard MCP response envelope with
insight_summary and content_blocks. Supports JSON and markdown output formats.
"""

from typing import Any

from services.insight_generator import generate_content_blocks, generate_insight_summary


def build_mcp_response(
    tool: str,
    results: dict[str, Any],
    file_id: str | None = None,
    variables_analyzed: list[str] | None = None,
    sample_size: int = 0,
    weighted: bool = False,
    format_detected: str = "sav",
    response_format: str = "json",
    download_url: str | None = None,
    download_expires: int | None = None,
    download_filename: str | None = None,
) -> dict[str, Any]:
    """Build the standard MCP response envelope.

    Every analysis tool returns this structure with insight_summary and content_blocks.
    """
    envelope: dict[str, Any] = {
        "tool": tool,
        "file_id": file_id,
        "variables_analyzed": variables_analyzed or [],
        "sample_size": sample_size,
        "weighted": weighted,
        "format_detected": format_detected,
    }

    # Add download info for Excel-producing tools
    if download_url:
        envelope["download_url"] = download_url
        envelope["download_expires_in_seconds"] = download_expires or 300
        envelope["filename"] = download_filename or "output.xlsx"

    # Results (full or markdown-formatted)
    if response_format == "markdown":
        envelope["results_markdown"] = _to_markdown(tool, results)
    else:
        envelope["results"] = results

    # Insight summary (deterministic, template-based)
    envelope["insight_summary"] = generate_insight_summary(tool, results)

    # Content blocks (tool-agnostic, for Gamma/PPTX/Canva/Slides)
    envelope["content_blocks"] = generate_content_blocks(tool, results)

    return envelope


def _to_markdown(tool: str, results: dict[str, Any]) -> str:
    """Convert results to human-readable markdown."""

    if tool == "spss_analyze_frequencies":
        parts = []
        for r in results.get("results", [results]):
            var = r.get("label") or r.get("variable", "?")
            base = r.get("base", "?")
            parts.append(f"### {var} (n={base})\n")
            freqs = r.get("frequencies", [])
            if freqs:
                parts.append("| Value | % | Count |")
                parts.append("|---|---|---|")
                for f in freqs:
                    parts.append(f"| {f.get('label', '?')} | {f.get('percentage', 0):.1f}% | {f.get('count', 0)} |")
            mean = r.get("mean")
            if mean is not None:
                parts.append(f"\nMean: {mean:.2f} | Std: {r.get('std', '?')} | Median: {r.get('median', '?')}")
            parts.append("")
        return "\n".join(parts)

    elif tool == "spss_analyze_crosstab":
        ct = results.get("results", results)
        parts = [f"### {ct.get('row_variable', '?')} x {ct.get('col_variable', '?')}"]
        parts.append(f"n={ct.get('total_responses', '?')}, sig={ct.get('significance_level', 0.95)}")
        chi2 = ct.get("chi2_pvalue")
        if chi2 is not None:
            parts.append(f"Chi-square p={chi2:.4f}")
        table = ct.get("table", [])
        if table and len(table) > 0:
            # Build from first row's keys
            first = table[0]
            cols = [k for k in first.keys() if k not in ("row_value", "row_label")]
            parts.append("\n| Row | " + " | ".join(cols) + " |")
            parts.append("|---|" + "|".join(["---"] * len(cols)) + "|")
            for row in table[:20]:
                label = row.get("row_label", row.get("row_value", "?"))
                vals = []
                for c in cols:
                    cell = row.get(c, {})
                    if isinstance(cell, dict):
                        pct = cell.get("percentage", "?")
                        sig = " ".join(cell.get("significance_letters", []))
                        vals.append(f"{pct}%{' ' + sig if sig else ''}")
                    else:
                        vals.append(str(cell))
                parts.append(f"| {label} | " + " | ".join(vals) + " |")
        return "\n".join(parts)

    elif tool == "spss_analyze_correlation":
        matrix = results.get("matrix", {})
        if not matrix:
            return "No correlation data."
        vars_list = list(matrix.keys())
        parts = [f"### Correlation Matrix ({results.get('method', 'pearson')})", f"n={results.get('n_cases', '?')}"]
        parts.append("\n| | " + " | ".join(vars_list) + " |")
        parts.append("|---|" + "|".join(["---"] * len(vars_list)) + "|")
        for v in vars_list:
            row_vals = [f"{matrix[v].get(c, 0):.3f}" if matrix[v].get(c) is not None else "-" for c in vars_list]
            parts.append(f"| {v} | " + " | ".join(row_vals) + " |")
        pairs = results.get("significant_pairs", [])
        if pairs:
            parts.append(f"\n**{len(pairs)} significant pair(s):**")
            for p in pairs[:10]:
                parts.append(f"- {p['var1']} x {p['var2']}: r={p['r']:.3f}, p={p['p_value']:.4f}")
        return "\n".join(parts)

    elif tool == "spss_analyze_anova":
        parts = [f"### ANOVA: {results.get('dependent', '?')} by {results.get('factor', '?')}"]
        parts.append(f"F={results.get('f_statistic', 0):.2f}, p={results.get('p_value', 1):.4f}, sig={results.get('significant', False)}")
        means = results.get("group_means", {})
        if means:
            parts.append("\n| Group | Mean | Std | N |")
            parts.append("|---|---|---|---|")
            ns = results.get("group_ns", {})
            stds = results.get("group_stds", {})
            for g, m in means.items():
                parts.append(f"| {g} | {m:.2f} | {stds.get(g, '?')} | {ns.get(g, '?')} |")
        return "\n".join(parts)

    elif tool == "spss_summarize_satisfaction":
        summaries = results.get("summaries", [])
        parts = ["### Satisfaction Summary"]
        parts.append("| Variable | Mean | T2B% | B2B% |")
        parts.append("|---|---|---|---|")
        for s in summaries:
            parts.append(f"| {s.get('label') or s.get('variable', '?')} | {s.get('mean', '-')} | {s.get('t2b', '-')}% | {s.get('b2b', '-')}% |")
        return "\n".join(parts)

    # Default: return JSON as formatted string
    import json
    return f"```json\n{json.dumps(results, indent=2, default=str)[:5000]}\n```"
