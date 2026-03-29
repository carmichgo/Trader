"""FastAPI application entry point with CORS, lifespan, and middleware."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from packages.core.config import SystemConfig
from packages.core.db.postgres import async_engine, init_db, dispose_engine, reconfigure_engine
from packages.core.db.timescale import setup_hypertables

from api.deps import get_config, init_redis, close_redis
from api.websocket import router as ws_router
from api.routes.portfolio import router as portfolio_router
from api.routes.trades import router as trades_router
from api.routes.ai_logs import router as ai_logs_router
from api.routes.costs import router as costs_router
from api.routes.risk import router as risk_router
from api.routes.goal import router as goal_router
from api.routes.controls import router as controls_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialise DB and Redis on startup, clean up on shutdown."""
    config = get_config()

    # -- Startup ---------------------------------------------------------------
    logger.info("app_startup", env=config.env, debug=config.debug)

    # Reconfigure engine from resolved config
    reconfigure_engine(
        url=config.database.url,
        echo=config.database.echo,
        pool_size=config.database.pool_size,
        max_overflow=config.database.max_overflow,
    )

    # Create tables (dev convenience; production uses Alembic)
    await init_db()
    logger.info("database_initialised")

    # TimescaleDB hypertables
    try:
        await setup_hypertables()
        logger.info("hypertables_configured")
    except Exception:
        logger.warning("hypertable_setup_skipped", reason="TimescaleDB may not be available")

    # Redis
    await init_redis(config.redis.url)
    logger.info("redis_connected", url=config.redis.host)

    yield

    # -- Shutdown --------------------------------------------------------------
    logger.info("app_shutdown")
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    config = get_config()

    app = FastAPI(
        title="AI Trading System API",
        version="0.1.0",
        description="REST + WebSocket API for the autonomous AI trading system.",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # -- CORS ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Custom middleware: request logging + timing ----------------------------
    app.add_middleware(RequestTimingMiddleware)

    # -- Routers ---------------------------------------------------------------
    app.include_router(portfolio_router)
    app.include_router(trades_router)
    app.include_router(ai_logs_router)
    app.include_router(costs_router)
    app.include_router(risk_router)
    app.include_router(goal_router)
    app.include_router(controls_router)
    app.include_router(ws_router)

    # -- Health check ----------------------------------------------------------
    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status, and duration."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        return response


app = create_app()
