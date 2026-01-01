"""
Pydantic models for request/response validation.

Defines the data contracts for the API, ensuring type safety
and automatic validation of incoming requests and outgoing responses.
"""

from pydantic import BaseModel, Field
from typing import Any, Optional
from enum import Enum


class JobStatus(str, Enum):
    """
    Enumeration of possible job states.
    
    Jobs transition through states: queued → processing → done
    Failed jobs may also exist if processing encounters errors.
    """
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


# ============================================================
# Request Models
# ============================================================

class JobPayload(BaseModel):
    """
    The payload for creating a new job.
    
    This is a demo payload structure - in production, this would
    be customized to match your specific business requirements.
    
    Attributes:
        name: A descriptive name for the job
        value: A numeric value for demo processing
        message: An optional message to include in processing
        metadata: Optional additional key-value pairs
    """
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="A descriptive name for the job",
        examples=["my-demo-job"]
    )
    value: int = Field(
        default=0,
        ge=0,
        le=1000000,
        description="A numeric value for demo processing"
    )
    message: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="An optional message to include"
    )
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional additional metadata"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "demo-job",
                "value": 42,
                "message": "Hello, World!",
                "metadata": {"priority": "normal"}
            }
        }


# ============================================================
# Response Models
# ============================================================

class JobAcceptedResponse(BaseModel):
    """
    Response returned when a job is successfully queued.
    
    This is returned immediately after the job is pushed to the queue,
    without waiting for processing to complete.
    """
    status: str = Field(
        default="accepted",
        description="Indicates the job was accepted for processing"
    )
    job_id: str = Field(
        ...,
        description="Unique identifier to track the job"
    )
    message: str = Field(
        default="Job queued successfully. Poll GET /jobs/{job_id} for status.",
        description="Helpful message for the client"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "accepted",
                "job_id": "job_a1b2c3d4e5f6",
                "message": "Job queued successfully. Poll GET /jobs/{job_id} for status."
            }
        }


class JobQueuedStatus(BaseModel):
    """Response when job is still waiting in the queue."""
    status: JobStatus = JobStatus.QUEUED
    job_id: str
    queue_position: Optional[int] = Field(
        default=None,
        description="Position in the queue (if available)"
    )
    estimated_wait_seconds: Optional[float] = Field(
        default=None,
        description="Estimated wait time in seconds"
    )


class JobProcessingStatus(BaseModel):
    """Response when job is currently being processed."""
    status: JobStatus = JobStatus.PROCESSING
    job_id: str
    started_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp when processing started"
    )


class JobResult(BaseModel):
    """
    The result of a completed job.
    
    This is a demo result structure showing the processed output.
    """
    message: str = Field(
        ...,
        description="Result message from processing"
    )
    input_echo: dict[str, Any] = Field(
        ...,
        description="Echo of the original input for verification"
    )
    processed_at: str = Field(
        ...,
        description="ISO timestamp when processing completed"
    )
    processing_duration_ms: Optional[float] = Field(
        default=None,
        description="How long processing took in milliseconds"
    )


class JobDoneStatus(BaseModel):
    """Response when job has completed successfully."""
    status: JobStatus = JobStatus.DONE
    job_id: str
    result: JobResult


class JobFailedStatus(BaseModel):
    """Response when job processing has failed."""
    status: JobStatus = JobStatus.FAILED
    job_id: str
    error: str = Field(
        ...,
        description="Error message describing what went wrong"
    )
    failed_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp when failure occurred"
    )


class JobStatusResponse(BaseModel):
    """
    Generic job status response that can represent any state.
    
    Used for the GET /jobs/{job_id} endpoint to return the current
    state of a job regardless of its processing stage.
    """
    status: JobStatus
    job_id: str
    result: Optional[JobResult] = None
    error: Optional[str] = None
    queue_position: Optional[int] = None
    estimated_wait_seconds: Optional[float] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "status": "queued",
                    "job_id": "job_a1b2c3d4e5f6",
                    "queue_position": 5,
                    "estimated_wait_seconds": 10.0
                },
                {
                    "status": "processing",
                    "job_id": "job_a1b2c3d4e5f6",
                    "started_at": "2026-01-01T12:00:00Z"
                },
                {
                    "status": "done",
                    "job_id": "job_a1b2c3d4e5f6",
                    "result": {
                        "message": "Demo processing complete",
                        "input_echo": {"name": "demo-job", "value": 42},
                        "processed_at": "2026-01-01T12:00:02Z"
                    }
                }
            ]
        }


class JobNotFoundResponse(BaseModel):
    """Response when a job ID is not found."""
    status: str = "not_found"
    job_id: str
    message: str = "Job not found or has expired"


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    service: str = "overload-safe-queue-api"
    version: str
    queue_connected: bool
    timestamp: str


class ErrorResponse(BaseModel):
    """Generic error response."""
    error: str
    detail: Optional[str] = None
    timestamp: str
