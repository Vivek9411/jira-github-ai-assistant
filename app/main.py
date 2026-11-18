"""FastAPI Application Entry Point."""

from contextlib import asynccontextmanager
import logging
import os
from collections.abc import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("jira_gh_assistant")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event handler for application startup and graceful shutdown."""
    logger.info("Initializing %s in %s mode...", settings.APP_NAME, settings.ENVIRONMENT)

    # In development mode, auto-create tables if they don't exist
    if settings.DEBUG:
        try:
            async with engine.begin() as conn:
                try:
                    from sqlalchemy import text
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                except Exception as exc:
                    logger.warning("Could not create vector extension automatically: %s", exc)
                await conn.run_sync(Base.metadata.create_all)
                logger.info("Database tables initialized successfully.")
        except Exception as exc:
            logger.warning(
                "Could not connect to PostgreSQL on startup (%s). App will continue running; ensure database is started for DB-backed operations.",
                exc,
            )

    yield

    logger.info("Shutting down %s...", settings.APP_NAME)
    await engine.dispose()
    logger.info("Database connection pool closed.")


app = FastAPI(
    title=settings.APP_NAME,
    description="Intelligent Jira + GitHub assistant for PMs & Developers with Hybrid RAG & Text-to-JQL.",
    version="0.1.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict to configured client origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(api_v1_router)

# Mount Static UI Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
@app.get("/login", include_in_schema=False)
async def serve_index() -> FileResponse:
    """Serve web chat dashboard UI and login view."""
    index_file = os.path.join(static_dir, "index.html")
    return FileResponse(index_file)


@app.get("/health", tags=["Health"], summary="Health Check")
async def health_check() -> dict[str, str]:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }
