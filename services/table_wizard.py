"""Table Wizard Service — orchestrates Generate Tables using tabulation_builder.

Bridges the project-based API with the existing stateless tabulation engine.
The heavy lifting is done by tabulation_builder.py (81KB, the most mature module).
"""

import asyncio
import logging
from typing import Any

from services.quantipy_engine import QuantiProEngine, SPSSData
from services.tabulation_builder import (
    TabulateSpec,
    TabulationResult,
    build_tabulation,
    _build_excel,
)

logger = logging.getLogger(__name__)


async def generate_tables_preview(
    data: SPSSData,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Dry-run: show what tables will be generated without building Excel."""
    spec = _config_to_spec(data, config)

    return {
        "banners": [b.variable for b in spec.banner_columns] if hasattr(spec, 'banner_columns') else config.get("banners", []),
        "stubs": spec.stubs if hasattr(spec, 'stubs') else [],
        "n_tables": len(spec.stubs) if hasattr(spec, 'stubs') else 0,
        "significance_level": spec.significance_level,
        "include_means": spec.include_means,
        "weight": spec.weight,
    }


async def generate_tables_json(
    data: SPSSData,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Execute tabulation and return structured JSON results."""
    spec = _config_to_spec(data, config)

    result: TabulationResult = await asyncio.to_thread(
        build_tabulation, QuantiProEngine, data, spec
    )

    return {
        "title": result.title,
        "n_sheets": len(result.sheets),
        "sheets": [
            {
                "name": sheet.name,
                "stub": sheet.stub,
                "n_rows": len(sheet.rows) if hasattr(sheet, 'rows') else 0,
            }
            for sheet in result.sheets
        ],
        "banners": [b.variable for b in result.banner_columns] if hasattr(result, 'banner_columns') else [],
    }


async def generate_tables_excel(
    data: SPSSData,
    config: dict[str, Any],
) -> bytes:
    """Execute tabulation and return Excel bytes.

    This is the main output — delegates to tabulation_builder._build_excel().
    """
    spec = _config_to_spec(data, config)

    result: TabulationResult = await asyncio.to_thread(
        build_tabulation, QuantiProEngine, data, spec
    )

    excel_bytes: bytes = await asyncio.to_thread(
        _build_excel, result, spec, data
    )

    return excel_bytes


def _config_to_spec(data: SPSSData, config: dict[str, Any]) -> TabulateSpec:
    """Convert API config dict to TabulateSpec for tabulation_builder."""
    banners = config.get("banners", [])
    stubs = config.get("stubs", "_all_")
    if stubs == "_all_":
        # All non-banner variables
        stubs = [col for col in data.df.columns if col not in banners]

    spec = TabulateSpec()
    spec.banners = banners
    spec.stubs = stubs
    spec.significance_level = config.get("significance_level", 0.95)
    spec.weight = config.get("weight")
    spec.include_means = config.get("include_means", False)
    spec.nets = config.get("nets")
    spec.mrs_groups = config.get("mrs_groups")
    spec.grid_groups = config.get("grid_groups")
    spec.title = config.get("title", "Tabulation")
    if config.get("single_sheet"):
        spec.output_mode = "single_sheet"
    return spec
