"""
API Routes - FastAPI endpoints for job submission and status checking.

These endpoints are designed to be extremely fast and lightweight:
- POST /jobs: Accepts a job and pushes it to the queue immediately
- GET /jobs/{job_id}: Retrieves job status from Redis

The API never performs heavy processing - all work is delegated to
the background worker via the Redis queue.
"""

import logging
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from ..core.utils import generate_job_id, get_timestamp
from ..models.schemas import (
    JobPayload,
    JobAcceptedResponse,
    JobStatusResponse,
    JobNotFoundResponse,
    HealthResponse,
    ErrorResponse
)
from ..queue.producer import producer
from ..storage.results import results_storage

# Configure logging
logger = logging.getLogger(__name__)

# Create the router
router = APIRouter()


# ============================================================
# Job Endpoints
# ============================================================

@router.post(
    "/jobs",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a new job",
    description="""
    Submit a job for background processing.
    
    This endpoint:
    - Accepts the job payload immediately
    - Generates a unique job ID
    - Pushes the job to the Redis queue
    - Returns without waiting for processing
    
    The job will be processed by the background worker. Use the
    returned job_id to poll for status via GET /jobs/{job_id}.
    
    **Important**: This endpoint is designed to handle massive traffic
    spikes. It will accept requests even if the queue is very long,
    as jobs are stored durably in Redis.
    """,
    responses={
        202: {"description": "Job accepted for processing"},
        500: {"model": ErrorResponse, "description": "Failed to enqueue job"}
    }
)
async def create_job(payload: JobPayload) -> JobAcceptedResponse:
    """
    Create a new job and add it to the processing queue.
    
    This endpoint is intentionally simple and fast:
    1. Generate a unique job ID
    2. Push job to Redis queue
    3. Return immediately
    
    No heavy processing happens here - that's the worker's job.
    """
    # Generate unique job ID
    job_id = generate_job_id()
    
    logger.info(f"Received job request: {job_id}")
    
    # Convert payload to dictionary for queue
    job_data = payload.model_dump()
    
    # Attempt to enqueue the job
    success = await producer.enqueue_job(job_id, job_data)
    
    if not success:
        # This should be rare - Upstash is highly available
        # But we handle it gracefully
        logger.error(f"Failed to enqueue job {job_id}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue job at this time. Please retry."
        )
    
    logger.info(f"Job {job_id} enqueued successfully")
    
    return JobAcceptedResponse(
        status="accepted",
        job_id=job_id,
        message="Job queued successfully. Poll GET /jobs/{job_id} for status."
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="""
    Retrieve the current status of a job.
    
    Possible status values:
    - **queued**: Job is waiting in the queue
    - **processing**: Job is currently being processed
    - **done**: Job completed successfully (result included)
    - **failed**: Job processing failed (error message included)
    
    Poll this endpoint to track job progress. When status is "done",
    the response will include the processing result.
    """,
    responses={
        200: {"description": "Job status retrieved"},
        404: {"model": JobNotFoundResponse, "description": "Job not found"}
    }
)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """
    Get the current status of a job by its ID.
    
    This endpoint queries Redis for the job's current state
    and returns it to the client for polling-based updates.
    """
    logger.debug(f"Status check for job: {job_id}")
    
    # Retrieve job status from storage
    job_status = await results_storage.get_job_status(job_id)
    
    if job_status is None:
        # Job not found - either invalid ID or expired
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found or has expired"
        )
    
    return job_status


# ============================================================
# Utility Endpoints
# ============================================================

@router.get(
    "/queue/stats",
    summary="Get queue statistics",
    description="Get current queue length and estimated wait time."
)
async def get_queue_stats():
    """
    Get current queue statistics.
    
    Useful for clients to understand system load before submitting jobs.
    """
    stats = await results_storage.get_queue_stats()
    return {
        "queue_length": stats["queue_length"],
        "estimated_wait_seconds": stats["estimated_total_wait_seconds"],
        "timestamp": get_timestamp()
    }


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check the health of the API and its dependencies."
)
async def health_check() -> HealthResponse:
    """
    Perform a health check.
    
    Verifies that the API can connect to Upstash Redis.
    """
    # Check Redis connectivity
    redis_healthy = await producer.health_check()
    
    from ..core.config import settings
    
    return HealthResponse(
        status="healthy" if redis_healthy else "degraded",
        service="overload-safe-queue-api",
        version=settings.api_version,
        queue_connected=redis_healthy,
        timestamp=get_timestamp()
    )
