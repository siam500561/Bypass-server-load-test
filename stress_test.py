"""
Stress Load Test for Overload-Safe Queue API

This script sends massive concurrent requests to test the API's 
ability to handle high traffic without crashing.

Usage:
    python stress_test.py                    # Default: 100 requests, 10 concurrent
    python stress_test.py --requests 1000    # 1000 total requests
    python stress_test.py --concurrent 50    # 50 concurrent connections
    python stress_test.py --requests 5000 --concurrent 100  # Heavy load
"""

import asyncio
import httpx
import time
import argparse
import statistics
from dataclasses import dataclass, field
from typing import Optional
from collections import Counter


# ============================================================
# Configuration
# ============================================================

BASE_URL = "http://13.203.74.93:8000"

# Test payload template
def get_test_payload(index: int) -> dict:
    return {
        "name": f"stress-test-job-{index}",
        "value": index,
        "message": f"Load test request #{index}",
        "metadata": {"test_id": index, "batch": "stress_test"}
    }


# ============================================================
# Results Tracking
# ============================================================

@dataclass
class TestResults:
    """Tracks all test metrics."""
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    status_codes: Counter = field(default_factory=Counter)
    response_times: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    start_time: float = 0
    end_time: float = 0
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
    
    @property
    def requests_per_second(self) -> float:
        if self.duration > 0:
            return self.total_requests / self.duration
        return 0
    
    @property
    def success_rate(self) -> float:
        if self.total_requests > 0:
            return (self.successful / self.total_requests) * 100
        return 0
    
    @property
    def avg_response_time(self) -> float:
        if self.response_times:
            return statistics.mean(self.response_times)
        return 0
    
    @property
    def min_response_time(self) -> float:
        if self.response_times:
            return min(self.response_times)
        return 0
    
    @property
    def max_response_time(self) -> float:
        if self.response_times:
            return max(self.response_times)
        return 0
    
    @property
    def p95_response_time(self) -> float:
        if len(self.response_times) >= 20:
            sorted_times = sorted(self.response_times)
            idx = int(len(sorted_times) * 0.95)
            return sorted_times[idx]
        return self.max_response_time
    
    @property
    def p99_response_time(self) -> float:
        if len(self.response_times) >= 100:
            sorted_times = sorted(self.response_times)
            idx = int(len(sorted_times) * 0.99)
            return sorted_times[idx]
        return self.max_response_time


# ============================================================
# Load Test Functions
# ============================================================

async def send_single_request(
    client: httpx.AsyncClient,
    index: int,
    results: TestResults,
    verbose: bool = False
) -> None:
    """Send a single POST request to /jobs endpoint."""
    payload = get_test_payload(index)
    start = time.perf_counter()
    
    try:
        response = await client.post(
            f"{BASE_URL}/jobs",
            json=payload,
            timeout=30.0
        )
        
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
        results.response_times.append(elapsed)
        results.status_codes[response.status_code] += 1
        
        if response.status_code in (200, 201, 202):
            results.successful += 1
            if verbose:
                data = response.json()
                print(f"✓ Request {index}: {response.status_code} - Job ID: {data.get('job_id', 'N/A')} ({elapsed:.1f}ms)")
        else:
            results.failed += 1
            if verbose:
                print(f"✗ Request {index}: {response.status_code} ({elapsed:.1f}ms)")
                
    except httpx.TimeoutException:
        results.failed += 1
        results.status_codes["timeout"] += 1
        results.errors.append(f"Request {index}: Timeout")
        if verbose:
            print(f"✗ Request {index}: TIMEOUT")
            
    except httpx.ConnectError as e:
        results.failed += 1
        results.status_codes["connection_error"] += 1
        results.errors.append(f"Request {index}: Connection error - {str(e)}")
        if verbose:
            print(f"✗ Request {index}: CONNECTION ERROR")
            
    except Exception as e:
        results.failed += 1
        results.status_codes["error"] += 1
        results.errors.append(f"Request {index}: {str(e)}")
        if verbose:
            print(f"✗ Request {index}: ERROR - {str(e)}")


async def run_load_test(
    total_requests: int,
    concurrent_limit: int,
    verbose: bool = False
) -> TestResults:
    """
    Run the load test with specified parameters.
    
    Args:
        total_requests: Total number of requests to send
        concurrent_limit: Maximum concurrent connections
        verbose: Print each request result
    
    Returns:
        TestResults object with all metrics
    """
    results = TestResults(total_requests=total_requests)
    
    print("\n" + "=" * 60)
    print("🚀 STRESS LOAD TEST STARTING")
    print("=" * 60)
    print(f"Target URL:        {BASE_URL}/jobs")
    print(f"Total Requests:    {total_requests:,}")
    print(f"Concurrent Limit:  {concurrent_limit}")
    print("=" * 60 + "\n")
    
    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(concurrent_limit)
    
    async def limited_request(client: httpx.AsyncClient, index: int):
        async with semaphore:
            await send_single_request(client, index, results, verbose)
    
    # Configure client with connection pooling
    limits = httpx.Limits(
        max_keepalive_connections=concurrent_limit,
        max_connections=concurrent_limit + 10
    )
    
    results.start_time = time.perf_counter()
    
    async with httpx.AsyncClient(limits=limits) as client:
        # Create all tasks
        tasks = [
            limited_request(client, i)
            for i in range(total_requests)
        ]
        
        # Progress tracking
        completed = 0
        batch_size = max(1, total_requests // 20)  # 5% increments
        
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            await asyncio.gather(*batch)
            completed += len(batch)
            
            # Progress bar
            progress = completed / total_requests
            bar_length = 40
            filled = int(bar_length * progress)
            bar = "█" * filled + "░" * (bar_length - filled)
            print(f"\r[{bar}] {progress*100:.1f}% ({completed:,}/{total_requests:,})", end="", flush=True)
    
    results.end_time = time.perf_counter()
    print("\n")  # New line after progress bar
    
    return results


async def check_health() -> bool:
    """Check if the API is reachable."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BASE_URL}/health")
            if response.status_code == 200:
                data = response.json()
                print(f"✓ API Health: {data.get('status', 'unknown')}")
                print(f"  Queue Connected: {data.get('queue_connected', 'unknown')}")
                return True
            else:
                print(f"✗ Health check failed: {response.status_code}")
                return False
    except Exception as e:
        print(f"✗ Cannot reach API: {str(e)}")
        return False


async def check_queue_stats() -> Optional[dict]:
    """Get current queue statistics."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BASE_URL}/queue/stats")
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    return None


