"""
Queue Producer - Pushes jobs to Upstash Redis queue.

This module handles the fast, non-blocking enqueue operation.
It uses the Upstash Redis REST API for maximum compatibility
and to avoid connection pooling issues on small servers.
"""

import httpx
import logging
from typing import Any

from ..core.config import settings
from ..core.utils import safe_json_dumps, get_timestamp

# Configure logging
logger = logging.getLogger(__name__)


class QueueProducer:
    """
    Handles pushing jobs to the Upstash Redis queue.
    
    Uses the Upstash REST API which is:
    - Connectionless (no pool management needed)
    - Serverless-friendly
    - Fast for simple operations
    
    This producer is designed to be extremely fast and never block,
    ensuring the API can accept requests even under massive load.
    """
    
    def __init__(self):
        """Initialize the producer with Upstash configuration."""
        self.base_url = settings.upstash.rest_url
        self.headers = settings.upstash.headers
        self.queue_key = settings.queue.job_queue_key
        self.job_prefix = settings.queue.job_prefix
        self.result_ttl = settings.queue.result_ttl
    
    async def enqueue_job(
        self,
        job_id: str,
        payload: dict[str, Any]
    ) -> bool:
        """
        Push a job to the Redis queue and store its initial metadata.
        
        This operation performs two Redis commands atomically:
        1. LPUSH - Add job ID to the queue list
        2. HSET - Store job metadata in a hash
        
        Args:
            job_id: Unique identifier for the job
            payload: The job payload data
        
        Returns:
            True if enqueue was successful, False otherwise
        
        Note:
            This method must be fast and resilient. It uses a short
            timeout to prevent blocking the API under load.
        """
        try:
            # Prepare job data to store
            job_data = {
                "job_id": job_id,
                "payload": safe_json_dumps(payload),
                "status": "queued",
                "created_at": get_timestamp(),
                "started_at": "",
                "completed_at": "",
                "result": "",
                "error": ""
            }
            
            # Use pipeline to execute multiple commands atomically
            # Upstash REST API supports pipeline via array of commands
            pipeline_commands = [
                # Store job metadata as hash
                ["HSET", f"{self.job_prefix}{job_id}", *self._flatten_dict(job_data)],
                # Set TTL on the job hash (for cleanup)
                ["EXPIRE", f"{self.job_prefix}{job_id}", str(self.result_ttl)],
                # Push job ID to the queue (RPUSH for FIFO order)
                ["RPUSH", self.queue_key, job_id]
            ]
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.base_url}/pipeline",
                    headers=self.headers,
                    json=pipeline_commands
                )
                
                if response.status_code == 200:
                    logger.debug(f"Job {job_id} enqueued successfully")
                    return True
                else:
                    logger.error(
                        f"Failed to enqueue job {job_id}: "
                        f"Status {response.status_code}, Body: {response.text}"
                    )
                    return False
                    
        except httpx.TimeoutException:
            logger.error(f"Timeout while enqueuing job {job_id}")
            return False
        except Exception as e:
            logger.error(f"Error enqueuing job {job_id}: {str(e)}")
            return False
    
    async def get_queue_length(self) -> int:
        """
        Get the current length of the job queue.
        
        Returns:
            Number of jobs waiting in the queue, or -1 on error
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.base_url}",
                    headers=self.headers,
                    json=["LLEN", self.queue_key]
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return int(data.get("result", 0))
                return -1
                
        except Exception as e:
            logger.error(f"Error getting queue length: {str(e)}")
            return -1
    
    async def health_check(self) -> bool:
        """
        Check if the Upstash Redis connection is healthy.
        
        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(
                    f"{self.base_url}",
                    headers=self.headers,
                    json=["PING"]
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("result") == "PONG"
                return False
                
        except Exception:
            return False
    
    def _flatten_dict(self, d: dict[str, Any]) -> list[str]:
        """
        Flatten a dictionary into a list of key-value pairs for HSET.
        
        Args:
            d: Dictionary to flatten
        
        Returns:
            List of alternating keys and values
        """
        result = []
        for key, value in d.items():
            result.append(str(key))
            result.append(str(value) if value is not None else "")
        return result


# Global producer instance for the application
producer = QueueProducer()
