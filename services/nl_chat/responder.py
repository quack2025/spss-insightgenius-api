"""Response Builder — converts analysis results to NL answer + chart specs.

Uses Claude to translate verified statistical results into natural language.
Charts are Recharts-compatible JSON specs for the frontend.
"""

import json
import logging
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)


async def build_response(
    question: str,
    analysis_results: list[dict[str, Any]],
    language: str = "en",
) -> dict[str, Any]:
    """Build the complete query response: NL answer + charts + metadata.

    Args:
        question: Original user question
        analysis_results: Results from executor
        language: "en" or "es"

    Returns:
        Dict with: answer, analyses, charts, variables_used, python_code, warnings
    """
    # Filter successful results
    successful = [r for r in analysis_results if r.get("success")]
    failed = [r for r in analysis_results if not r.get("success")]

    # Collect all warnings
    all_warnings = []
    for r in analysis_results:
        all_warnings.extend(r.get("warnings", []))
    for r in failed:
        all_warnings.append(f"Analysis {r.get('type')} failed: {r.get('error')}")

    # Build charts
    charts = []
    for r in successful:
        chart = _build_chart(r)
        if chart:
            charts.append(chart)

    # Collect variables used
    variables_used = set()
    for r in analysis_results:
        if r.get("variable"):
            variables_used.add(r["variable"])
        if r.get("cross_variable"):
            variables_used.add(r["cross_variable"])

    # Generate NL answer
    answer = await _translate_results(question, successful, language)

    # Generate Python code
    python_code = _generate_python_code(successful)

    # Build analysis summaries for the response
    analyses = []
    for r in successful:
        analyses.append({
            "type": r["type"],
            "variable": r.get("variable"),
            "cross_variable": r.get("cross_variable"),
            "success": True,
            "result": r.get("result"),
            "chart": _build_chart(r),
        })
    for r in failed:
        analyses.append({
            "type": r["type"],
            "variable": r.get("variable"),
            "success": False,
            "error": r.get("error"),
        })

    return {
        "answer": answer,
        "analyses": analyses,
        "variables_used": sorted(variables_used),
        "python_code": python_code,
        "warnings": all_warnings,
    }


async def _translate_results(
    question: str,
    results: list[dict[str, Any]],
    language: str,
) -> str:
    """Use Claude to translate analysis results into natural language."""
    settings = get_settings()

    if not results:
        return "No se pudieron ejecutar los análisis solicitados." if language == "es" else "Could not execute the requested analyses."

    if not settings.anthropic_api_key:
        return _fallback_summary(results, language)

    # Build a summary of results for Claude
    results_summary = []
    for r in results[:5]:  # Limit to 5 analyses
        summary = {"type": r["type"], "variable": r.get("variable")}
        result_data = r.get("result", {})

        # Extract key numbers for the LLM
        if r["type"] == "frequency":
            rows = result_data.get("frequencies", result_data.get("rows", []))[:10]
            summary["data"] = rows
            summary["total"] = result_data.get("total_responses", result_data.get("base"))
        elif r["type"] in ("crosstab", "crosstab_with_significance"):
            summary["total"] = result_data.get("total_responses")
            summary["n_rows"] = len(result_data.get("table", []))
            summary["n_cols"] = len(result_data.get("col_labels", {}))
        elif r["type"] == "nps":
            summary["nps_score"] = result_data.get("nps_score")
            summary["promoters_pct"] = result_data.get("promoters_pct")
            summary["detractors_pct"] = result_data.get("detractors_pct")
        elif r["type"] == "descriptive":
            summary["mean"] = result_data.get("mean")
            summary["std"] = result_data.get("std")
            summary["n"] = result_data.get("n")
        elif r["type"] == "net_score":
            summary["top_box_pct"] = result_data.get("top_box_pct")
            summary["bottom_box_pct"] = result_data.get("bottom_box_pct")

        results_summary.append(summary)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        lang_instruction = "Respond in Spanish." if language == "es" else "Respond in English."

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=f"""You are a market research analyst interpreting statistical results.
Provide a concise, professional summary of the data analysis results.
{lang_instruction}
Rules:
- ONLY cite numbers that appear in the data provided. NEVER invent statistics.
- Be concise: 2-4 sentences per analysis.
- Use market research terminology.
- If significance letters are present, mention which groups differ significantly.""",
            messages=[{
                "role": "user",
                "content": f"Question: {question}\n\nResults:\n{json.dumps(results_summary, ensure_ascii=False, default=str)}",
            }],
        )
        return response.content[0].text.strip()

    except Exception as e:
        logger.warning("translate_results failed: %s", e)
        return _fallback_summary(results, language)


def _fallback_summary(results: list[dict], language: str) -> str:
    """Generate a basic summary without Claude."""
    parts = []
    for r in results:
        rtype = r["type"]
        var = r.get("variable", "?")
        if rtype == "frequency":
            rd = r.get("result", {})
            total = rd.get("total_responses", rd.get("base", "?"))
            parts.append(f"Frequency of {var} (n={total})")
        elif "crosstab" in rtype:
            cross = r.get("cross_variable", "?")
            parts.append(f"Crosstab: {var} by {cross}")
        elif rtype == "nps":
            score = r.get("result", {}).get("nps_score", "?")
            parts.append(f"NPS: {score}")
        else:
            parts.append(f"{rtype}: {var}")

    if language == "es":
        return "Resultados: " + "; ".join(parts) + "."
    return "Results: " + "; ".join(parts) + "."


