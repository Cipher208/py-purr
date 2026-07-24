# PURR

> Redis-like on SQLite — state machine, sagas, middleware, WAL.

## Features

- **Store** — thread-safe key-value store with SQLite WAL
- **State Machine** — FSM with persistence, snapshots, guards, actions
- **Saga** — compensating transactions for multi-step operations
- **Middleware** — event processing pipeline (logging, rate limiting, dedup, filter, transform)
- **Event Bus** — pub/sub for decoupled communication
- **Retry** — exponential backoff with jitter

## Quick Start

```python
from purr import Store

# Create a store
store = Store("my.db")

# Basic operations
store.set("key", "value")
store.get("key")  # "value"
store.delete("key")

# TTL
store.set("temp", "data", ttl=60)  # expires in 60 seconds

# Atomic multi-set
store.mset({"a": 1, "b": 2, "c": 3})
```

## State Machine

```python
from purr import StateMachine

# Create a machine
sm = StateMachine("order", db_path="state.db")

# Define transitions
sm.add_transition("idle", "processing", "submit")
sm.add_transition("processing", "done", "complete")
sm.add_transition("processing", "failed", "error")

# Use it
sm.set_state("idle")
sm.send("submit")  # Now in "processing"
sm.send("complete")  # Now in "done"
```

## Saga

```python
from purr import Saga

async def create_order(data):
    return {"order_id": 123}

async def charge_payment(data):
    return {"payment_id": "abc"}

async def compensate_payment(data):
    pass  # Refund logic

# Build saga
saga = Saga("order-creation")
saga.add_step("create_order", create_order)
saga.add_step("charge_payment", charge_payment, compensation=compensate_payment)

# Execute
result = await saga.execute({"user_id": 1})
```

## Middleware

```python
from purr import MiddlewarePipeline, LoggingMiddleware, RateLimitMiddleware

pipeline = MiddlewarePipeline()
pipeline.add(LoggingMiddleware())
pipeline.add(RateLimitMiddleware(max_per_second=10))

# Execute through pipeline
await pipeline.execute(event, handler)
```

## License

MIT
