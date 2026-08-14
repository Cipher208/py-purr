# 🐾 PURR

**The Zero-Infrastructure SQLite-backed alternative to Redis.**

*State Machine, Sagas, Event Streams, and Key-Value Store with SQLite WAL persistence.*

[![CI](https://github.com/Cipher208/PURR/actions/workflows/ci.yml/badge.svg)](https://github.com/Cipher208/PURR/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 💡 Why PURR?

Modern applications and autonomous AI agents need reliable state management, event streaming, and transactional guarantees. Typically, this forces you to deploy and manage a heavy infrastructure stack: **Redis, Redis Streams, Celery, and RabbitMQ**.

**PURR replaces that complexity with a single embedded SQLite database file.**

- 🪶 **Zero Infrastructure:** Pure Python. No Docker containers, no external services, no background daemons, zero network overhead.
- ⚡ **SQLite WAL Mode:** Concurrency-safe, high-throughput atomic read/writes that survive crashes and power loss.
- 🔄 **3-in-1 Architecture:**
  1. **Key-Value Store:** Fast storage with TTL auto-expiry, atomic multi-set, and numeric operations.
  2. **State Machine & Sagas:** FSM engine with persistent snapshots, guards, and automatic rollback on step failure (compensating transactions).
  3. **Event Streams & Pub/Sub:** Redis Streams-like append-only event store with consumer cursors and middleware pipelines (rate limiting, deduplication, filtering).

---

## 📦 Installation

```bash
pip install purr
```

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

# Transition state
sm.transition("start_job")
assert sm.current_state == "processing"

# Take persistent snapshots for crash recovery
snapshot_id = sm.snapshot()
sm.restore(snapshot_id)
```

---

### 3. Sagas (Compensating Transactions)

Execute multi-step distributed operations safely. If any step fails, PURR automatically executes compensating rollback actions in reverse order.

```python
from purr import Saga

saga = Saga("deploy_workflow", db_path="sagas.db")

def allocate_resources(ctx):
    ctx["allocated"] = True

def release_resources(ctx):
    ctx["allocated"] = False

def run_failing_migration(ctx):
    raise RuntimeError("Migration failed!")

# Define steps: (name, forward_action, compensate_action)
saga.add_step("reserve", allocate_resources, compensate=release_resources)
saga.add_step("migrate", run_failing_migration)

# If step 2 fails, 'release_resources' is executed automatically
result = saga.execute()
assert result.failed is True
```

---

### 4. Event Streams & Consumer Groups (Redis Streams alternative)

Append-only persistent event logs with cursor tracking across multiple consumers.

```python
from purr import EventStream

stream = EventStream("events.db")

# Publish events
event_id = stream.append(topic="user_signups", payload={"user_id": 42})

# Read events since consumer cursor
events = stream.read(topic="user_signups", after_cursor="cursor_id", limit=50)
```

---

### 5. Pub/Sub with Middleware Pipeline

```python
import asyncio
from purr import EventBus
from purr.middleware import DedupMiddleware, RateLimitMiddleware

bus = EventBus()
bus.use(DedupMiddleware(window_seconds=60))
bus.use(RateLimitMiddleware(max_per_second=100))

async def handle_alert(event):
    print(f"Alert received: {event.payload}")

bus.subscribe("system.alerts.*", handle_alert)
asyncio.run(bus.publish("system.alerts.cpu", {"usage": "98%"}))
```

---

## 🛠️ Development & Testing

Run the full test suite (44 tests):

```bash
uv run --with pytest --with pytest-asyncio pytest -v
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