# ─── Chart Building ───────────────────────────────────────────────────────


def _build_chart(result: dict[str, Any]) -> dict | None:
    """Build a Recharts-compatible chart spec from analysis result."""
    rtype = result.get("type")
    data = result.get("result", {})

    if not data:
        return None

    if rtype == "frequency":
        return _build_frequency_chart(data, result.get("variable"))
    elif rtype in ("crosstab", "crosstab_with_significance"):
        return _build_crosstab_chart(data, result.get("variable"), result.get("cross_variable"))
    elif rtype == "nps":
        return _build_nps_chart(data)
    elif rtype == "net_score":
        return _build_net_score_chart(data)
    elif rtype == "descriptive":
        return None  # No chart for descriptive stats
    elif rtype == "correlation":
        return None  # Heatmap would need frontend component
    return None


def _build_frequency_chart(data: dict, variable: str | None) -> dict:
    """Build a bar chart spec for frequency results."""
    rows = data.get("frequencies", data.get("rows", []))
    chart_data = []
    for row in rows[:20]:  # Limit bars
        chart_data.append({
            "name": str(row.get("label", row.get("value", ""))),
            "value": row.get("percentage", row.get("count", 0)),
            "count": row.get("count", 0),
        })

    return {
        "chart_type": "bar",
        "title": f"Distribution: {variable or ''}",
        "data": chart_data,
        "xKey": "name",
        "yKey": "value",
        "yLabel": "%",
    }


def _build_crosstab_chart(data: dict, row_var: str | None, col_var: str | None) -> dict:
    """Build a grouped bar chart for crosstab results."""
    table = data.get("table", [])
    col_labels = data.get("col_labels", {})

    chart_data = []
    for row in table[:15]:  # Limit rows
        entry = {"name": str(row.get("row_label", row.get("row_value", "")))}
        for col_val, col_info in row.items():
            if col_val in ("row_value", "row_label", "Total"):
                continue
            if isinstance(col_info, dict):
                letter = col_info.get("column_letter", "")
                entry[f"{letter}_{col_val}"] = col_info.get("percentage", 0)
        chart_data.append(entry)

    return {
        "chart_type": "grouped_bar",
        "title": f"{row_var or ''} by {col_var or ''}",
        "data": chart_data,
        "col_labels": col_labels,
    }


def _build_nps_chart(data: dict) -> dict:
    """Build an NPS gauge chart spec."""
    return {
        "chart_type": "nps_gauge",
        "title": "Net Promoter Score",
        "nps_score": data.get("nps_score", 0),
        "promoters_pct": data.get("promoters_pct", 0),
        "passives_pct": data.get("passives_pct", 0),
        "detractors_pct": data.get("detractors_pct", 0),
    }


def _build_net_score_chart(data: dict) -> dict:
    """Build a T2B/B2B chart."""
    return {
        "chart_type": "net_score",
        "title": "Top/Bottom Box",
        "top_box_pct": data.get("top_box_pct", 0),
        "bottom_box_pct": data.get("bottom_box_pct", 0),
        "net_score": data.get("top_box_pct", 0) - data.get("bottom_box_pct", 0),
    }


# ─── Python Code Generation ──────────────────────────────────────────────


def _generate_python_code(results: list[dict]) -> str | None:
    """Generate reproducible Python code for the analyses."""
    if not results:
        return None

    lines = [
        "import pyreadstat",
        "import pandas as pd",
        "from scipy import stats",
        "",
        '# Load data',
        'df, meta = pyreadstat.read_sav("your_file.sav")',
        "",
    ]

    for r in results[:5]:
        rtype = r["type"]
        var = r.get("variable", "var")

        if rtype == "frequency":
            lines.append(f"# Frequency: {var}")
            lines.append(f"freq = df['{var}'].value_counts()")
            lines.append(f"print(freq)")
            lines.append("")
        elif "crosstab" in rtype:
            cross = r.get("cross_variable", "cross")
            lines.append(f"# Crosstab: {var} by {cross}")
            lines.append(f"ct = pd.crosstab(df['{var}'], df['{cross}'], margins=True)")
            lines.append(f"print(ct)")
            lines.append("")
        elif rtype == "nps":
            lines.append(f"# NPS: {var}")
            lines.append(f"promoters = (df['{var}'] >= 9).sum()")
            lines.append(f"detractors = (df['{var}'] <= 6).sum()")
            lines.append(f"total = df['{var}'].notna().sum()")
            lines.append(f"nps = (promoters - detractors) / total * 100")
            lines.append(f"print(f'NPS: {{nps:.1f}}')")
            lines.append("")
        elif rtype == "descriptive":
            lines.append(f"# Descriptive: {var}")
            lines.append(f"print(df['{var}'].describe())")
            lines.append("")

    return "\n".join(lines)
