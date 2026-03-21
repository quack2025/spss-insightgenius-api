"""POST /v1/process — Main endpoint: upload .sav + optional ticket/operations → full analysis."""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth import require_scope, KeyConfig
from config import get_settings
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine, QUANTIPYMRX_AVAILABLE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Processing"])


def _validate_upload(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "No filename provided"})
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("sav", "por", "zsav"):
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": f"Unsupported format '.{ext}'. Accepted: .sav, .por, .zsav"})


async def _execute_operation(data, op: dict, op_id: str) -> dict:
    """Execute a single analysis operation and return OperationResult."""
    op_type = op.get("type", "")
    variable = op.get("variable", "")
    params = op.get("params", {})
    weight = op.get("weight")

    try:
        if op_type == "frequency":
            result = await run_in_executor(QuantiProEngine.frequency, data, variable, weight)
        elif op_type == "crosstab":
            cross_var = op.get("cross_variable", "")
            sig = params.get("significance_level", 0.95)
            result = await run_in_executor(
                QuantiProEngine.crosstab_with_significance, data, variable, cross_var, weight, sig
            )
        elif op_type == "nps":
            result = await run_in_executor(QuantiProEngine.nps, data, variable, weight)
        elif op_type == "top_bottom_box":
            top_vals = params.get("top_values")
            bot_vals = params.get("bottom_values")
            result = await run_in_executor(QuantiProEngine.top_bottom_box, data, variable, top_vals, bot_vals)
        elif op_type == "nets":
            net_defs = params.get("net_definitions", {})
            result = await run_in_executor(QuantiProEngine.nets, data, variable, net_defs)
        else:
            return {"operation_id": op_id, "type": op_type, "variable": variable, "status": "error", "data": None, "error": f"Unknown operation type: {op_type}"}

        return {"operation_id": op_id, "type": op_type, "variable": variable, "status": "success", "data": result, "error": None}

    except (asyncio.TimeoutError, RuntimeError):
        raise  # handled by global exception handlers (504 / 503)
    except Exception as e:
        return {"operation_id": op_id, "type": op_type, "variable": variable, "status": "error", "data": None, "error": str(e)}


@router.post("/v1/process", summary="Full processing pipeline", description="Upload a .sav file with optional Reporting Ticket or manual operations spec. Returns metadata + all analysis results.")
async def process(
    request: Request,
    file: UploadFile = File(..., description="SPSS .sav file"),
    operations: str | None = Form(None, description="JSON array of operation specs"),
    ticket: UploadFile | None = File(None, description="Reporting Ticket .docx (optional)"),
    weight: str | None = Form(None, description="Default weight variable"),
    key: KeyConfig = Depends(require_scope("process")),
):
    start = time.perf_counter()
    _validate_upload(file)

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "Empty file"})

    # Load SPSS
    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, file.filename or "upload.sav")
    except (asyncio.TimeoutError, RuntimeError):
        raise
    except Exception as e:
        raise HTTPException(500, detail={"code": "PROCESSING_FAILED", "message": f"Failed to load SPSS: {e}"})

    # Extract metadata
    metadata = await run_in_executor(QuantiProEngine.extract_metadata, data)

    # Determine operations
    ops_list = []
    ticket_plan = None

    # 1. If ticket provided, parse it via Haiku
    if ticket and ticket.filename:
        settings = get_settings()
        if settings.anthropic_api_key:
            try:
                from services.ticket_parser import TicketParser
                ticket_bytes = await ticket.read()
                parser = TicketParser()
                ticket_plan = await parser.parse(ticket_bytes, metadata.get("variables", []))
                ops_list = ticket_plan.get("operations", [])
                if not weight and ticket_plan.get("weight"):
                    weight = ticket_plan["weight"]
            except Exception as e:
                logger.warning("Ticket parsing failed: %s", e)
                ticket_plan = {"raw_text": "", "operations": [], "notes": [f"Parsing failed: {e}"]}

    # 2. If explicit operations provided, use them (override ticket)
    if operations:
        try:
            parsed_ops = json.loads(operations)
            if isinstance(parsed_ops, list):
                ops_list = parsed_ops
        except json.JSONDecodeError:
            raise HTTPException(400, detail={"code": "INVALID_OPERATIONS", "message": "Invalid JSON in 'operations' field"})

    # 3. If neither, use auto_planner for default operations
    if not ops_list:
        try:
            from services.auto_planner import AutoPlanner
            ops_list = AutoPlanner.plan(metadata)
        except ImportError:
            # Auto planner not yet implemented — return metadata only
            ops_list = []
        except Exception as e:
            logger.warning("Auto planner failed: %s", e)

    # Apply default weight to operations that don't specify one
    for op in ops_list:
        if isinstance(op, dict) and not op.get("weight") and weight:
            op["weight"] = weight

    # Execute all operations in parallel
    tasks = [
        _execute_operation(data, op, f"op_{i+1}")
        for i, op in enumerate(ops_list)
    ]
    results = await asyncio.gather(*tasks) if tasks else []

    return {
        "success": True,
        "data": {
            "metadata": metadata,
            "results": list(results),
            "ticket_plan": ticket_plan,
        },
        "meta": {
            "request_id": getattr(request.state, "request_id", ""),
            "processing_time_ms": int((time.perf_counter() - start) * 1000),
            "engine_version": "1.0.0",
            "quantipymrx_available": QUANTIPYMRX_AVAILABLE,
        },
    }
