"""Metadata extraction service — extracts variable info from SPSS files.

Reuses quantipy_engine.py for the actual extraction work.
Stores metadata in the database for project-based features.
"""

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.project import DatasetMetadata, Project, ProjectFile, ProjectStatus
from services.quantipy_engine import QuantiProEngine, SPSSData

logger = logging.getLogger(__name__)


async def extract_and_store_metadata(
    db: AsyncSession,
    project: Project,
    file_record: ProjectFile,
    file_bytes: bytes,
) -> DatasetMetadata:
    """Extract metadata from an SPSS file and store it in the database.

    Uses quantipy_engine.load_spss() for parsing and extract_metadata() for
    variable information. This runs in a thread to avoid blocking the event loop.
    """
    try:
        # Load SPSS in thread (blocking I/O)
        spss_data: SPSSData = await asyncio.to_thread(
            QuantiProEngine.load_spss, file_bytes
        )

        # Extract metadata
        meta_dict: dict[str, Any] = await asyncio.to_thread(
            QuantiProEngine.extract_metadata, spss_data
        )

        n_cases = len(spss_data.df)
        n_variables = len(spss_data.df.columns)
        variables = meta_dict.get("variables", [])

        # Create or update dataset metadata
        dataset_meta = DatasetMetadata(
            project_id=project.id,
            n_cases=n_cases,
            n_variables=n_variables,
            variables=variables,
            basic_frequencies={},
            basic_stats={},
            variable_profiles=[],
        )
        db.add(dataset_meta)

        # Mark project as ready
        project.status = ProjectStatus.READY
        project.error_message = None
        await db.flush()

        logger.info(
            "Extracted metadata for project %s: %d cases, %d variables",
            project.id, n_cases, n_variables,
        )
        return dataset_meta

    except Exception as e:
        # Mark project as error
        project.status = ProjectStatus.ERROR
        project.error_message = str(e)[:500]
        await db.flush()
        logger.error("Metadata extraction failed for project %s: %s", project.id, e)
        raise


async def extract_metadata_from_bytes(file_bytes: bytes) -> dict[str, Any]:
    """Extract metadata without storing — useful for stateless API endpoints.

    Returns dict with: n_cases, n_variables, variables list.
    """
    spss_data = await asyncio.to_thread(QuantiProEngine.load_spss, file_bytes)
    meta_dict = await asyncio.to_thread(QuantiProEngine.extract_metadata, spss_data)

    return {
        "n_cases": len(spss_data.df),
        "n_variables": len(spss_data.df.columns),
        "variables": meta_dict.get("variables", []),
    }
