"""
FastAPI Application Entry Point

This is the main application module that configures and runs the
overload-safe, queue-based API server.

The API is designed to:
- Accept requests instantly without blocking
- Push all jobs to Upstash Redis queue
- Never perform heavy processing in the request lifecycle
- Remain responsive under massive traffic spikes
- Never return 5xx errors due to overload

Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .core.config import settings
from .core.utils import get_timestamp
from .api.routes import router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# Application Lifespan Handler
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown events:
    - Startup: Verify Redis connectivity, log configuration
    - Shutdown: Clean up resources (if any)
    """
    # ---- Startup ----
    logger.info("=" * 60)
    logger.info("OVERLOAD-SAFE QUEUE API STARTING")
    logger.info("=" * 60)
    logger.info(f"Server Port: {settings.server_port}")
    logger.info(f"API Version: {settings.api_version}")
    logger.info(f"Queue Key: {settings.queue.job_queue_key}")
    logger.info(f"Result TTL: {settings.queue.result_ttl}s")
    
    # Verify Redis connectivity
    from .queue.producer import producer
    if await producer.health_check():
        logger.info("✓ Upstash Redis connection verified")
    else:
        logger.warning("⚠ Could not verify Upstash Redis connection")
    
    logger.info("=" * 60)
    logger.info(f"API ready to accept requests on port {settings.server_port}")
    logger.info("=" * 60)
    
    yield  # Application runs here
    
    # ---- Shutdown ----
    logger.info("API shutting down...")


# ============================================================
# FastAPI Application Instance
# ============================================================

app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)


# ============================================================
# Middleware Configuration
# ============================================================

# CORS middleware - configure for your deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Exception Handlers
# ============================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
):
    """
    Handle validation errors with a clean response.
    
    Returns 422 with details about what failed validation.
    """
    logger.warning(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation failed",
            "detail": exc.errors(),
            "timestamp": get_timestamp()
        }
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler to prevent 500 errors from crashing the API.
    
    This ensures that unexpected errors are logged but don't bring
    down the entire service. The API remains available even when
    individual requests fail.
    """
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred. Please try again.",
            "timestamp": get_timestamp()
        }
    )


# ============================================================
# Route Registration
# ============================================================

# Include the main API routes
app.include_router(router, tags=["Jobs"])


# ============================================================
# Root Endpoint
# ============================================================

@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint with API information.
    
    Provides basic info and links to documentation.
    """
    return {
        "service": settings.api_title,
        "version": settings.api_version,
        "description": settings.api_description,
        "endpoints": {
            "submit_job": "POST /jobs",
            "check_status": "GET /jobs/{job_id}",
            "queue_stats": "GET /queue/stats",
            "health": "GET /health",
            "docs": "GET /docs"
        },
        "timestamp": get_timestamp()
    }


# ============================================================
# Run Configuration (for direct execution)
# ============================================================

if __name__ == "__main__":
    import os
    import uvicorn
    
    # Cloud servers often set PORT env var
    port = int(os.getenv("PORT", "8000"))
    
    print("=" * 60)
    print("OVERLOAD-SAFE QUEUE API")
    print("=" * 60)
    print(f"Binding to 0.0.0.0:{port}")
    print(f"Docs: http://localhost:{port}/docs")
    print("=" * 60)
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=1,
        log_level="info"
    )
