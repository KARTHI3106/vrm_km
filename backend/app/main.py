"""
Vendorsols — Vendor Risk Management System
FastAPI Application Entrypoint
"""

import os
import logging
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import get_settings
from app.api.routes import router
from app.api.phase3_routes import phase3_router
from app.core.vector import init_collections
from app.core.events import event_manager
from app.core.middleware import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    InputValidationMiddleware,
)


# ═══════════════════════════════════════════════════════════════════
# Logging Configuration
# ═══════════════════════════════════════════════════════════════════


def setup_logging():
    """Configure structured logging with structlog."""
    settings = get_settings()

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ═══════════════════════════════════════════════════════════════════
# Application Lifecycle
# ═══════════════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    setup_logging()
    logger = logging.getLogger(__name__)

    settings = get_settings()

    # Create upload directory
    os.makedirs(settings.upload_dir, exist_ok=True)

    # Initialize Qdrant collections
    try:
        init_collections()
        logger.info("Qdrant collections initialized")
    except Exception as e:
        logger.warning(f"Could not initialize Qdrant collections: {e}")

    await event_manager.start()

    logger.info(f"Vendorsols Vendor Risk Management System started (env={settings.app_env})")

    yield

    await event_manager.stop()
    logger.info("Vendorsols shutting down")


# ═══════════════════════════════════════════════════════════════════
# FastAPI Application
# ═══════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Vendorsols — Vendor Risk Management System",
    description=(
        "Multi-agent autonomous vendor risk assessment platform. "
        "Phase 3: All 8 agents — Intake, Security, Compliance, Financial, "
        "Evidence Coordinator, Risk Assessment, Approval Orchestrator, and Supervisor."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

# CORS + Security
app.add_middleware(InputValidationMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Include API routes
app.include_router(router)
app.include_router(phase3_router)


# ═══════════════════════════════════════════════════════════════════
# Root Endpoint
# ═══════════════════════════════════════════════════════════════════


@app.get("/")
async def root():
    """Root endpoint — system information."""
    return {
        "system": "Vendorsols — Vendor Risk Management System",
        "version": "3.0.0",
        "phase": "Phase 3: Production Ready",
        "agents": [
            "Supervisor Agent",
            "Document Intake Agent",
            "Security Review Agent",
            "Compliance Review Agent",
            "Financial Review Agent",
            "Evidence Coordinator Agent",
            "Risk Assessment Agent",
            "Approval Orchestrator Agent",
        ],
        "docs": "/docs",
        "health": "/api/v1/health",
    }
