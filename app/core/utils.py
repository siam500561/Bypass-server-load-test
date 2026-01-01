"""
Shared utility functions for the queue-based API.

Contains helper functions used across multiple modules including
ID generation, timestamp handling, and common operations.
"""

import uuid
import time
from datetime import datetime, timezone
from typing import Any
import json


def generate_job_id() -> str:
    """
    Generate a unique job identifier.
    
    Uses UUID4 for guaranteed uniqueness across distributed systems.
    The prefix 'job_' makes IDs easily identifiable in logs and debugging.
    
    Returns:
        A unique job ID string in format 'job_<uuid>'
    """
    return f"job_{uuid.uuid4().hex[:16]}"


def get_timestamp() -> str:
    """
    Get current UTC timestamp in ISO format.
    
    Returns:
        ISO-formatted UTC timestamp string
    """
    return datetime.now(timezone.utc).isoformat()


def get_unix_timestamp() -> float:
    """
    Get current Unix timestamp.
    
    Returns:
        Current time as Unix timestamp (seconds since epoch)
    """
    return time.time()


def safe_json_loads(data: str | bytes, default: Any = None) -> Any:
    """
    Safely parse JSON with error handling.
    
    Args:
        data: JSON string or bytes to parse
        default: Value to return if parsing fails
    
    Returns:
        Parsed JSON data or default value on failure
    """
    try:
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return default


def safe_json_dumps(data: Any, default: str = "{}") -> str:
    """
    Safely serialize data to JSON string.
    
    Args:
        data: Data to serialize
        default: Value to return if serialization fails
    
    Returns:
        JSON string or default value on failure
    """
    try:
        return json.dumps(data, default=str)
    except (TypeError, ValueError):
        return default


def truncate_string(s: str, max_length: int = 100) -> str:
    """
    Truncate a string to a maximum length for logging.
    
    Args:
        s: String to truncate
        max_length: Maximum allowed length
    
    Returns:
        Original string if short enough, otherwise truncated with ellipsis
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - 3] + "..."


def calculate_wait_position(queue_length: int, processing_time: float = 2.0) -> dict:
    """
    Calculate estimated wait time based on queue position.
    
    Args:
        queue_length: Current number of jobs ahead in queue
        processing_time: Average processing time per job
    
    Returns:
        Dictionary with queue position and estimated wait time
    """
    estimated_wait = queue_length * processing_time
    
    return {
        "queue_position": queue_length,
        "estimated_wait_seconds": round(estimated_wait, 1),
        "estimated_wait_human": format_duration(estimated_wait)
    }


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable string.
    
    Args:
        seconds: Duration in seconds
    
    Returns:
        Human-readable duration string
    """
    if seconds < 60:
        return f"{int(seconds)} seconds"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''}"
