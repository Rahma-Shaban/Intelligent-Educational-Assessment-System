"""FastAPI application entrypoint for Intelligent Educational Assessment System."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import inspect, text
from app.database import Base, engine
from app.routers import (
    analytics_router,
    attempt_router,
    auth_router,
    curriculum_router,
    exam_router,
)
from scripts.config import LLM_PROVIDER
from scripts.generation import validate_configuration

app = FastAPI(
    title="Intelligent Educational Assessment System API",
    description=(
        "Production-grade FastAPI backend featuring curriculum RAG ingestion, "
        "Bloom-aligned exam generation with Gemini, automated multi-format grading, "
        "and student analytics clustering."
    ),
    version="1.0.0",
)

# CORS middleware configuration
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    """Initialize SQLite database tables and ensure schema migrations."""
    Base.metadata.create_all(bind=engine)
    try:
        with engine.connect() as conn:
            inspector = inspect(engine)
            if "exams" in inspector.get_table_names():
                cols = [c["name"] for c in inspector.get_columns("exams")]
                if "is_published" not in cols:
                    conn.execute(text("ALTER TABLE exams ADD COLUMN is_published BOOLEAN DEFAULT 0"))
                    conn.commit()
    except Exception:
        pass


# Mount feature routers with designated API prefixes
app.include_router(auth_router.router, prefix="/api/auth")
app.include_router(curriculum_router.router, prefix="/api/curriculum")
app.include_router(exam_router.router, prefix="/api/exams")
app.include_router(attempt_router.router, prefix="/api/attempts")
app.include_router(analytics_router.router, prefix="/api/analytics")


@app.get(
    "/api/health",
    summary="Health and LLM configuration verification",
    tags=["System"],
)
def health_check() -> dict[str, Any]:
    """
    Checks system status, API readiness, and validates Google Gemini credentials.
    """
    is_valid, missing, model_name = validate_configuration()
    return {
        "status": "healthy" if is_valid else "degraded",
        "llm_ready": is_valid,
        "missing_config": missing,
        "active_model": model_name,
        "active_provider": LLM_PROVIDER,
    }


@app.get("/", tags=["System"], include_in_schema=False)
def root() -> dict[str, str]:
    """Root redirect / welcoming endpoint."""
    return {
        "name": "Intelligent Educational Assessment System API",
        "docs_url": "/docs",
        "status": "online",
    }
