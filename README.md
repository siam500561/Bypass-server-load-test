# Overload-Safe Queue-Based API

A production-grade, Python-only backend API designed to absorb massive traffic spikes (100,000+ concurrent requests) without crashing or returning server errors.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SYSTEM ARCHITECTURE                                │
└─────────────────────────────────────────────────────────────────────────────┘

                         ┌─────────────────┐
                         │     Clients     │
                         │ (100K+ requests)│
                         └────────┬────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │      FastAPI Server     │
                    │   (Stateless Ingress)   │
                    │                         │
                    │  • Accepts instantly    │
                    │  • No heavy processing  │
                    │  • Returns job_id       │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │                         │
           Enqueue  │    UPSTASH REDIS        │  Poll for
           (RPUSH)  │    (Serverless)         │  results
                    │                         │
                    │  ┌─────────────────┐    │
                    │  │   Job Queue     │    │
                    │  │   (Redis List)  │    │
                    │  └────────┬────────┘    │
                    │           │             │
                    │  ┌────────▼────────┐    │
                    │  │  Job Metadata   │    │
                    │  │  (Redis Hash)   │    │
                    │  └─────────────────┘    │
                    │                         │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    Background Worker    │
                    │   (Single-Threaded)     │
                    │                         │
                    │  • Processes 1 job/time │
                    │  • Rate-limited         │
                    │  • Crash-resistant      │
                    └─────────────────────────┘
```

## Core Design Principles

| Principle                | Implementation                              |
| ------------------------ | ------------------------------------------- |
| **Accept instantly**     | API only enqueues jobs to Redis             |
| **Never block**          | All processing happens in background worker |
| **Survive crashes**      | Jobs persist in Redis until processed       |
| **Graceful degradation** | System slows down, never fails              |
| **Minimal resources**    | Runs on 512MB RAM servers                   |

## Project Structure

```
project_root/
│
├── app/
│   ├── main.py                 # FastAPI app entrypoint
│   │
│   ├── api/
│   │   ├── routes.py           # API endpoints (/jobs, /health)
│   │
│   ├── queue/
│   │   ├── producer.py         # Push jobs to Upstash (RPUSH)
│   │   ├── consumer.py         # Pull jobs from Upstash (LPOP)
│   │
│   ├── workers/
│   │   ├── worker.py           # Background processor
│   │
│   ├── storage/
│   │   ├── results.py          # Job status & result retrieval
│   │
│   ├── models/
│   │   ├── schemas.py          # Pydantic request/response models
│   │
│   ├── core/
│   │   ├── config.py           # Environment & Upstash config
│   │   ├── utils.py            # Shared helpers
│
└── README.md                   # This file
```

## API Contract

### POST /jobs - Submit a Job

Submit a job for background processing. Returns immediately without waiting.

**Request:**

```json
{
  "name": "my-demo-job",
  "value": 42,
  "message": "Hello, World!",
  "metadata": { "priority": "normal" }
}
```

**Response (202 Accepted):**

```json
{
  "status": "accepted",
  "job_id": "job_a1b2c3d4e5f6",
  "message": "Job queued successfully. Poll GET /jobs/{job_id} for status."
}
```

### GET /jobs/{job_id} - Check Job Status

Poll for job status. Returns current state and result when complete.

**Response - Queued:**

```json
{
  "status": "queued",
  "job_id": "job_a1b2c3d4e5f6",
  "queue_position": 5,
  "estimated_wait_seconds": 10.0
}
```

**Response - Processing:**

```json
{
  "status": "processing",
  "job_id": "job_a1b2c3d4e5f6",
  "started_at": "2026-01-01T12:00:00Z"
}
```

**Response - Done:**

```json
{
  "status": "done",
  "job_id": "job_a1b2c3d4e5f6",
  "result": {
    "message": "Demo processing complete for 'my-demo-job'",
    "input_echo": {
      "name": "my-demo-job",
      "value": 42,
      "message": "Hello, World!",
      "processed_value": 84
    },
    "processed_at": "2026-01-01T12:00:02Z",
    "processing_duration_ms": 2001.5
  }
}
```

### GET /queue/stats - Queue Statistics

Get current queue length and estimated wait time.

```json
{
  "queue_length": 150,
  "estimated_wait_seconds": 300.0,
  "timestamp": "2026-01-01T12:00:00Z"
}
```

### GET /health - Health Check

```json
{
  "status": "healthy",
  "service": "overload-safe-queue-api",
  "version": "1.0.0",
  "queue_connected": true,
  "timestamp": "2026-01-01T12:00:00Z"
}
```

## Queue Design (Upstash Redis)

### Data Structures

| Structure     | Key Pattern    | Purpose           |
| ------------- | -------------- | ----------------- |
| **Job Queue** | `jobs:queue`   | Redis List (FIFO) |
| **Job Data**  | `job:{job_id}` | Redis Hash        |

### Job Hash Fields

```
job:job_a1b2c3d4
├── job_id      → "job_a1b2c3d4"
├── payload     → "{\"name\": \"demo\", ...}"
├── status      → "queued" | "processing" | "done" | "failed"
├── created_at  → "2026-01-01T12:00:00Z"
├── started_at  → "2026-01-01T12:00:01Z"
├── completed_at→ "2026-01-01T12:00:03Z"
├── result      → "{\"message\": \"...\"}"
└── error       → "" (or error message if failed)
```

### Queue Operations

```
Enqueue (API):
  RPUSH jobs:queue job_a1b2c3d4    # Add to end of queue
  HSET job:job_a1b2c3d4 ...        # Store metadata

