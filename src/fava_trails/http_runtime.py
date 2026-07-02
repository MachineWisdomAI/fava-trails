"""Loopback Streamable HTTP runtime for the FAVA Trails MCP server."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import ConfigStore, get_data_repo_root, get_trails_dir


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
        data_repo = get_data_repo_root()
        trails_dir = get_trails_dir()
        return JSONResponse(
            {
                "status": "ok",
                "runtime": "fava-trails-tunnel",
                "data_repo": str(data_repo),
                "trails_dir": str(trails_dir),
            }
        )

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
