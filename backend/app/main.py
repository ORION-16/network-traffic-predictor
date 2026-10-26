"""Network Traffic Predictor — FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.interfaces import router as interfaces_router
from api.routes.capture import router as capture_router
from api.routes.monitoring import router as monitoring_router
from api.websockets import router as ws_router, close_all_connections
from capture.sniffer import stop_capture
from core.config import settings
from monitoring.collector import monitoring_collector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Network Traffic Predictor backend starting")
    try:
        monitoring_collector.start()
    except Exception:
        logger.exception("Interface collector failed to start")
    yield
    # Clean shutdown: stop capture, stop counter collection, close WS connections
    logger.info("Shutting down — stopping capture and closing connections")
    stop_capture()
    monitoring_collector.stop()
    await close_all_connections()


app = FastAPI(
    title="Network Traffic Predictor",
    description="Live interface-counter monitoring, statistical forecasting, and optional packet capture",
    version="0.2.0",
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
app.include_router(monitoring_router)
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "monitoring": monitoring_collector.health(),
    }
