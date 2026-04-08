"""NL Chat engine — interprets natural language, executes analysis, builds responses.

Pipeline: question → interpreter → executor → responder → QueryResponse
"""

from services.nl_chat.interpreter import interpret_query
from services.nl_chat.executor import execute_analysis_plan
from services.nl_chat.responder import build_response

__all__ = ["interpret_query", "execute_analysis_plan", "build_response"]
