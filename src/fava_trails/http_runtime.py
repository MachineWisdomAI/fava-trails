"""Loopback Streamable HTTP runtime for the FAVA Trails MCP server."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import DEFAULT_FAVA_HOME, ConfigStore
from .readiness import DEFAULT_READINESS_TIMEOUT_SECONDS, ReadinessFailure, probe_data_repository


class _McpASGIApp:
    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await self._session_manager.handle_request(scope, receive, send)


def create_streamable_http_app() -> Starlette:
    """Create a Starlette app exposing the existing MCP server at /mcp."""
    from . import server as fava_server

    session_manager = StreamableHTTPSessionManager(
        app=fava_server.server,
        stateless=False,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette):
        ConfigStore.reset()
        await fava_server._init_server()
        async with session_manager.run():
            yield

    async def healthz(request) -> JSONResponse:
        data_repo = Path(os.environ.get("FAVA_TRAILS_DATA_REPO", DEFAULT_FAVA_HOME)).expanduser()
        try:
            data_state = await asyncio.wait_for(
                asyncio.to_thread(
                    probe_data_repository,
                    data_repo,
                    timeout_seconds=DEFAULT_READINESS_TIMEOUT_SECONDS,
                ),
                timeout=DEFAULT_READINESS_TIMEOUT_SECONDS + 0.1,
            )
        except ReadinessFailure as exc:
            return JSONResponse(
                {
                    "status": "not_ready",
                    "runtime": "fava-trails-tunnel",
                    "reason": exc.reason,
                    "message": exc.message,
                },
                status_code=503,
            )
        except TimeoutError:
            return JSONResponse(
                {
                    "status": "not_ready",
                    "runtime": "fava-trails-tunnel",
                    "reason": "probe_timeout",
                    "message": "data readiness probe exceeded its time limit",
                },
                status_code=503,
            )
        except Exception:  # noqa: BLE001 - readiness must fail closed without leaking internals
            return JSONResponse(
                {
                    "status": "not_ready",
                    "runtime": "fava-trails-tunnel",
                    "reason": "readiness_probe_failed",
                    "message": "data readiness probe failed",
                },
                status_code=503,
            )
        return JSONResponse({
            "status": "ok",
            "runtime": "fava-trails-tunnel",
            "data": data_state,
        })

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route("/healthz", endpoint=healthz, methods=["GET"]),
            Mount("/mcp", app=_McpASGIApp(session_manager)),
        ],
    )


def run_streamable_http_server(*, host: str, port: int, log_level: str = "info") -> None:
    """Run the loopback Streamable HTTP MCP server until interrupted."""
    import uvicorn

    app = create_streamable_http_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        lifespan="on",
    )
    uvicorn.Server(config).run()
