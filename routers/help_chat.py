"""Help Chat API — AI-powered platform help assistant."""
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth_unified import AuthContext, require_user
from config import get_settings
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/help-chat", tags=["Help"])

KNOWLEDGE_BASE = """
InsightGenius is a market research data analysis platform.

Features:
- Upload SPSS (.sav), CSV, or Excel files
- Natural language chat to analyze data (frequency, crosstab, NPS, regression, etc.)
- Generate Tables wizard for professional Excel tabulations with significance testing
- Data preparation rules (cleaning, weighting, nets, recodes)
- Variable groups (MRS, grids) with auto-detection
- Segments (reusable audience filters)
- Waves for tracking studies
- Interactive Explore mode
- Dashboards with share links
- Team collaboration
- API + MCP for integrations

Analysis types: frequency, crosstab with significance (A/B/C letters),
compare means, NPS, net score (T2B/B2B), correlation, descriptive,
multiple response, gap analysis, regression, factor analysis.

All statistics are calculated by the engine (scipy/pandas/QuantipyMRX).
The AI only interprets results — it never generates numbers.
"""


class HelpQuestion(BaseModel):
    question: str


@router.post("")
async def ask_help(data: HelpQuestion, auth: AuthContext = Depends(require_user)):
    settings = get_settings()
    if not settings.anthropic_api_key:
        return success_response({"answer": "Help chat requires ANTHROPIC_API_KEY."})

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=f"You are a helpful assistant for InsightGenius platform.\n\n{KNOWLEDGE_BASE}\n\nAnswer concisely.",
            messages=[{"role": "user", "content": data.question}],
        )
        return success_response({"answer": response.content[0].text.strip()})
    except Exception as e:
        logger.warning("Help chat failed: %s", e)
        return success_response({"answer": "Sorry, help is temporarily unavailable."})
