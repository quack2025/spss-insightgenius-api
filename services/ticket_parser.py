"""Parse Reporting Ticket .docx files into structured analysis plans via Claude Haiku."""

import io
import json
import logging
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)

TICKET_PARSER_SYSTEM_PROMPT = """You are a market research analyst AI. You parse "Reporting Tickets" — instruction documents that specify what tables and analyses should be produced from an SPSS survey dataset.

A reporting ticket typically contains:
- Banner/break variables (demographics for column headers in crosstabs)
- Stub list (questions to analyze in rows)
- Weighting instructions
- Base filtering (e.g., "Base: All respondents who...")
- Special instructions (nets, top-box, significance level)
- Template preferences (e.g., "standard tables", "summary tables")

Given the ticket text and optionally the available variables in the dataset, produce a JSON analysis plan.

RULES:
1. Only use variable names from <available_variables> when provided. If unsure of a match, add a note.
2. Use fuzzy matching for variable names (case-insensitive, ignore underscores vs spaces).
3. If the ticket mentions "Total" as a banner, that means no cross-variable (frequency only).
4. Nets like "Top 2 Box" on a 5-point scale → type "top_bottom_box" with top_values=[4,5], bottom_values=[1,2].
5. If significance level is mentioned (e.g., "95% confidence"), include it in params.
6. Default significance_level is 0.95 if not specified.
7. Return ONLY valid JSON. No markdown, no explanation.

Output format:
{
  "operations": [
    {"type": "frequency", "variable": "Q1"},
    {"type": "crosstab", "variable": "Q1", "cross_variable": "gender", "params": {"significance_level": 0.95}},
    {"type": "nps", "variable": "Q_recommend"},
    {"type": "top_bottom_box", "variable": "Q_sat", "params": {"top_values": [4, 5], "bottom_values": [1, 2]}}
  ],
  "weight": "weight_var_name_or_null",
  "filters": [],
  "notes": ["Could not match 'Brand awareness' to any variable"]
}

Valid operation types: frequency, crosstab, nps, top_bottom_box, nets"""


class TicketParser:
    """Parse Reporting Ticket .docx files using Claude Haiku."""

    def __init__(self):
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for ticket parsing")

        from anthropic import AsyncAnthropic
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def parse(
        self,
        docx_bytes: bytes,
        available_variables: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Parse a .docx Reporting Ticket into a structured plan.

        Args:
            docx_bytes: Raw .docx file bytes
            available_variables: Optional list of VariableInfo dicts from the dataset

        Returns:
            Dict with operations, weight, filters, notes
        """
        # Extract text from .docx
        text = self._extract_text(docx_bytes)
        if not text.strip():
            return {
                "raw_text": "",
                "operations": [],
                "weight": None,
                "filters": [],
                "notes": ["Empty document — no text could be extracted"],
            }

        # Build prompt
        user_content = f"<ticket>\n{text[:8000]}\n</ticket>"

        if available_variables:
            var_summary = "\n".join(
                f"- {v['name']}: {v.get('label', '')} ({v.get('type', 'unknown')})"
                for v in available_variables[:200]
            )
            user_content += f"\n\n<available_variables>\n{var_summary}\n</available_variables>"

        user_content += "\n\nParse this reporting ticket into a structured JSON analysis plan."

        # Call Haiku
        response = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=TICKET_PARSER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        # Parse response
        response_text = response.content[0].text if response.content else ""
        try:
            plan = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    plan = json.loads(response_text[start:end])
                except json.JSONDecodeError:
                    plan = {
                        "operations": [],
                        "notes": [f"Failed to parse Haiku response as JSON"],
                    }
            else:
                plan = {
                    "operations": [],
                    "notes": ["No JSON found in Haiku response"],
                }

        plan["raw_text"] = text[:2000]  # Include first 2K of ticket text for reference
        plan.setdefault("operations", [])
        plan.setdefault("weight", None)
        plan.setdefault("filters", [])
        plan.setdefault("notes", [])

        return plan

    @staticmethod
    def _extract_text(docx_bytes: bytes) -> str:
        """Extract plain text from a .docx file."""
        from docx import Document

        doc = Document(io.BytesIO(docx_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    paragraphs.append(" | ".join(cells))

        return "\n".join(paragraphs)
