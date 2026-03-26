"""SSE streaming chat endpoint: tokens stream progressively like ChatGPT."""

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Form, File, UploadFile
from fastapi.responses import StreamingResponse

from config import get_settings
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Chat"])


async def _resolve_file(file_id: str | None, file: UploadFile | None) -> tuple[bytes | None, str]:
    """Resolve file bytes from file_id (Redis) or direct upload."""
    settings = get_settings()
    filename = "upload.sav"

    if file_id:
        import redis.asyncio as aioredis
        if not settings.redis_url:
            return None, filename
        r = aioredis.from_url(settings.redis_url, decode_responses=False)
        try:
            file_bytes = await r.get(f"spss:file:{file_id}")
            meta_raw = await r.get(f"spss:meta:{file_id}")
            if meta_raw:
                meta_info = json.loads(meta_raw)
                filename = meta_info.get("filename", filename)
            ttl = settings.spss_session_ttl_seconds
            await r.expire(f"spss:file:{file_id}", ttl)
            await r.expire(f"spss:meta:{file_id}", ttl)
            await r.aclose()
            return file_bytes, filename
        except Exception:
            try:
                await r.aclose()
            except Exception:
                pass
            return None, filename
    elif file:
        file_bytes = await file.read()
        return file_bytes, file.filename or filename

    return None, filename


@router.post("/v1/chat-stream", summary="Streaming chat (SSE)")
async def chat_stream_endpoint(
    message: str = Form(...),
    file_id: str = Form(None),
    file: UploadFile = File(None),
    ticket: UploadFile = File(None),
    history: str = Form("[]"),
    prep_context: str = Form(""),
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

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            if not settings.anthropic_api_key:
                yield f"event: error\ndata: {json.dumps({'message': 'ANTHROPIC_API_KEY not configured'})}\n\n"
                return

            # Resolve file
            file_bytes, filename = await _resolve_file(file_id, file)
            if not file_bytes:
                yield f"event: error\ndata: {json.dumps({'message': 'File not found or expired. Re-upload.'})}\n\n"
                return

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
                    message += f"\n\n[SYSTEM: Reporting Ticket parsed. Spec: {json.dumps(ticket_spec)[:500]}. Generate the Excel tabulation using this spec.]"
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
            messages.append({"role": "user", "content": message})

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
                    model="claude-sonnet-4-20250514",
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
            yield f"event: done\ndata: {json.dumps({'response': final_text, 'charts': charts, 'downloads': downloads, 'tool_calls': tool_calls_log, 'model': 'claude-sonnet-4-20250514'})}\n\n"

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
