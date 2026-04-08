"""Data Preparation API — CRUD + preview + reorder rules."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.data_prep import DataPrepRule, RuleType
from schemas.data_prep import DataPrepRuleCreate, DataPrepRuleUpdate, DataPrepRuleOut, ReorderRequest, PreviewRequest
from services.data_prep_service import MAX_RULES_PER_PROJECT, preview_rule
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/data-prep", tags=["Data Prep"])


@router.post("/rules")
async def create_rule(
    project_id: UUID, data: DataPrepRuleCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    # Check limit
    count_result = await db.execute(
        select(DataPrepRule).where(DataPrepRule.project_id == project_id)
    )
    if len(count_result.all()) >= MAX_RULES_PER_PROJECT:
        return JSONResponse(status_code=400, content=error_response(
            "LIMIT_REACHED", f"Maximum {MAX_RULES_PER_PROJECT} rules per project"))

    rule = DataPrepRule(
        project_id=project_id,
        rule_type=RuleType(data.rule_type),
        name=data.name,
        description=data.description,
        config=data.config,
        is_active=data.is_active,
    )
    db.add(rule)
    await db.flush()
    return success_response(DataPrepRuleOut.model_validate(rule).model_dump(mode="json"))


@router.get("/rules")
async def list_rules(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(DataPrepRule)
        .where(DataPrepRule.project_id == project_id)
        .order_by(DataPrepRule.order_index)
    )
    rules = result.scalars().all()
    return success_response([DataPrepRuleOut.model_validate(r).model_dump(mode="json") for r in rules])


@router.put("/rules/{rule_id}")
async def update_rule(
    project_id: UUID, rule_id: UUID, data: DataPrepRuleUpdate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(DataPrepRule).where(DataPrepRule.id == rule_id, DataPrepRule.project_id == project_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Rule not found"))

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await db.flush()
    return success_response(DataPrepRuleOut.model_validate(rule).model_dump(mode="json"))


@router.delete("/rules/{rule_id}")
async def delete_rule(
    project_id: UUID, rule_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(DataPrepRule).where(DataPrepRule.id == rule_id, DataPrepRule.project_id == project_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Rule not found"))

    await db.delete(rule)
    await db.flush()
    return success_response(None)


@router.put("/reorder")
async def reorder_rules(
    project_id: UUID, data: ReorderRequest,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    for idx, rule_id in enumerate(data.rule_ids):
        result = await db.execute(
            select(DataPrepRule).where(DataPrepRule.id == rule_id, DataPrepRule.project_id == project_id)
        )
        rule = result.scalar_one_or_none()
        if rule:
            rule.order_index = idx
    await db.flush()
    return success_response({"reordered": len(data.rule_ids)})


@router.post("/preview")
async def preview_rule_endpoint(
    project_id: UUID, data: PreviewRequest,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Preview the impact of a rule without saving it."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    # Load data
    from services.data_manager import get_project_data
    try:
        spss_data = await get_project_data(str(project_id))
    except Exception as e:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", str(e)))

    # Get existing rules for cumulative preview
    result = await db.execute(
        select(DataPrepRule)
        .where(DataPrepRule.project_id == project_id, DataPrepRule.is_active == True)
        .order_by(DataPrepRule.order_index)
    )
    existing = [{"rule_type": r.rule_type.value, "config": r.config, "is_active": True}
                for r in result.scalars().all()]

    preview = preview_rule(spss_data.df, data.rule_type, data.config, existing)
    return success_response(preview)
