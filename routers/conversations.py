"""Conversations API — NL chat with analysis execution.

Pipeline: question → interpreter (Claude) → executor (quantipy_engine) → responder → response

All endpoints require Supabase JWT auth.
"""

import asyncio
import hashlib
import json
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.conversation import Conversation, Message, MessageRole
from db.models.project import DatasetMetadata, Project, ProjectFile, FileType
from schemas.conversations import (
    ConversationCreate,
    ConversationDetailOut,
    ConversationOut,
    MessageOut,
    QueryRequest,
    QueryResponse,
)
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Conversations"])

QUERY_TIMEOUT_SECONDS = 45
REPORT_TIMEOUT_SECONDS = 120

# In-memory query cache (simple, per-worker)
_query_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 300  # 5 minutes


# ─── Conversation CRUD ────────────────────────────────────────────────────


@router.post("/projects/{project_id}/conversations")
async def create_conversation(
    project_id: UUID,
    data: ConversationCreate = ConversationCreate(),
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversation in a project."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    conv = Conversation(
        project_id=project_id,
        user_id=auth.db_user.id,
        title=data.title,
    )
    db.add(conv)
    await db.flush()

    return success_response({
        "id": str(conv.id),
        "project_id": str(project_id),
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
    })


@router.get("/projects/{project_id}/conversations")
async def list_conversations(
    project_id: UUID,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversations in a project."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    # Single query with message count (no N+1)
    stmt = (
        select(
            Conversation.id,
            Conversation.title,
            Conversation.created_at,
            Conversation.updated_at,
            func.count(Message.id).label("message_count"),
        )
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(
            Conversation.project_id == project_id,
            Conversation.user_id == auth.db_user.id,
        )
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    conversations = [
        {
            "id": str(row.id),
            "project_id": str(project_id),
            "title": row.title,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "message_count": row.message_count,
        }
        for row in rows
    ]
    return success_response(conversations)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a conversation with all messages."""
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == auth.db_user.id,
        )
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()

    if conv is None:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Conversation not found"))

    messages = [
        {
            "id": str(m.id),
            "role": m.role.value,
            "content": m.content,
            "analyses_performed": m.analyses_performed,
            "charts": m.charts,
            "variables_used": m.variables_used,
            "python_code": m.python_code,
            "warnings": m.warnings,
            "created_at": m.created_at.isoformat(),
        }
        for m in (conv.messages or [])
    ]

    return success_response({
        "id": str(conv.id),
        "project_id": str(conv.project_id),
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "messages": messages,
    })


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation."""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == auth.db_user.id,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()

    if conv is None:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Conversation not found"))

    await db.delete(conv)
    await db.flush()
    return success_response(None)


# ─── Query (Main Pipeline) ───────────────────────────────────────────────


@router.post("/conversations/{conversation_id}/query")
async def query_conversation(
    conversation_id: UUID,
    data: QueryRequest,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute a natural language query against the project's data.

    Pipeline:
    1. Load conversation + project
    2. Check cache
    3. Interpret question (Claude → analysis plan)
    4. Execute analyses (quantipy_engine)
    5. Build response (NL + charts)
    6. Persist messages
    7. Return QueryResponse
    """
    t_start = time.time()

    # Load conversation with project access check
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == auth.db_user.id,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv is None:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Conversation not found"))

    # Load project with metadata
    try:
        project = await get_project(db, conv.project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    # Check we have data
    if not project.dataset_metadata:
        return JSONResponse(status_code=400, content=error_response(
            "NO_DATA", "Project has no uploaded data. Upload an SPSS file first."
        ))

    # Cache check
    cache_key = _cache_key(conv.project_id, auth.db_user.id, data.question)
    cached = _check_cache(cache_key)
    if cached:
        logger.info("[QUERY] Cache hit for %s", cache_key[:16])
        return success_response(cached, meta={
            "processing_time_ms": int((time.time() - t_start) * 1000),
            "cached": True,
            "engine": "quantipymrx",
        })

    # Run the pipeline with timeout
    try:
        response_data = await asyncio.wait_for(
            _run_query_pipeline(db, conv, project, data),
            timeout=QUERY_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content=error_response(
            "QUERY_TIMEOUT",
            f"Query exceeded {QUERY_TIMEOUT_SECONDS}s. Try a simpler question.",
        ))
    except Exception as e:
        logger.error("[QUERY] Pipeline error: %s", e, exc_info=True)
        # Save error message
        error_msg = Message(
            conversation_id=conv.id,
            role=MessageRole.ASSISTANT,
            content="",
            error_message=str(e)[:500],
        )
        db.add(error_msg)
        await db.flush()
        return JSONResponse(status_code=500, content=error_response(
            "QUERY_FAILED", str(e) if not get_settings_safe().is_production else "Analysis failed",
        ))

    # Cache result
    _store_cache(cache_key, response_data)

    processing_time = int((time.time() - t_start) * 1000)
    logger.info("[QUERY] Completed in %dms: %s", processing_time, data.question[:80])

    return success_response(response_data, meta={
        "processing_time_ms": processing_time,
        "cached": False,
        "engine": "quantipymrx",
    })


# ─── Suggestions ──────────────────────────────────────────────────────────


@router.get("/conversations/{conversation_id}/suggestions")
async def get_suggestions(
    conversation_id: UUID,
    lang: str = Query("en", description="Language: en or es"),
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Get context-aware analysis suggestions for the conversation's project."""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == auth.db_user.id,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv is None:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Conversation not found"))

    try:
        project = await get_project(db, conv.project_id, auth.db_user)
    except ProjectAccessError:
        return success_response([])

    suggestions = _generate_suggestions(project, lang)
    return success_response(suggestions)


# ─── Pipeline Implementation ─────────────────────────────────────────────


async def _run_query_pipeline(
    db: AsyncSession,
    conv: Conversation,
    project: Project,
    data: QueryRequest,
) -> dict:
    """Execute the full query pipeline."""
    from services.nl_chat.interpreter import interpret_query
    from services.nl_chat.executor import execute_analysis_plan
    from services.nl_chat.responder import build_response
    from services.data_manager import get_project_data

    # 1. Save user message
    user_msg = Message(
        conversation_id=conv.id,
        role=MessageRole.USER,
        content=data.question,
    )
    db.add(user_msg)
    await db.flush()

    # 2. Load data
    spss_data = await get_project_data(str(project.id))

    # 3. Get variable info from metadata
    variables_info = project.dataset_metadata.enriched_variables

    # 4. Build study context
    study_context = {
        "study_objective": project.study_objective,
        "country": project.country,
        "industry": project.industry,
        "brands": project.brands,
    }

    # 5. Interpret question (Claude)
    analysis_plan = await interpret_query(
        question=data.question,
        variables_info=variables_info,
        study_context=study_context,
        confidence_level=data.confidence_level,
    )

    # 6. Execute analyses (quantipy_engine)
    analysis_results = await execute_analysis_plan(
        data=spss_data,
        plan=analysis_plan,
        low_base_threshold=project.low_base_threshold,
    )

    # 7. Build response (NL + charts)
    response = await build_response(
        question=data.question,
        analysis_results=analysis_results,
        language=project.report_language,
    )

    # 8. Save assistant message
    assistant_msg = Message(
        conversation_id=conv.id,
        role=MessageRole.ASSISTANT,
        content=response["answer"],
        analyses_performed=[
            {"type": a["type"], "variable": a.get("variable"), "success": a["success"]}
            for a in response["analyses"]
        ],
        charts=[a.get("chart") for a in response["analyses"] if a.get("chart")],
        variables_used=response["variables_used"],
        python_code=response["python_code"],
        warnings=response["warnings"],
    )
    db.add(assistant_msg)
    await db.flush()

    # 9. Auto-name conversation on first query
    if conv.title == "New conversation":
        conv.title = data.question[:100]
        await db.flush()

    return {
        "message_id": str(assistant_msg.id),
        "answer": response["answer"],
        "analyses": response["analyses"],
        "variables_used": response["variables_used"],
        "python_code": response["python_code"],
        "warnings": response["warnings"],
    }


# ─── Cache ────────────────────────────────────────────────────────────────


def _cache_key(project_id, user_id, question: str) -> str:
    raw = f"{project_id}:{user_id}:{question.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _check_cache(key: str) -> dict | None:
    if key in _query_cache:
        data, ts = _query_cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _query_cache[key]
    return None


def _store_cache(key: str, data: dict) -> None:
    # Evict oldest if cache too large
    if len(_query_cache) > 100:
        oldest = min(_query_cache, key=lambda k: _query_cache[k][1])
        del _query_cache[oldest]
    _query_cache[key] = (data, time.time())


# ─── Suggestions ──────────────────────────────────────────────────────────


def _generate_suggestions(project: Project, lang: str) -> list[dict]:
    """Generate dataset-specific analysis suggestions."""
    meta = project.dataset_metadata
    if not meta:
        return []

    variables = meta.enriched_variables or []
    suggestions = []

    # Find key variable types
    categoricals = [v for v in variables if v.get("value_labels") and len(v.get("value_labels", {})) <= 10]
    numerics = [v for v in variables if v.get("type") == "numeric" and not v.get("value_labels")]

    if categoricals:
        v = categoricals[0]
        name = v.get("label") or v["name"]
        if lang == "es":
            suggestions.append({"text": f"¿Cuál es la distribución de {name}?", "type": "frequency"})
        else:
            suggestions.append({"text": f"What is the distribution of {name}?", "type": "frequency"})

    if len(categoricals) >= 2:
        v1 = categoricals[0]
        v2 = categoricals[1]
        n1 = v1.get("label") or v1["name"]
        n2 = v2.get("label") or v2["name"]
        if lang == "es":
            suggestions.append({"text": f"Cruza {n1} por {n2} con significancia", "type": "crosstab"})
        else:
            suggestions.append({"text": f"Cross {n1} by {n2} with significance", "type": "crosstab"})

    # NPS suggestion
    nps_vars = [v for v in variables if any(k in (v.get("label") or "").lower() for k in ["recommend", "nps", "recomendar"])]
    if nps_vars:
        name = nps_vars[0].get("label") or nps_vars[0]["name"]
        if lang == "es":
            suggestions.append({"text": f"¿Cuál es el NPS de {name}?", "type": "nps"})
        else:
            suggestions.append({"text": f"What is the NPS for {name}?", "type": "nps"})

    # Summary suggestion
    if lang == "es":
        suggestions.append({"text": "Genera un reporte detallado", "type": "report"})
    else:
        suggestions.append({"text": "Generate a detailed report", "type": "report"})

    return suggestions[:6]


# ─── Helpers ──────────────────────────────────────────────────────────────


def get_settings_safe():
    from config import get_settings
    return get_settings()