def print_results(results: TestResults) -> None:
    """Print formatted test results."""
    print("=" * 60)
    print("📊 STRESS TEST RESULTS")
    print("=" * 60)
    
    print(f"\n{'SUMMARY':^60}")
    print("-" * 60)
    print(f"  Total Requests:      {results.total_requests:,}")
    print(f"  Successful:          {results.successful:,} ({results.success_rate:.1f}%)")
    print(f"  Failed:              {results.failed:,}")
    print(f"  Total Duration:      {results.duration:.2f}s")
    print(f"  Requests/Second:     {results.requests_per_second:.1f} RPS")
    
    print(f"\n{'RESPONSE TIMES':^60}")
    print("-" * 60)
    if results.response_times:
        print(f"  Average:             {results.avg_response_time:.2f}ms")
        print(f"  Minimum:             {results.min_response_time:.2f}ms")
        print(f"  Maximum:             {results.max_response_time:.2f}ms")
        print(f"  95th Percentile:     {results.p95_response_time:.2f}ms")
        print(f"  99th Percentile:     {results.p99_response_time:.2f}ms")
    else:
        print("  No successful responses to measure")
    
    print(f"\n{'STATUS CODE DISTRIBUTION':^60}")
    print("-" * 60)
    for status, count in sorted(results.status_codes.items(), key=lambda x: -x[1]):
        percentage = (count / results.total_requests) * 100
        bar = "█" * int(percentage / 2)
        print(f"  {status:>15}: {count:>6} ({percentage:>5.1f}%) {bar}")
    
    if results.errors and len(results.errors) <= 10:
        print(f"\n{'ERRORS (first 10)':^60}")
        print("-" * 60)
        for error in results.errors[:10]:
            print(f"  • {error}")
    elif results.errors:
        print(f"\n  Total errors: {len(results.errors)} (showing first 10)")
        for error in results.errors[:10]:
            print(f"  • {error}")
    
    print("\n" + "=" * 60)
    
    # Performance rating
    if results.success_rate >= 99:
        if results.requests_per_second >= 100:
            print("🏆 EXCELLENT - API handles high load perfectly!")
        else:
            print("✅ GREAT - 100% success rate, all requests accepted!")
    elif results.success_rate >= 95:
        print("✅ GOOD - API performs well under load")
    elif results.success_rate >= 80:
        print("⚠️  MODERATE - Some requests failed under load")
    else:
        print("❌ POOR - API struggles under this load")
    
    print("=" * 60 + "\n")


# ============================================================
# Main Entry Point
# ============================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Stress test the Overload-Safe Queue API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python stress_test.py                         # Quick test (100 requests)
  python stress_test.py -r 500 -c 25            # Medium load
  python stress_test.py -r 1000 -c 50           # Heavy load
  python stress_test.py -r 5000 -c 100          # Extreme load
  python stress_test.py -r 10000 -c 200 -v      # Maximum stress (verbose)
        """
    )
    
    parser.add_argument(
        "-r", "--requests",
        type=int,
        default=100,
        help="Total number of requests to send (default: 100)"
    )
    
    parser.add_argument(
        "-c", "--concurrent",
        type=int,
        default=10,
        help="Maximum concurrent connections (default: 10)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print each request result"
    )
    
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="Skip initial health check"
    )
    
    args = parser.parse_args()
    
    print("\n" + "🔥" * 30)
    print("   OVERLOAD-SAFE QUEUE API - STRESS TEST")
    print("🔥" * 30 + "\n")
    
    # Health check
    if not args.skip_health:
        print("Checking API health...")
        if not await check_health():
            print("\n❌ API is not reachable. Aborting test.")
            return
        print()
    
    # Get initial queue stats
    print("Checking queue status...")
    stats = await check_queue_stats()
    if stats:
        print(f"  Queue Length: {stats.get('queue_length', 'N/A')}")
        print(f"  Est. Wait: {stats.get('estimated_wait_seconds', 'N/A')}s")
    print()
    
    # Run the load test
    results = await run_load_test(
        total_requests=args.requests,
        concurrent_limit=args.concurrent,
        verbose=args.verbose
    )
    
    # Print results
    print_results(results)
    
    # Check final queue stats
    print("Checking final queue status...")
    stats = await check_queue_stats()
    if stats:
        print(f"  Queue Length: {stats.get('queue_length', 'N/A')}")
        print(f"  Est. Wait: {stats.get('estimated_wait_seconds', 'N/A')}s")
    print()


if __name__ == "__main__":
    asyncio.run(main())
