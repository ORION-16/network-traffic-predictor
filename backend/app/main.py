"""Network Traffic Predictor — FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.interfaces import router as interfaces_router
from api.routes.capture import router as capture_router
from api.websockets import router as ws_router, close_all_connections
from capture.sniffer import stop_capture
from core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Network Traffic Predictor backend starting")
    yield
    # Clean shutdown: stop capture, close WS connections
    logger.info("Shutting down — stopping capture and closing connections")
    stop_capture()
    await close_all_connections()


app = FastAPI(
    title="Network Traffic Predictor",
    description="Phase 1 — Live network traffic monitoring and analysis",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(interfaces_router)
app.include_router(capture_router)
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
