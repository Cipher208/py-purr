# 🐾 PURR

**The Zero-Infrastructure SQLite-backed alternative to Redis.**

*State Machine, Sagas, Event Streams, and Key-Value Store with SQLite WAL persistence.*

[![PyPI](https://img.shields.io/pypi/v/py-purr.svg)](https://pypi.org/project/py-purr/)
[![CI](https://github.com/Cipher208/py-purr/actions/workflows/ci.yml/badge.svg)](https://github.com/Cipher208/py-purr/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 💡 Why PURR?

Modern applications and autonomous AI agents need reliable state management, event streaming, and transactional guarantees. Typically, this forces you to deploy and manage a heavy infrastructure stack: **Redis, Redis Streams, Celery, and RabbitMQ**.

**PURR replaces that complexity with a single embedded SQLite database file.**

- 🪶 **Zero Infrastructure:** Pure Python. No Docker containers, no external services, no background daemons, zero network overhead.
- ⚡ **SQLite WAL Mode:** Concurrency-safe, high-throughput atomic read/writes that survive crashes and power loss.
- 🔄 **3-in-1 Architecture:**
  1. **Key-Value Store:** Fast storage with TTL (lazy expiry: checked on get/exists, or run sweep()/maintain() manually), atomic multi-set, and atomic numeric operations.
  2. **State Machine & Sagas:** FSM engine with persistent snapshots, guards, and rollback of previously completed saga steps on failure (compensating transactions).
  3. **Event Streams & Pub/Sub:** Redis Streams-like append-only event store with consumer cursors and middleware pipelines (rate limiting, deduplication, filtering).

---

## 📦 Installation

```bash
pip install py-purr
```

The distribution is called **`py-purr`**, but you import it as **`purr`**:

```python
from purr import Store
```

The name `purr` on PyPI belongs to an unrelated package, so `pip install purr`
would have installed somebody else's library. This is the only reason the
distribution and the import differ.

*(Or install locally via `pip install -e .`)*

---

## 🚀 Quick Tour

### 1. Key-Value Store with TTL & Atomic Operations

```python
from purr import Store

# Initialize store (in-memory or persistent file)
store = Store("app_state.db")

# Basic KV operations
store.set("user:1001", {"name": "Alice", "role": "admin"})
user = store.get("user:1001")

# Auto-expiring keys (TTL in seconds)
store.set("session_token", "xyz-123", ttl=3600)

# Atomic multi-set and counters
store.mset({"counter": 0, "status": "active"})
store.incr("counter", 1)  # returns 1

# TTL notes: expiry is lazy — an expired key disappears on get()/exists(),
# but stays visible in keys()/size() until sweep() or maintain() runs.
# incr() is atomic (safe across threads) and follows Redis semantics:
# incrementing an expired or missing key starts from 0.
```

---

### 2. State Machine with Persistence & Snapshots

```python
from purr import StateMachine

sm = StateMachine("order_pipeline", db_path="pipeline.db")

# Define transitions
sm.add_transition("idle", "processing", "start_job")
sm.add_transition("processing", "completed", "finish_job")
sm.add_transition("processing", "failed", "report_error")

# Transition state (machine starts empty — set the initial state first)
sm.set_state("idle")
sm.send("start_job")
assert sm.current_state == "processing"

# Take persistent snapshots for crash recovery
sm.snapshot()
sm.restore_snapshot()
```

---

### 3. Sagas (Compensating Transactions)

Execute multi-step distributed operations safely. If any step fails, PURR automatically executes compensating rollback actions of previously completed steps in reverse order and removes their written data. Note: the failed step's own compensation is not run — handle it inside the action itself. Sagas are in-memory: if the process dies, all saga state is lost.

```python
import asyncio
from purr import Saga

saga = Saga("deploy_workflow")

async def allocate_resources(ctx):
    ctx["allocated"] = True
    return ctx

async def release_resources(ctx):
    ctx["allocated"] = False

async def run_failing_migration(ctx):
    raise RuntimeError("Migration failed!")

# Define steps: (name, forward_action, compensation)
saga.add_step("reserve", allocate_resources, compensation=release_resources)
saga.add_step("migrate", run_failing_migration)

# If step 2 fails, 'release_resources' is executed automatically,
# then the error propagates (no result flag — expect the raise)
try:
    asyncio.run(saga.execute())
except RuntimeError as exc:
    assert str(exc) == "Migration failed!"
```

---

### 4. Event Streams & Consumer Groups (Redis Streams alternative)

Append-only persistent event logs with cursor tracking across multiple consumers.
The stream is enforced append-only: appending an event whose id already exists
raises `ValueError` (since 0.1.x this previously overwrote the original event —
a breaking change if you relied on overwrite-by-id).

```python
from purr import Event, EventStream, EventType

stream = EventStream("events.db")

# Publish events
stream.append(Event(type=EventType.SYSTEM, topic="user_signups", payload={"user_id": 42}))

# Read events, track consumer cursor.
# last_id is None when there is nothing new: guard the write-back, otherwise
# an empty poll would clear the cursor and replay the stream from the start.
events, last_id = stream.read(
    cursor=stream.get_cursor("my-consumer"), topic="user_signups", limit=50
)
if last_id:
    stream.set_cursor("my-consumer", last_id)
```

---

### 5. Pub/Sub with Middleware Pipeline

```python
import asyncio
from purr import Event, EventBus, EventType
from purr.middleware import DedupMiddleware, MiddlewarePipeline, RateLimitMiddleware

bus = EventBus()

# Middleware runs through a separate pipeline (bus has no .use());
# exact-topic match plus the "*" wildcard only
pipeline = MiddlewarePipeline()
pipeline.add(DedupMiddleware(ttl_seconds=60))
pipeline.add(RateLimitMiddleware(max_per_second=100))

async def handle_alert(event):
    print(f"Alert received: {event.payload}")

bus.subscribe("system.alerts.cpu", handle_alert)
event = Event(type=EventType.SYSTEM, topic="system.alerts.cpu", payload={"usage": "98%"})
asyncio.run(bus.publish(event))
# Same event through the middleware pipeline (dedup + rate limit), then to the handler
asyncio.run(pipeline.execute(event, handle_alert))

# publish_sync delivers to subscribers outside an async context (sync
# handlers directly; async handlers via asyncio.run). Inside a running
# event loop, use the async publish() instead.
```

---

## 🛠️ Development & Testing

```bash
uv sync --extra dev
uv run pytest -v
```

The suite is 117 tests and runs in a few seconds. CI additionally enforces
`ruff check`, `ruff format --check`, and a coverage gate of 85% on Python
3.11, 3.12 and 3.13.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
