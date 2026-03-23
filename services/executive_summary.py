"""Generate executive summary of tabulation results using Claude Haiku."""

import json
import logging
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = """You are a senior market research analyst. You write clear, actionable executive summaries of crosstab analysis results.

Your summary should:
1. Lead with the 3-5 most important findings (statistically significant differences)
2. Use specific numbers (percentages, sig letters) to support each finding
3. Identify which segments/groups differ most
4. Flag any notable patterns across multiple variables
5. End with 2-3 actionable recommendations

Format: Use bullet points. Be concise but specific. Write in the language that matches the variable labels (Spanish labels → Spanish summary, English labels → English summary).

If study_context is provided, frame findings around those objectives and benchmarks."""


async def generate_executive_summary(
    tabulation_results: list[dict[str, Any]],
    banner_labels: list[str],
    study_context: dict[str, Any] | None = None,
    file_name: str = "",
    n_cases: int = 0,
) -> str:
    """Generate an executive summary from tabulation results.

    Args:
        tabulation_results: List of dicts with variable, label, type, data (top findings per stub)
        banner_labels: Banner variable labels for context
        study_context: Optional dict with objectives, target_audience, key_questions, benchmarks
        file_name: Original file name
        n_cases: Total number of cases

    Returns:
        Executive summary text (markdown format)
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return "_Executive summary requires ANTHROPIC_API_KEY to be configured._"

    from anthropic import AsyncAnthropic
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Build a condensed summary of results (stay within token limits)
    findings = []
    for r in tabulation_results[:30]:  # Cap at 30 stubs
        if r.get("status") != "success":
            continue
        entry = f"**{r.get('variable', '?')}** ({r.get('label', '')}): "
        if r.get("significant_cells"):
            entry += f"Significant differences: {', '.join(r['significant_cells'][:5])}"
        if r.get("means"):
            entry += f" | Means: {r['means']}"
        if r.get("t2b"):
            entry += f" | T2B: {r['t2b']}"
        findings.append(entry)

    user_content = f"""<analysis_context>
File: {file_name}
Total cases: {n_cases}
Banners: {', '.join(banner_labels)}
Total stubs analyzed: {len(tabulation_results)}
</analysis_context>

<findings>
{chr(10).join(findings) if findings else 'No significant findings to summarize.'}
</findings>"""

    if study_context:
        ctx_parts = []
        if study_context.get("objectives"):
            ctx_parts.append(f"Objectives: {study_context['objectives']}")
        if study_context.get("target_audience"):
            ctx_parts.append(f"Target: {study_context['target_audience']}")
        if study_context.get("key_questions"):
            ctx_parts.append(f"Key questions: {', '.join(study_context['key_questions'])}")
        if study_context.get("benchmarks"):
            ctx_parts.append(f"Benchmarks: {json.dumps(study_context['benchmarks'])}")
        user_content += f"\n\n<study_context>\n{chr(10).join(ctx_parts)}\n</study_context>"

    user_content += "\n\nWrite an executive summary of these analysis results."

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text if response.content else ""
    except Exception as e:
        logger.error("Executive summary generation failed: %s", e)
        return f"_Executive summary generation failed: {e}_"