Dequeue (Worker):
  LPOP jobs:queue                   # Remove from front
  HSET job:job_a1b2c3d4 status processing

Complete (Worker):
  HSET job:job_a1b2c3d4 status done result {...}
```

## Worker Behavior

The background worker:

1. **Single-threaded**: Processes exactly ONE job at a time
2. **Rate-limited**: Artificial delay simulates heavy processing
3. **Crash-resistant**: Jobs remain in Redis if worker dies
4. **Graceful**: Never crashes on malformed input
5. **Observable**: Logs all processing activity

### Worker State Machine

```
          ┌─────────────┐
          │   QUEUED    │
          └──────┬──────┘
                 │ LPOP (dequeue)
                 ▼
          ┌─────────────┐
          │ PROCESSING  │
          └──────┬──────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
  ┌─────────┐       ┌─────────┐
  │  DONE   │       │ FAILED  │
  └─────────┘       └─────────┘
```

## Scalability Guarantees

| Scenario                      | System Behavior                           |
| ----------------------------- | ----------------------------------------- |
| 100,000 simultaneous requests | All accepted, queued in Redis             |
| Worker crashes                | Jobs safe, resume on restart              |
| API crashes                   | Jobs safe, status checks fail temporarily |
| Queue grows very large        | Wait times increase, no failures          |
| Redis connection issues       | 503 with retry message                    |

## Configuration

Environment variables:

| Variable                   | Default    | Description                         |
| -------------------------- | ---------- | ----------------------------------- |
| `UPSTASH_REDIS_REST_URL`   | (required) | Upstash REST endpoint               |
| `UPSTASH_REDIS_REST_TOKEN` | (required) | Upstash auth token                  |
| `WORKER_PROCESSING_DELAY`  | `2.0`      | Simulated processing time (seconds) |
| `WORKER_POLL_INTERVAL`     | `1.0`      | Queue poll interval (seconds)       |
| `QUEUE_RESULT_TTL`         | `3600`     | Result expiry time (seconds)        |

## Dependencies

- **fastapi**: Web framework
- **uvicorn**: ASGI server
- **httpx**: Async HTTP client for Upstash REST API
- **pydantic**: Data validation

## Running the System

### Start the API Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Start the Worker (separate process)

```bash
python -m app.workers.worker
```

## Why This Architecture Works

### Problem: Traffic Spikes

Traditional APIs process requests synchronously. Under heavy load, they run out of memory, CPU, or connections and crash.

### Solution: Queue-Based Decoupling

1. **API** accepts requests instantly (microseconds)
2. **Redis** buffers the work (handles millions of items)
3. **Worker** processes slowly and safely (seconds per item)

### Result

- API never times out
- API never runs out of memory
- API never returns 500 errors due to load
- Users wait longer, but always get results

---

_This is a DEMO system for educational purposes. The processing logic is intentionally simple to focus on the architecture._
