"""MCP SSE transport with Redis pub/sub relay for cross-replica session routing.

Railway with numReplicas > 1: the SSE GET and the POST /messages/ may land on
different replicas. Sessions (MemoryObjectSendStream) are in-memory and can't
cross processes, so we relay via Redis pub/sub:

  POST on Replica B (session not found locally):
    -> publish body to Redis `mcp:msg:{session_id}`
    -> return 202 Accepted

  Replica A (owns the session, subscribed to `mcp:msg:*`):
    -> receives pub/sub message
    -> writes JSON-RPC body to local stream
    -> FastMCP processes it and responds via the SSE connection

If REDIS_URL is not set, the relay is disabled (single-replica mode).
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

import mcp.types as types
import redis.asyncio as aioredis
from mcp.server.sse import SseServerTransport
from mcp.shared.message import SessionMessage
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from config import get_settings

logger = logging.getLogger(__name__)

# Module-level SSE transport — shared between the ASGI app routes and the relay.
# endpoint is the path the client POSTs to (relative to this app's mount point).
_sse_transport = SseServerTransport("/messages/")

# Persistent Redis client for publishing (connection-pooled).
_redis_pub: aioredis.Redis | None = None

# Background task handle for the pub/sub subscriber loop.
_redis_subscriber_task: asyncio.Task | None = None


async def _redis_subscriber_loop() -> None:
    """Subscribe to `mcp:msg:*` and forward messages to local SSE sessions.

    Runs as a background task (started by start_redis_relay).
    Retries with exponential back-off on connection failure.
    """
    settings = get_settings()
    redis_url = settings.redis_url
    retry_delay = 1.0

    while True:
        try:
            async with aioredis.from_url(redis_url, decode_responses=False) as sub_redis:
                pubsub = sub_redis.pubsub()
                await pubsub.psubscribe("mcp:msg:*")
                logger.info("MCP Redis relay: subscribed to mcp:msg:*")
                retry_delay = 1.0  # reset on successful connect

                async for message in pubsub.listen():
                    if message["type"] != "pmessage":
                        continue

                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()

                    # channel format: mcp:msg:{session_id_hex}
                    session_id_hex = channel.split(":")[-1]
                    try:
                        session_id = UUID(hex=session_id_hex)
                    except ValueError:
                        continue

                    writer = _sse_transport._read_stream_writers.get(session_id)
                    if not writer:
                        continue  # session lives on another replica — ignore

                    body = message["data"]
                    try:
                        msg = types.JSONRPCMessage.model_validate_json(body)
                        await writer.send(SessionMessage(msg))
                        logger.debug(
                            "MCP Redis relay: forwarded message for session %.8s",
                            session_id_hex,
                        )
                    except Exception as exc:
                        logger.warning(
                            "MCP Redis relay: failed to deliver message for session %.8s: %s",
                            session_id_hex, exc,
                        )

        except asyncio.CancelledError:
            logger.info("MCP Redis relay: subscriber stopped")
            return
        except Exception as exc:
            logger.warning(
                "MCP Redis relay: connection error (%s) — retrying in %.1fs",
                exc, retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


async def start_redis_relay() -> None:
    """Start the Redis pub/sub relay. Called from the FastAPI app lifespan."""
    global _redis_pub, _redis_subscriber_task
    settings = get_settings()
    if not settings.redis_url:
        logger.warning(
            "MCP Redis relay: REDIS_URL not set — POST /mcp/messages/ will return 404 "
            "when Railway routes SSE and POST to different replicas (numReplicas > 1). "
            "Set REDIS_URL to enable cross-replica session routing."
        )
        return

    _redis_pub = aioredis.from_url(settings.redis_url, decode_responses=False)
    _redis_subscriber_task = asyncio.create_task(_redis_subscriber_loop())
    logger.info("MCP Redis relay started (REDIS_URL configured)")


async def stop_redis_relay() -> None:
    """Stop the Redis pub/sub relay. Called from the FastAPI app lifespan."""
    global _redis_pub, _redis_subscriber_task
    if _redis_subscriber_task:
        _redis_subscriber_task.cancel()
        try:
            await _redis_subscriber_task
        except asyncio.CancelledError:
            pass
        _redis_subscriber_task = None
    if _redis_pub:
        await _redis_pub.aclose()
        _redis_pub = None


async def _handle_post_with_redis(scope: Any, receive: Any, send: Any) -> None:
    """POST /messages/ handler with Redis relay for cross-replica session routing.

    If the session_id from the query string is owned by this replica, the
    message is handled locally (standard FastMCP path).

    If the session is on another replica, the raw JSON body is published to
    `mcp:msg:{session_id}` in Redis so the owning replica can deliver it.
    """
    request = Request(scope, receive)
    session_id_param = request.query_params.get("session_id")

    if session_id_param:
        try:
            session_id = UUID(hex=session_id_param)
        except ValueError:
            # Invalid UUID — let the transport return 400
            await _sse_transport.handle_post_message(scope, receive, send)
            return

        if session_id not in _sse_transport._read_stream_writers:
            if _redis_pub is not None:
                body = await request.body()
                try:
                    subscriber_count = await _redis_pub.publish(
                        f"mcp:msg:{session_id_param}", body
                    )
                    if subscriber_count == 0:
                        logger.warning(
                            "MCP Redis relay: no subscriber for session %.8s — "
                            "session may have expired",
                            session_id_param,
                        )
                        response = Response("Could not find session", status_code=404)
                    else:
                        response = Response("Accepted", status_code=202)
                    await response(scope, receive, send)
                    return
                except Exception as exc:
                    logger.error("MCP Redis relay: publish failed: %s", exc)
                    response = Response("Service unavailable", status_code=503)
                    await response(scope, receive, send)
                    return
            # Redis not configured — fall through to local handler (returns 404)

    await _sse_transport.handle_post_message(scope, receive, send)


def get_mcp_asgi_app(mcp_instance):
    """Return the MCP SSE ASGI app for mounting in the main FastAPI app.

    SSE endpoint:  GET  /mcp/sse
    Post endpoint: POST /mcp/messages/

    Sessions are relayed across Railway replicas via Redis pub/sub when
    REDIS_URL is set (see start_redis_relay / stop_redis_relay).

    Args:
        mcp_instance: The FastMCP instance with registered tools.
    """

    async def handle_sse(scope: Any, receive: Any, send: Any) -> Response:
        async with _sse_transport.connect_sse(scope, receive, send) as streams:
            await mcp_instance._mcp_server.run(
                streams[0],
                streams[1],
                mcp_instance._mcp_server.create_initialization_options(),
            )
        return Response()

    async def sse_endpoint(request: Request) -> Response:
        return await handle_sse(request.scope, request.receive, request._send)  # type: ignore[reportPrivateUsage]

    return Starlette(routes=[
        Route("/sse", endpoint=sse_endpoint, methods=["GET"]),
        Mount("/messages/", app=_handle_post_with_redis),
    ])
