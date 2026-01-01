"""
Background Worker - Processes jobs from the queue.

This is a single-threaded worker that processes exactly one job
at a time. It's designed to run as a separate process from the
API server, ensuring that:

1. The API remains responsive even under heavy load
2. Processing is rate-limited naturally by sequential execution
3. The worker can be restarted without losing jobs (they're in Redis)
4. Memory usage stays constant regardless of queue size

Run this worker with: python -m app.workers.worker
"""

import asyncio
import logging
import signal
import sys
import time
from typing import Any, Optional

# Add parent directory to path for module imports
sys.path.insert(0, str(__file__).rsplit("\\", 3)[0])

from app.core.config import settings
from app.core.utils import get_timestamp, safe_json_loads, safe_json_dumps
from app.queue.consumer import consumer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("worker")


class JobWorker:
    """
    Single-threaded job processor.
    
    This worker:
    - Polls the queue for jobs
    - Processes one job at a time
    - Simulates heavy processing with artificial delay
    - Updates job status throughout the lifecycle
    - Handles errors gracefully without crashing
    
    The worker is designed to be extremely resilient. If it crashes
    or is restarted, no jobs are lost because they remain in Redis
    until explicitly dequeued.
    """
    
    def __init__(self):
        """Initialize the worker with configuration."""
        self.processing_delay = settings.worker.processing_delay
        self.poll_interval = settings.worker.poll_interval
        self.max_retries = settings.worker.max_retries
        self.running = False
        self.jobs_processed = 0
        self.jobs_failed = 0
        
        logger.info("Worker initialized")
        logger.info(f"  Processing delay: {self.processing_delay}s")
        logger.info(f"  Poll interval: {self.poll_interval}s")
        logger.info(f"  Max retries: {self.max_retries}")
    
    async def start(self):
        """
        Start the worker main loop.
        
        The worker will run indefinitely, processing jobs as they
        become available and sleeping when the queue is empty.
        """
        self.running = True
        logger.info("Worker started - waiting for jobs...")
        
        while self.running:
            try:
                # Try to get a job from the queue
                job_id = await consumer.dequeue_job()
                
                if job_id:
                    # Process the job
                    await self._process_job(job_id)
                else:
                    # No jobs available, sleep before polling again
                    await asyncio.sleep(self.poll_interval)
                    
            except asyncio.CancelledError:
                logger.info("Worker received cancellation signal")
                break
            except Exception as e:
                # Log error but don't crash - continue processing
                logger.error(f"Unexpected error in worker loop: {str(e)}")
                await asyncio.sleep(self.poll_interval)
        
        logger.info(f"Worker stopped. Processed: {self.jobs_processed}, Failed: {self.jobs_failed}")
    
    async def stop(self):
        """Signal the worker to stop gracefully."""
        logger.info("Worker stop requested")
        self.running = False
    
    async def _process_job(self, job_id: str):
        """
        Process a single job.
        
        Args:
            job_id: The job identifier to process
        """
        start_time = time.time()
        logger.info(f"Processing job: {job_id}")
        
        try:
            # Mark job as processing
            await consumer.mark_processing(job_id)
            
            # Get job data
            job_data = await consumer.get_job_data(job_id)
            
            if not job_data:
                logger.warning(f"Job {job_id} data not found - skipping")
                await consumer.mark_failed(job_id, "Job data not found")
                self.jobs_failed += 1
                return
            
            # Extract payload
            payload = job_data.get("payload", {})
            if isinstance(payload, str):
                payload = safe_json_loads(payload, default={})
            
            # Perform the demo processing
            result = await self._do_processing(job_id, payload)
            
            # Calculate processing duration
            duration_ms = (time.time() - start_time) * 1000
            result["processing_duration_ms"] = round(duration_ms, 2)
            
            # Mark job as completed
            await consumer.mark_completed(job_id, result)
            
            self.jobs_processed += 1
            logger.info(f"Job {job_id} completed in {duration_ms:.0f}ms")
            
        except Exception as e:
            logger.error(f"Error processing job {job_id}: {str(e)}")
            await consumer.mark_failed(job_id, str(e))
            self.jobs_failed += 1
    
    async def _do_processing(
        self,
        job_id: str,
        payload: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Perform the actual job processing.
        
        This is a DEMO implementation that simulates heavy processing
        with an artificial delay. In a real application, this would
        contain the actual business logic.
        
        Args:
            job_id: The job identifier
            payload: The job payload data
        
        Returns:
            Processing result dictionary
        """
        # Simulate heavy processing with artificial delay
        # This represents CPU-intensive work, API calls, etc.
        await asyncio.sleep(self.processing_delay)
        
        # Extract payload fields with safe defaults
        name = payload.get("name", "unknown")
        value = payload.get("value", 0)
        message = payload.get("message", "")
        metadata = payload.get("metadata", {})
        
        # Demo processing: transform the input
        # In a real app, this would be your actual business logic
        processed_value = value * 2  # Simple transformation
        
        # Build the result
        result = {
            "message": f"Demo processing complete for '{name}'",
            "input_echo": {
                "name": name,
                "value": value,
                "message": message,
                "metadata": metadata,
                "processed_value": processed_value
            },
            "processed_at": get_timestamp(),
            "worker_id": "worker-1"  # In multi-worker setup, this would be unique
        }
        
        return result


async def main():
    """
    Main entry point for the worker process.
    
    Sets up signal handlers for graceful shutdown and starts
    the worker loop.
    """
    worker = JobWorker()
    
    # Set up graceful shutdown handlers
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Shutdown signal received")
        asyncio.create_task(worker.stop())
    
    # Register signal handlers (Unix-style, may need adjustment for Windows)
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        # Use alternative approach
        signal.signal(signal.SIGINT, lambda s, f: asyncio.create_task(worker.stop()))
        signal.signal(signal.SIGTERM, lambda s, f: asyncio.create_task(worker.stop()))
    
    # Start the worker
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        await worker.stop()


if __name__ == "__main__":
    print("=" * 60)
    print("OVERLOAD-SAFE QUEUE WORKER")
    print("=" * 60)
    print("This worker processes jobs from the Upstash Redis queue.")
    print("Press Ctrl+C to stop gracefully.")
    print("=" * 60)
    
    asyncio.run(main())
