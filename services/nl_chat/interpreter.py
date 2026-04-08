"""NL Query Interpreter — converts natural language to analysis plans.

Uses Claude to classify user intent and extract parameters.
The LLM ONLY interprets — it never generates data or statistics.
All rules are designed for market research vocabulary.
"""

import json
import logging
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)

# Supported analysis types (mapped to quantipy_engine methods)
ANALYSIS_TYPES = [
    "frequency",                 # Single variable distribution
    "crosstab",                  # Two-way table (no significance)
    "crosstab_with_significance",# Crosstab + A/B/C letters
    "compare_means",             # Numeric means by group
    "nps",                       # Net Promoter Score
    "net_score",                 # Top 2 Box / Bottom 2 Box
    "correlation",               # Pearson/Spearman matrix
    "descriptive",               # Mean/std/median/min/max
    "multiple_response",         # MRS frequency
    "gap_analysis",              # Importance-Performance quadrant
    "executive_summary",         # AI narrative summary
    "detailed_report",           # Multi-analysis report
]


def _build_system_prompt(variables_info: list[dict], study_context: dict | None = None) -> str:
    """Build the system prompt for Claude with variable info and rules."""

    # Variable list (compact for large datasets)
    if len(variables_info) > 200:
        var_block = "\n".join(
            f"- {v['name']}: {v.get('label', '')} [{v.get('type', '')}]"
            for v in variables_info[:200]
        )
        var_block += f"\n... and {len(variables_info) - 200} more variables"
    else:
        var_block = "\n".join(
            f"- {v['name']}: {v.get('label', '')} [{v.get('type', '')}]"
            + (f" values: {json.dumps(v['value_labels'], ensure_ascii=False)}" if v.get('value_labels') else "")
            for v in variables_info
        )

    # Study context
    context_block = ""
    if study_context:
        parts = []
        if study_context.get("study_objective"):
            parts.append(f"Objective: {study_context['study_objective']}")
        if study_context.get("country"):
            parts.append(f"Country: {study_context['country']}")
        if study_context.get("industry"):
            parts.append(f"Industry: {study_context['industry']}")
        if study_context.get("brands"):
            parts.append(f"Brands: {', '.join(study_context['brands'])}")
        if parts:
            context_block = "\n## Study Context\n" + "\n".join(parts)

    return f"""You are a market research data analysis assistant. You interpret natural language questions about survey data and return a structured analysis plan.

## Available Variables
{var_block}
{context_block}

## Rules

1. ONLY use variable names that appear in the list above. Use EXACT names (case-sensitive).
2. For frequency: use when asking about distribution of ONE variable ("how is X distributed?", "what percentage of...", "awareness levels").
3. For crosstab_with_significance: use when asking about relationship between TWO variables ("X by Y", "X segmented by Y", "compare X across Y groups"). Default to significance=true.
4. For compare_means: use when asking about numeric means across groups ("average satisfaction by gender").
5. For nps: use when a variable looks like NPS (0-10 scale, "recommend", "NPS").
6. For net_score: use when asking about Top 2 Box (T2B) or Bottom 2 Box (B2B) on Likert scales.
7. For correlation: use when asking about relationship between 2+ numeric variables.
8. For descriptive: use when asking for basic stats (mean, median, std) of a numeric variable.
9. For multiple_response: use when the question is about a multiple-select question (binary 0/1 variables with common prefix).
10. For gap_analysis: use when asking about importance vs satisfaction/performance gaps.
11. Market research vocabulary: "awareness" → frequency, "by" → crosstab, "compare" → compare_means, "key drivers" → correlation, "segmented by" → crosstab.
12. If the user mentions "weighted" or "use weights", set weight to the weight variable from the dataset.
13. Confidence level: extract from query ("90%", "95%", "99%") or default to 0.95.
14. For "reporte detallado" or "detailed report", set type to "detailed_report".
15. For "resumen ejecutivo" or "executive summary", set type to "executive_summary".
16. If the question is ambiguous, choose the most common analysis type (frequency for single var, crosstab for two vars).
17. NEVER invent or guess data — only specify which analysis to run.
18. Language: respond in the same language as the question (Spanish or English).

## Output Format

Return a JSON array of analysis requests:
```json
[
  {{
    "type": "frequency|crosstab_with_significance|compare_means|nps|net_score|correlation|descriptive|multiple_response|gap_analysis|executive_summary|detailed_report",
    "variable": "main_variable_name",
    "cross_variable": "banner_variable_name or null",
    "weight": "weight_variable_name or null",
    "significance_level": 0.95,
    "top_box_codes": [4, 5],
    "bottom_box_codes": [1, 2]
  }}
]
```

Return ONLY the JSON array, no other text."""


async def interpret_query(
    question: str,
    variables_info: list[dict],
    study_context: dict | None = None,
    confidence_level: float | None = None,
    conversation_history: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Interpret a natural language question into an analysis plan.

    Returns a list of analysis requests, each with type, variable(s), and parameters.
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not set — NL chat requires Claude")

    import anthropic

    system_prompt = _build_system_prompt(variables_info, study_context)

    # Build messages with conversation history (last 5 exchanges)
    messages = []
    if conversation_history:
        for msg in conversation_history[-10:]:  # Last 5 exchanges = 10 messages
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

    messages.append({"role": "user", "content": question})

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=messages,
        )

        raw_text = response.content[0].text.strip()

        # Extract JSON from response (may be wrapped in ```json ... ```)
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        analysis_plan = json.loads(raw_text)

        if not isinstance(analysis_plan, list):
            analysis_plan = [analysis_plan]

        # Apply confidence level override
        if confidence_level:
            for req in analysis_plan:
                req["significance_level"] = confidence_level

        # Validate types
        for req in analysis_plan:
            if req.get("type") not in ANALYSIS_TYPES:
                logger.warning("Unknown analysis type: %s, defaulting to frequency", req.get("type"))
                req["type"] = "frequency"

        logger.info("Interpreted query into %d analyses: %s",
                     len(analysis_plan),
                     [r["type"] for r in analysis_plan])
        return analysis_plan

    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude response as JSON: %s", e)
        # Fallback: try to extract something useful
        return [{"type": "frequency", "variable": None, "error": f"Parse error: {e}"}]
    except Exception as e:
        logger.error("interpret_query failed: %s", e)
        raise
