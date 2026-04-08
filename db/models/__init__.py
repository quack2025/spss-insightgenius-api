"""Database models package.

Import all models here so Alembic can discover them via Base.metadata.
"""

from db.models.user import User, UserPreferences  # noqa: F401
from db.models.project import Project, ProjectFile, DatasetMetadata  # noqa: F401
