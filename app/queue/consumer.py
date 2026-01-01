"""
Queue Consumer - Pulls jobs from Upstash Redis queue.

This module handles dequeuing jobs for processing by the worker.
It uses blocking-like behavior through polling to efficiently
wait for new jobs while minimizing API calls.
"""

import httpx
import logging
from typing import Optional, Any

from ..core.config import settings
from ..core.utils import safe_json_loads, get_timestamp

# Configure logging
logger = logging.getLogger(__name__)


class QueueConsumer:
    """
    Handles pulling jobs from the Upstash Redis queue.
    
    Since Upstash REST API doesn't support true BLPOP (blocking pop),
    we implement a polling-based approach that's efficient and
    suitable for single-worker processing.
    
    The consumer is designed to:
    - Pull one job at a time (single-threaded processing)
    - Handle transient failures gracefully
    - Never crash on malformed data
    """
    
    def __init__(self):
        """Initialize the consumer with Upstash configuration."""
        self.base_url = settings.upstash.rest_url
        self.headers = settings.upstash.headers
        self.queue_key = settings.queue.job_queue_key
        self.job_prefix = settings.queue.job_prefix
    
    async def dequeue_job(self) -> Optional[str]:
        """
        Remove and return the next job ID from the queue.
        
        Uses LPOP to get the oldest job (FIFO order since we RPUSH).
        
        Returns:
            Job ID string if a job was available, None otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}",
                    headers=self.headers,
                    json=["LPOP", self.queue_key]
                )
                
                if response.status_code == 200:
                    data = response.json()
                    result = data.get("result")
                    
                    if result is not None:
                        logger.debug(f"Dequeued job: {result}")
                        return str(result)
                    return None
                else:
                    logger.error(f"Failed to dequeue: Status {response.status_code}")
                    return None
                    
        except httpx.TimeoutException:
            logger.warning("Timeout while dequeuing job")
            return None
        except Exception as e:
            logger.error(f"Error dequeuing job: {str(e)}")
            return None
    
    async def get_job_data(self, job_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve all data for a specific job.
        
        Args:
            job_id: The job identifier
        
        Returns:
            Dictionary containing job data, or None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}",
                    headers=self.headers,
                    json=["HGETALL", f"{self.job_prefix}{job_id}"]
                )
                
                if response.status_code == 200:
                    data = response.json()
                    result = data.get("result", [])
                    
                    if not result:
                        return None
                    
                    # Convert array of [key, value, key, value, ...] to dict
                    job_data = {}
                    for i in range(0, len(result), 2):
                        if i + 1 < len(result):
                            key = result[i]
                            value = result[i + 1]
                            job_data[key] = value
                    
                    # Parse the payload JSON if present
                    if "payload" in job_data:
                        job_data["payload"] = safe_json_loads(
                            job_data["payload"],
                            default={}
                        )
                    
                    # Parse result JSON if present
                    if "result" in job_data and job_data["result"]:
                        job_data["result"] = safe_json_loads(
                            job_data["result"],
                            default={}
                        )
                    
                    return job_data
                    
                return None
                
        except Exception as e:
            logger.error(f"Error getting job data for {job_id}: {str(e)}")
            return None
    
    async def update_job_status(
        self,
        job_id: str,
        status: str,
        **additional_fields
    ) -> bool:
        """
        Update the status and other fields of a job.
        
        Args:
            job_id: The job identifier
            status: New status value
            **additional_fields: Additional fields to update
        
        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Build the HSET command with all fields
            fields = {"status": status, **additional_fields}
            hset_args = ["HSET", f"{self.job_prefix}{job_id}"]
            
            for key, value in fields.items():
                hset_args.append(str(key))
                if isinstance(value, dict):
                    hset_args.append(safe_json_loads(value) if isinstance(value, str) else str(value))
                else:
                    hset_args.append(str(value) if value is not None else "")
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}",
                    headers=self.headers,
                    json=hset_args
                )
                
                return response.status_code == 200
                
        except Exception as e:
            logger.error(f"Error updating job {job_id}: {str(e)}")
            return False
    
    async def mark_processing(self, job_id: str) -> bool:
        """
        Mark a job as currently being processed.
        
        Args:
            job_id: The job identifier
        
        Returns:
            True if update was successful
        """
        return await self.update_job_status(
            job_id,
            status="processing",
            started_at=get_timestamp()
        )
    
    async def mark_completed(
        self,
        job_id: str,
        result: dict[str, Any]
    ) -> bool:
        """
        Mark a job as completed with its result.
        
        Args:
            job_id: The job identifier
            result: The processing result
        
        Returns:
            True if update was successful
        """
        from ..core.utils import safe_json_dumps
        
        return await self.update_job_status(
            job_id,
            status="done",
            completed_at=get_timestamp(),
            result=safe_json_dumps(result)
        )
    
    async def mark_failed(self, job_id: str, error: str) -> bool:
        """
        Mark a job as failed with an error message.
        
        Args:
            job_id: The job identifier
            error: Error message describing the failure
        
        Returns:
            True if update was successful
        """
        return await self.update_job_status(
            job_id,
            status="failed",
            completed_at=get_timestamp(),
            error=error
        )
    
    async def peek_queue(self, count: int = 10) -> list[str]:
        """
        Peek at the next N jobs in the queue without removing them.
        
        Useful for estimating queue position.
        
        Args:
            count: Number of jobs to peek
        
        Returns:
            List of job IDs in queue order
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}",
                    headers=self.headers,
                    json=["LRANGE", self.queue_key, "0", str(count - 1)]
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("result", [])
                return []
                
        except Exception as e:
            logger.error(f"Error peeking queue: {str(e)}")
            return []


# Global consumer instance for the application
consumer = QueueConsumer()
