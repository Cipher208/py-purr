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
  1. **Key-Value Store:** Fast storage with TTL (lazy expiry: `get()`/`exists()` report an expired key as missing but do not delete it — `sweep()`/`maintain()` do the physical cleanup), atomic multi-set, and atomic numeric operations.
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

# TTL notes: expiry is lazy and read-only — get()/exists()/mget() report an
# expired key as missing (None / False) and leave it in place, so it stays in
# keys() and in size() until sweep() or maintain() runs the physical cleanup.
# A read emits no journal event. incr() is atomic (safe across threads) and
# follows Redis semantics: incrementing an expired or missing key starts from 0.
```

An expired key is missing to every reader and still on disk until cleanup
runs — reading does not write:

```python
import time

from purr import Store

store = Store(":memory:")
store.set("short_lived", "gone soon", ttl=0.05)
time.sleep(0.2)

store.get("short_lived")     # None
store.exists("short_lived")  # False
store.mget(["short_lived"])  # [None]
store.keys()                 # ['short_lived'] — the read did not delete it
store.size()                 # 1 — it still counts until cleanup runs

store.sweep()                # 1 — cleanup is explicit, not a side effect of reading
store.keys()                 # []
store.size()                 # 0
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

Execute multi-step distributed operations safely. If any step fails, PURR automatically executes compensating rollback actions of previously completed steps in reverse order and rolls their data back: keys the step added are removed, keys it overwrote or deleted get their previous values back. Note: the failed step's own compensation is not run — handle it inside the action itself. Sagas are in-memory: if the process dies, all saga state is lost.

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

#### Journaling mutations

`Store` and `StateMachine` accept `journal=` and write every mutation to an
event stream. The stream must live in the **same file** as the data: the event
joins the data's transaction, so it is committed or rolled back together with
the row it describes, never after it. A journal on another file is refused at
start-up.

```python
from purr import EventStream, Store

# The journal must live in the data file: one file, one transaction.
stream = EventStream("app_state.db")
store = Store("app_state.db", journal=stream)

with store.transaction():
    store.set("user:1001", {"name": "Alice"})
    store.set("user:1002", {"name": "Bob"})

for event in stream.read()[0]:
    print(event.payload)
# {'op': 'set', 'key': 'user:1001', 'value': {'name': 'Alice'}}
# {'op': 'set', 'key': 'user:1002', 'value': {'name': 'Bob'}}

# A journal on another file is refused at start-up:
try:
    Store("app_state.db", journal=EventStream("events.db"))
except ValueError as exc:
    print("ValueError:", exc)
# ValueError: the journal must live in the same file as the data: ...
```

Migrating a deployment whose journal lived in its own `events.db`:

1. The old file stays readable — `EventStream("events.db")` opens it as before
   — but new events are written to the data file. Nothing is deleted.
2. Open the store once with `EventStream(<the data file>)`: that is what
   creates the `events` and `cursors` tables inside the data file.
3. To keep the history in one place, merge it, cursors included — they point
   at events that move with them, so consumers resume where they stopped:

```python
import sqlite3

dst = sqlite3.connect("app_state.db")
dst.execute("ATTACH DATABASE 'events.db' AS old")
dst.execute("INSERT OR IGNORE INTO events SELECT * FROM old.events")
dst.execute("INSERT OR IGNORE INTO cursors SELECT * FROM old.cursors")
dst.commit()
dst.close()
```

Skip step 3 and the new journal starts empty: a consumer whose saved cursor id
came from the old log fails with `ValueError: cursor references missing event
id`, and `stream.reset_cursor(name)` restarts it from the beginning of the new
log.

---

### Replaying the journal

The journal records `set` (with `expires_at` when the key has a TTL),
`delete`, `expire` and `flush`. A replay must handle **every** op: one that
skips ops it does not recognise will drop `flush` and keep keys that were
deleted, with nothing to report the divergence. `flush()` writes a single
event, not one per key — the journal grows with operations, not with rows.

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

The suite is 202 tests and runs in a few seconds. CI additionally enforces
`ruff check`, `ruff format --check`, and a coverage gate of 85% on Python
3.11, 3.12 and 3.13.

Crash-durability stand: `tools/crash_harness.py` kills a writer mid-operation
and checks what survived.

```bash
uv run python tools/crash_harness.py run 1               # plain writes
uv run python tools/crash_harness.py run-txn 1           # one transaction, 500 writes
uv run python tools/crash_harness.py run-journal 1       # single writes + journal
uv run python tools/crash_harness.py run-journal-txn 1   # transaction + journal
uv run python tools/crash_harness.py run-journal-txn-nonatomic 1  # control
```

Exit code `0` means the stand found no divergence, `1` means it found one, in
every mode — so any of them can fail a script. `run-journal` counts three
things as divergence: a key in KV with no journal event (gap), a journal event
with no key (phantom), and a confirmed key that did not survive. Its `0` means
KV and journal agree on every key that is there; it does not by itself prove
the writer got far enough to be measured — an empty database also reports
`gap 0` and exits `0`. `run-journal-txn` closes that hole for itself by
refusing a run whose 500-key batch never committed (`ПРОГОН НЕ СОСТОЯЛСЯ`);
`run-journal` has no such guard, so read its report line, not only its exit
code.

`run-journal-txn-nonatomic` is the control for `run-journal-txn`: it models the
pre-fix order (data committed, event written in a second transaction) and must
stay red — a stand that passes both is measuring nothing.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
