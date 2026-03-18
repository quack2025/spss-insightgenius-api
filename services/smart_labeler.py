"""Improve cryptic SPSS variable labels using Claude Haiku."""

import json
import logging
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)

SMART_LABELER_SYSTEM_PROMPT = """You improve cryptic SPSS variable labels into clear, human-readable descriptions.

Input: A list of variables with their current names, labels, and value labels.
Output: A JSON object mapping variable names to improved labels.

RULES:
1. Keep improved labels concise (under 60 characters).
2. If the current label is already clear, keep it as-is.
3. If value labels suggest a scale (1-5, 1-7, 1-10), mention the scale type.
4. If value labels are binary (Yes/No, 0/1), note it.
5. If the variable name suggests a group (Q5_1, Q5_2), note the group.
6. Return ONLY valid JSON. No markdown.

Example output:
{"Q2_3": "Overall Satisfaction (1-5 scale)", "S1": "Gender (Male/Female)", "Q5_1": "Brand Awareness: Coca-Cola (Yes/No)"}"""


class SmartLabeler:
    """Improve SPSS variable labels using Haiku."""

    def __init__(self):
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for smart labeling")

        from anthropic import AsyncAnthropic
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def label(self, variables: list[dict[str, Any]]) -> dict[str, str]:
        """Improve labels for a list of variables.

        Args:
            variables: List of VariableInfo dicts with name, label, value_labels

        Returns:
            Dict mapping variable name → improved label
        """
        if not variables:
            return {}

        # Build compact representation (batch all variables in one call)
        var_lines = []
        for v in variables[:150]:  # Cap at 150 to stay within Haiku token limits
            parts = [f"name={v['name']}"]
            if v.get("label"):
                parts.append(f"label={v['label']}")
            if v.get("value_labels"):
                vl = v["value_labels"]
                # Show first 5 value labels
                sample = dict(list(vl.items())[:5])
                parts.append(f"values={sample}")
            var_lines.append(", ".join(parts))

        user_content = (
            "Improve these SPSS variable labels:\n\n"
            + "\n".join(var_lines)
            + "\n\nReturn a JSON object mapping variable name → improved label."
        )

        response = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=SMART_LABELER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        response_text = response.content[0].text if response.content else "{}"
        try:
            result = json.loads(response_text)
            if isinstance(result, dict):
                return {str(k): str(v) for k, v in result.items()}
        except json.JSONDecodeError:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    result = json.loads(response_text[start:end])
                    return {str(k): str(v) for k, v in result.items()}
                except json.JSONDecodeError:
                    pass

        logger.warning("Smart labeler failed to parse response")
        return {}
