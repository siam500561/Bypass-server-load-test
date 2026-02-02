"""
Configuration module for the overload-safe queue-based API.

Manages environment variables and Upstash Redis connection settings.
All sensitive credentials should be loaded from environment variables
in production deployments.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UpstashConfig:
    """
    Immutable configuration for Upstash Redis connection.
    
    Attributes:
        rest_url: The Upstash Redis REST API endpoint
        rest_token: Authentication token for Upstash Redis
    """
    rest_url: str
    rest_token: str
    
    @property
    def headers(self) -> dict[str, str]:
        """Returns the authorization headers for Upstash REST API."""
        return {
            "Authorization": f"Bearer {self.rest_token}",
            "Content-Type": "application/json"
        }


@dataclass(frozen=True)
class WorkerConfig:
    """
    Configuration for the background worker.
    
    Attributes:
        processing_delay: Simulated processing time per job (seconds)
        poll_interval: Time to wait between queue polls when empty (seconds)
        max_retries: Maximum retry attempts for failed jobs
    """
    processing_delay: float = 2.0  # Simulate heavy processing
    poll_interval: float = 1.0     # Polling interval when queue is empty
    max_retries: int = 3           # Max retries for transient failures


@dataclass(frozen=True)
class QueueConfig:
    """
    Configuration for Redis queue keys and settings.
    
    Attributes:
        job_queue_key: Redis list key for the job queue
        job_prefix: Prefix for individual job hash keys
        result_ttl: Time-to-live for completed job results (seconds)
    """
    job_queue_key: str = "jobs:queue"
    job_prefix: str = "job:"
    result_ttl: int = 3600  # Keep results for 1 hour


class Settings:
    """
    Central settings manager that aggregates all configuration.
    
    Loads configuration from environment variables.
    Upstash credentials are REQUIRED - no defaults provided for security.
    """
    
    def __init__(self):
        # Load Upstash credentials from environment variables (REQUIRED)
        # These must be set in production - no hardcoded defaults for security
        upstash_url = os.getenv("UPSTASH_REDIS_REST_URL")
        upstash_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        
        if not upstash_url or not upstash_token:
            raise ValueError(
                "Missing required environment variables: "
                "UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN must be set"
            )
        
        self.upstash = UpstashConfig(
            rest_url=upstash_url,
            rest_token=upstash_token
        )
        
        # Worker configuration
        self.worker = WorkerConfig(
            processing_delay=float(os.getenv("WORKER_PROCESSING_DELAY", "2.0")),
            poll_interval=float(os.getenv("WORKER_POLL_INTERVAL", "1.0")),
            max_retries=int(os.getenv("WORKER_MAX_RETRIES", "3"))
        )
        
        # Queue configuration
        self.queue = QueueConfig(
            job_queue_key=os.getenv("QUEUE_JOB_KEY", "jobs:queue"),
            job_prefix=os.getenv("QUEUE_JOB_PREFIX", "job:"),
            result_ttl=int(os.getenv("QUEUE_RESULT_TTL", "3600"))
        )
    
    @property
    def server_port(self) -> int:
        """Server port from environment variable."""
        return int(os.getenv("PORT", "8000"))
    
    @property
    def api_title(self) -> str:
        """API title for OpenAPI documentation."""
        return "Overload-Safe Queue API"
    
    @property
    def api_version(self) -> str:
        """API version string."""
        return "1.0.0"
    
    @property
    def api_description(self) -> str:
        """API description for OpenAPI documentation."""
        return (
            "A production-grade, queue-based API that absorbs traffic spikes "
            "by decoupling request ingestion from processing using Upstash Redis."
        )


# Global settings instance - imported throughout the application
settings = Settings()
