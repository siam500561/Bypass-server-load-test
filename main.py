"""
Unified Entry Point for Cloud Server Deployment

This file starts BOTH the FastAPI API server and the background worker
in a single Python process, suitable for free cloud hosting that only
allows one startup command.

The API server and worker run concurrently using asyncio.
"""

import asyncio
import logging
import sys
import signal
from multiprocessing import Process

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def run_api_server():
    """Run the FastAPI server in a separate process."""
    import os
    import uvicorn
    from app.main import app
    
    # Cloud servers set PORT env var - use it if available
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting FastAPI server on 0.0.0.0:{port}...")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True
    )


def run_worker():
    """Run the background worker in a separate process."""
    import asyncio
    from app.workers.worker import main as worker_main
    
    logger.info("Starting background worker...")
    asyncio.run(worker_main())


def main():
    """
    Main entry point that starts both API and worker.
    
    Uses multiprocessing to run both components concurrently.
    """
    print("=" * 70)
    print("OVERLOAD-SAFE QUEUE API - UNIFIED STARTUP")
    print("=" * 70)
    print("Starting API Server + Background Worker...")
    print("=" * 70)
    
    # Create processes for API and Worker
    api_process = Process(target=run_api_server, name="API-Server")
    worker_process = Process(target=run_worker, name="Background-Worker")
    
    # Start both processes
    api_process.start()
    worker_process.start()
    
    logger.info(f"API Server started (PID: {api_process.pid})")
    logger.info(f"Worker started (PID: {worker_process.pid})")
    logger.info("System is ready to handle requests!")
    
    # Set up signal handler for graceful shutdown
    def shutdown_handler(signum, frame):
        logger.info("Shutdown signal received, stopping processes...")
        api_process.terminate()
        worker_process.terminate()
        api_process.join(timeout=5)
        worker_process.join(timeout=5)
        logger.info("Shutdown complete")
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)
    
    try:
        # Wait for both processes
        api_process.join()
        worker_process.join()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        shutdown_handler(None, None)


if __name__ == "__main__":
    main()
