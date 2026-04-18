"""SSE streaming chat endpoint: tokens stream progressively like ChatGPT."""

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Form, File, UploadFile
from fastapi.responses import StreamingResponse

from auth import require_auth, KeyConfig
from config import get_settings
from middleware.processing import run_in_executor
from middleware.rate_limiter import check_rate_limit
from services.quantipy_engine import QuantiProEngine
from shared.file_resolver import resolve_file as shared_resolve_file

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Chat"])


@router.post("/v1/chat-stream", summary="Streaming chat (SSE)")
async def chat_stream_endpoint(
    message: str = Form(...),
    file_id: str = Form(None),
    file: UploadFile = File(None),
    ticket: UploadFile = File(None),
    history: str = Form("[]"),
    prep_context: str = Form(""),
    key: KeyConfig = Depends(require_auth),
    _rl: None = Depends(check_rate_limit),
):
    """Stream chat response via SSE. Events:
    - `text`: partial text token
    - `tool_start`: tool execution started {tool, input}
    - `tool_end`: tool execution finished {tool, result_summary}
    - `chart`: chart specification
    - `download`: download URL
    - `done`: final message with complete response
    - `error`: error occurred
    """
    settings = get_settings()

    # Capture message in a mutable container for the inner generator
    _msg = [message]

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            if not settings.anthropic_api_key:
                yield f"event: error\ndata: {json.dumps({'message': 'ANTHROPIC_API_KEY not configured'})}\n\n"
                return

            # Resolve file
            file_bytes, filename = await shared_resolve_file(file=file, file_id=file_id)

            # Load data
            data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)

            # Parse context
            history_parsed = json.loads(history) if history else []
            prep_ctx = json.loads(prep_context) if prep_context else None

            # Parse ticket if provided
            if ticket and ticket.filename and ticket.filename.endswith('.docx'):
                try:
                    ticket_bytes = await ticket.read()
                    from services.ticket_parser import TicketParser
                    parser = TicketParser()
                    meta = await run_in_executor(QuantiProEngine.extract_metadata, data)
                    var_list = [v["name"] for v in (meta.get("variables") or [])]
                    ticket_spec = await parser.parse(ticket_bytes, var_list)
                    _msg[0] += f"\n\n[SYSTEM: Reporting Ticket parsed. Spec: {json.dumps(ticket_spec)[:500]}. Generate the Excel tabulation using this spec.]"
                except Exception as e:
                    logger.warning("[STREAM] Ticket parsing failed: %s", e)

            # Initialize chat service
            from services.chat_service import ChatService, ANALYSIS_TOOLS, _build_metadata_context, _execute_tool
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            metadata_context = _build_metadata_context(data)

            # Build system prompt (same as ChatService.chat)
            from services.chat_service import SYSTEM_PROMPT
            prep_section = ""
            if prep_ctx:
                lines = ["\n\nUSER-CONFIRMED DATA STRUCTURE:"]
                mrs = prep_ctx.get("mrs_groups", [])
                if mrs:
                    lines.append(f"\nMRS Groups ({len(mrs)}):")
                    for g in mrs:
                        lines.append(f"  - {g.get('name','?')}: {g.get('variables',[])}")
                grids = prep_ctx.get("grid_groups", [])
                if grids:
                    lines.append(f"\nGrid Batteries ({len(grids)}):")
                    for g in grids:
                        lines.append(f"  - {g.get('name','?')}: {g.get('variables',[])}")
                demos = prep_ctx.get("demographics", [])
                if demos:
                    lines.append(f"\nDemographics: {demos}")
                wt = prep_ctx.get("weight")
                if wt:
                    lines.append(f"\nWeight: {wt}")
                study_ctx = prep_ctx.get("study_context")
                if study_ctx:
                    lines.append(f"\n\nSTUDY BRIEF:\n{study_ctx}")
                prep_section = "\n".join(lines)

            system = SYSTEM_PROMPT + f"\n\nDATASET CONTEXT:\n{metadata_context}{prep_section}"

            # Build messages
            messages = []
            if history_parsed:
                for h in history_parsed[-10:]:
                    messages.append(h)
            messages.append({"role": "user", "content": _msg[0]})

            charts = []
            downloads = []
            tool_calls_log = []
            full_text = ""

            # Streaming tool-use loop
            for round_num in range(5):
                # Stream Sonnet's response
                text_parts = []
                tool_uses = []
                content_blocks = []

                async with client.messages.stream(
                    model="claude-sonnet-4-6",
                    max_tokens=4096,
                    system=system,
                    tools=ANALYSIS_TOOLS,
                    messages=messages,
                ) as stream:
                    async for event in stream:
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "text"):
                                yield f"event: text\ndata: {json.dumps({'text': event.delta.text})}\n\n"
                                text_parts.append(event.delta.text)

                    # Get final message
                    response = await stream.get_final_message()

                # Collect blocks
                for block in response.content:
                    content_blocks.append(block)
                    if block.type == "tool_use":
                        tool_uses.append(block)

                # If no tool calls, we're done
                if not tool_uses:
                    break

                # Execute tools
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for tool_use in tool_uses:
                    tool_name = tool_use.name
                    tool_input = tool_use.input

                    yield f"event: tool_start\ndata: {json.dumps({'tool': tool_name, 'input_summary': str(tool_input)[:200]})}\n\n"

                    tool_calls_log.append({"tool": tool_name, "input": tool_input})

                    if tool_name == "show_chart":
                        charts.append(tool_input)
                        yield f"event: chart\ndata: {json.dumps(tool_input)}\n\n"
                        result_content = json.dumps({"rendered": True})
                    else:
                        result = await _execute_tool(tool_name, tool_input, data)
                        if "download_url" in result:
                            downloads.append(result["download_url"])
                            yield f"event: download\ndata: {json.dumps({'url': result['download_url']})}\n\n"
                        result_content = json.dumps(result, default=str)

                    yield f"event: tool_end\ndata: {json.dumps({'tool': tool_name})}\n\n"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result_content[:50000],
                    })

                messages.append({"role": "user", "content": tool_results})

            # Final text
            final_text = ""
            for block in response.content:
                if block.type == "text":
                    final_text += block.text
            if not final_text:
                final_text = "".join(text_parts)

            # Send done event with full data
            yield f"event: done\ndata: {json.dumps({'response': final_text, 'charts': charts, 'downloads': downloads, 'tool_calls': tool_calls_log, 'model': 'claude-sonnet-4-6'})}\n\n"

        except Exception as e:
            logger.error("Stream error: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
