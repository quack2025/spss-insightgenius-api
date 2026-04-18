"""Report Generator — deterministic multi-analysis reports with AI narrative.

Runs 6-8 analyses in parallel based on variable types, then generates
a unified narrative via Claude. All statistics are calculated, not AI-generated.
"""

import asyncio
import logging
from typing import Any

from services.quantipy_engine import QuantiProEngine, SPSSData
from services.nl_chat.executor import execute_analysis_plan
from config import get_settings

logger = logging.getLogger(__name__)


async def generate_report(
    data: SPSSData,
    variables_info: list[dict[str, Any]],
    language: str = "en",
    depth: str = "standard",
) -> dict[str, Any]:
    """Generate a multi-analysis report.

    1. Plan analyses based on variable types
    2. Execute in parallel
    3. Generate narrative via Claude
    """
    plan = _build_report_plan(variables_info, data)

    # Execute all analyses
    results = await execute_analysis_plan(data, plan)
    successful = [r for r in results if r.get("success")]

    # Generate narrative
    narrative = await _generate_narrative(successful, language, depth)

    return {
        "title": "Executive Report",
        "narrative": narrative,
        "analyses": results,
        "n_analyses": len(results),
        "n_successful": len(successful),
        "depth": depth,
    }


def _build_report_plan(variables_info: list[dict], data: SPSSData) -> list[dict]:
    """Deterministic analysis selection based on variable types."""
    plan = []

    # Classify variables
    categoricals = [v for v in variables_info
                    if v.get("value_labels") and 2 <= len(v.get("value_labels", {})) <= 10]
    numerics = [v for v in variables_info
                if v.get("type") == "numeric" and not v.get("value_labels")]

    # Slot 1-2: Top demographics (frequency)
    demo_keywords = ["gender", "genero", "age", "edad", "region", "city", "ciudad", "nse", "income"]
    demos = [v for v in categoricals
             if any(k in (v.get("name", "") + v.get("label", "")).lower() for k in demo_keywords)]
    for v in demos[:2]:
        plan.append({"type": "frequency", "variable": v["name"]})

    # Slot 3: NPS if available
    nps_vars = [v for v in variables_info
                if any(k in (v.get("label") or "").lower() for k in ["recommend", "nps", "recomendar"])]
    if nps_vars:
        plan.append({"type": "nps", "variable": nps_vars[0]["name"]})

    # Slot 4: Top categorical (not demo)
    non_demos = [v for v in categoricals if v not in demos]
    if non_demos:
        plan.append({"type": "frequency", "variable": non_demos[0]["name"]})

    # Slot 5-6: Crosstab if we have demo + key var
    if demos and non_demos:
        plan.append({
            "type": "crosstab_with_significance",
            "variable": non_demos[0]["name"],
            "cross_variable": demos[0]["name"],
        })
    if len(demos) >= 2 and len(non_demos) >= 2:
        plan.append({
            "type": "crosstab_with_significance",
            "variable": non_demos[1]["name"] if len(non_demos) > 1 else non_demos[0]["name"],
            "cross_variable": demos[1]["name"],
        })

    # Slot 7: Descriptive for a numeric variable
    if numerics:
        plan.append({"type": "descriptive", "variable": numerics[0]["name"]})

    return plan[:8]  # Max 8 analyses


async def _generate_narrative(
    results: list[dict[str, Any]],
    language: str,
    depth: str,
) -> str:
    """Generate report narrative from analysis results via Claude."""
    settings = get_settings()

    if not results:
        return "No analyses could be executed." if language == "en" else "No se pudieron ejecutar los análisis."

    if not settings.anthropic_api_key:
        return _fallback_narrative(results, language)

    # Prepare results summary
    import json
    summaries = []
    for r in results[:8]:
        s = {"type": r["type"], "variable": r.get("variable")}
        rd = r.get("result", {})
        if r["type"] == "frequency":
            s["data"] = rd.get("frequencies", rd.get("rows", []))[:8]
            s["total"] = rd.get("base", rd.get("total_responses"))
        elif r["type"] == "nps":
            s["nps_score"] = rd.get("nps_score")
        elif r["type"] == "descriptive":
            s["mean"] = rd.get("mean")
            s["n"] = rd.get("n")
        summaries.append(s)

    depth_instruction = {
        "compact": "2-3 paragraphs, key findings only.",
        "standard": "5-section report: Overview, Sample Profile, Key Findings, Analysis, Conclusions. 500-1000 words.",
        "detailed": "5-section report with detailed analysis. 1000-2000 words.",
    }.get(depth, "5-section report. 500-1000 words.")

    lang_instruction = "Write in Spanish." if language == "es" else "Write in English."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=f"""You are a senior market research analyst writing an executive report.
{lang_instruction}
{depth_instruction}
Rules:
- ONLY cite numbers from the data. NEVER invent statistics.
- Start with sample size.
- Be professional and actionable.
- Include significance findings when available.""",
            messages=[{
                "role": "user",
                "content": f"Generate report from:\n{json.dumps(summaries, ensure_ascii=False, default=str)}",
            }],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning("Report narrative generation failed: %s", e)
        return _fallback_narrative(results, language)


def _fallback_narrative(results: list[dict], language: str) -> str:
    parts = []
    for r in results:
        parts.append(f"- {r['type']}: {r.get('variable', 'N/A')}")
    header = "Report Summary" if language == "en" else "Resumen del Reporte"
    return f"# {header}\n\nAnalyses performed:\n" + "\n".join(parts)
