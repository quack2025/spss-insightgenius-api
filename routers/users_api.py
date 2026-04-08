"""Users API — profile and preferences."""
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from schemas.dashboards import UserPreferencesUpdate, UserProfileOut
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/users", tags=["Users"])


@router.get("/me")
async def get_profile(auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    user = auth.db_user
    return success_response({
        "id": str(user.id), "email": user.email, "name": user.name,
        "plan": user.plan.value, "created_at": user.created_at.isoformat(),
    })


@router.patch("/me")
async def update_profile(
    data: dict, auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    user = auth.db_user
    if "name" in data:
        user.name = data["name"]
    await db.flush()
    return success_response({"id": str(user.id), "name": user.name})


@router.get("/me/preferences")
async def get_preferences(auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    user = auth.db_user
    prefs = user.preferences
    if not prefs:
        return success_response({"language": "en", "confidence_level": "95"})
    return success_response({
        "language": prefs.language,
        "confidence_level": prefs.confidence_level.value if hasattr(prefs.confidence_level, 'value') else prefs.confidence_level,
        "default_prompt": prefs.default_prompt,
    })


@router.patch("/me/preferences")
async def update_preferences(
    data: UserPreferencesUpdate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    user = auth.db_user
    if not user.preferences:
        from db.models.user import UserPreferences
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)
        await db.flush()
        # Refresh
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        from db.models.user import User
        result = await db.execute(select(User).options(selectinload(User.preferences)).where(User.id == user.id))
        user = result.scalar_one()

    prefs = user.preferences
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(prefs, field, value)
    await db.flush()
    return success_response({"updated": True})
