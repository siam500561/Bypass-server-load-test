"""
Results Storage - Job status and result handling.

This module provides a clean interface for retrieving job status
and results from Upstash Redis. It's used by the API to respond
to polling requests from clients.
"""

import httpx
import logging
from typing import Optional, Any

from ..core.config import settings
from ..core.utils import safe_json_loads
from ..models.schemas import JobStatus, JobStatusResponse, JobResult

# Configure logging
logger = logging.getLogger(__name__)


class ResultsStorage:
    """
    Handles retrieval of job status and results from Upstash Redis.
    
    This class provides a clean abstraction over the Redis storage,
    converting raw Redis data into typed response objects.
    
    The storage is read-only from the API perspective - only the
    worker writes to the results storage.
    """
    
    def __init__(self):
        """Initialize the storage with Upstash configuration."""
        self.base_url = settings.upstash.rest_url
        self.headers = settings.upstash.headers
        self.queue_key = settings.queue.job_queue_key
        self.job_prefix = settings.queue.job_prefix
        self.processing_delay = settings.worker.processing_delay
    
    async def get_job_status(self, job_id: str) -> Optional[JobStatusResponse]:
        """
        Get the current status of a job.
        
        Args:
            job_id: The job identifier to look up
        
        Returns:
            JobStatusResponse if job exists, None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Get all job data from the hash
                response = await client.post(
                    f"{self.base_url}",
                    headers=self.headers,
                    json=["HGETALL", f"{self.job_prefix}{job_id}"]
                )
                
                if response.status_code != 200:
                    logger.error(f"Failed to get job {job_id}: Status {response.status_code}")
                    return None
                
                data = response.json()
                result_array = data.get("result", [])
                
                # Empty result means job not found
                if not result_array:
                    return None
                
                # Convert array to dictionary
                job_data = self._array_to_dict(result_array)
                
                # Build the response based on status
                return await self._build_status_response(job_id, job_data)
                
        except Exception as e:
            logger.error(f"Error getting job status for {job_id}: {str(e)}")
            return None
    
    async def _build_status_response(
        self,
        job_id: str,
        job_data: dict[str, Any]
    ) -> JobStatusResponse:
        """
        Build a JobStatusResponse from raw job data.
        
        Args:
            job_id: The job identifier
            job_data: Raw dictionary from Redis
        
        Returns:
            Properly typed JobStatusResponse
        """
        status_str = job_data.get("status", "queued")
        
        # Map string status to enum
        try:
            status = JobStatus(status_str)
        except ValueError:
            status = JobStatus.QUEUED
        
        response_data = {
            "status": status,
            "job_id": job_id,
            "created_at": job_data.get("created_at"),
            "started_at": job_data.get("started_at") or None,
            "completed_at": job_data.get("completed_at") or None,
        }
        
        # Add status-specific fields
        if status == JobStatus.QUEUED:
            # Get queue position for waiting jobs
            queue_info = await self._get_queue_position(job_id)
            response_data["queue_position"] = queue_info.get("position")
            response_data["estimated_wait_seconds"] = queue_info.get("estimated_wait")
        
        elif status == JobStatus.DONE:
            # Parse and include result
            result_str = job_data.get("result", "{}")
            result_data = safe_json_loads(result_str, default={})
            
            if result_data:
                response_data["result"] = JobResult(
                    message=result_data.get("message", "Processing complete"),
                    input_echo=result_data.get("input_echo", {}),
                    processed_at=result_data.get("processed_at", ""),
                    processing_duration_ms=result_data.get("processing_duration_ms")
                )
        
        elif status == JobStatus.FAILED:
            response_data["error"] = job_data.get("error", "Unknown error")
        
        return JobStatusResponse(**response_data)
    
    async def _get_queue_position(self, job_id: str) -> dict[str, Any]:
        """
        Get the position of a job in the queue.
        
        Args:
            job_id: The job identifier
        
        Returns:
            Dictionary with position and estimated wait time
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Get entire queue to find position
                # Note: For very large queues, this could be optimized
                # by using LPOS (Redis 6.0.6+) if Upstash supports it
                response = await client.post(
                    f"{self.base_url}",
                    headers=self.headers,
                    json=["LRANGE", self.queue_key, "0", "-1"]
                )
                
                if response.status_code == 200:
                    data = response.json()
                    queue = data.get("result", [])
                    
                    try:
                        position = queue.index(job_id)
                        estimated_wait = position * self.processing_delay
                        return {
                            "position": position + 1,  # 1-indexed for users
                            "estimated_wait": round(estimated_wait, 1)
                        }
                    except ValueError:
                        # Job not in queue - might be processing
                        return {"position": None, "estimated_wait": None}
                
                return {"position": None, "estimated_wait": None}
                
        except Exception as e:
            logger.error(f"Error getting queue position: {str(e)}")
            return {"position": None, "estimated_wait": None}
    
    async def get_queue_stats(self) -> dict[str, Any]:
        """
        Get overall queue statistics.
        
        Returns:
            Dictionary with queue length and other stats
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
                    queue_length = int(data.get("result", 0))
                    
                    return {
                        "queue_length": queue_length,
                        "estimated_total_wait_seconds": queue_length * self.processing_delay
                    }
                
                return {"queue_length": -1, "estimated_total_wait_seconds": -1}
                
        except Exception as e:
            logger.error(f"Error getting queue stats: {str(e)}")
            return {"queue_length": -1, "estimated_total_wait_seconds": -1}
    
    async def job_exists(self, job_id: str) -> bool:
        """
        Check if a job exists in the storage.
        
        Args:
            job_id: The job identifier
        
        Returns:
            True if job exists, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.base_url}",
                    headers=self.headers,
                    json=["EXISTS", f"{self.job_prefix}{job_id}"]
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return int(data.get("result", 0)) > 0
                
                return False
                
        except Exception:
            return False
    
    def _array_to_dict(self, arr: list) -> dict[str, Any]:
        """
        Convert Redis HGETALL array result to dictionary.
        
        Redis HGETALL returns [key1, val1, key2, val2, ...]
        
        Args:
            arr: Array from Redis response
        
        Returns:
            Dictionary representation
        """
        result = {}
        for i in range(0, len(arr), 2):
            if i + 1 < len(arr):
                result[arr[i]] = arr[i + 1]
        return result


# Global storage instance for the application
results_storage = ResultsStorage()
