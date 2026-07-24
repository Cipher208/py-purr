# PURR — Future Plan

> **Статус:** Draft
> **Дата:** 2026-07-24
> **Визия:** Полноценная Redis-подобная СУБД на SQLite

---

## 1. Текущее состояние (v0.1.0)

### Working
- **Store** — thread-safe KV с SQLite WAL, TTL, atomic writes
- **StateMachine** — FSM с persistence, snapshots, guards, actions
- **Saga** — compensating transactions
- **EventBus** — pub/sub
- **EventStream** — persistent event store с cursors (Redis Streams-like)
- **EventVersioner** — event schema migration
- **HealthChecker** — component health monitoring
- **Middleware** — pipeline (logging, rate limit, dedup, filter, transform)
- **Retry** — exponential backoff с jitter
- **Tests** — 44/44 passed

### Stats
- LOC: ~1500
- Files: 15
- Modules: 10
- Tests: 44

---

## 2. Roadmap

### Phase 1: Data Structures (Redis-like)

Добавить основные Redis data structures поверх Store.

| Feature | Redis Commands | Priority |
|---|---|---|
| **Strings** | GET, SET, DEL, INCR, DECR, APPEND, STRLEN | ✅ Done |
| **Hashes** | HSET, HGET, HDEL, HGETALL, HLEN, HMSET, HMGET | P0 |
| **Lists** | LPUSH, RPUSH, LPOP, RPOP, LRANGE, LLEN, LINDEX | P0 |
| **Sets** | SADD, SREM, SMEMBERS, SISMEMBER, SCARD, SUNION, SINTER | P0 |
| **Sorted Sets** | ZADD, ZREM, ZRANGE, ZSCORE, ZRANK, ZCARD | P1 |
| **Streams** | XADD, XREAD, XRANGE, XLEN, XINFO | ✅ Done (EventStream) |

#### Hashes Implementation
```python
# purr/structures/hashes.py
class HashStore:
    def hset(self, name: str, key: str, value: Any) -> int:
        """Set hash field. Returns 1 if new, 0 if updated."""
    
    def hget(self, name: str, key: str) -> Any | None:
        """Get hash field."""
    
    def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields."""
    
    def hgetall(self, name: str) -> dict[str, Any]:
        """Get all hash fields."""
    
    def hlen(self, name: str) -> int:
        """Get hash length."""
    
    def hmset(self, name: str, mapping: dict[str, Any]) -> None:
        """Set multiple hash fields."""
    
    def hmget(self, name: str, *keys: str) -> list[Any]:
        """Get multiple hash fields."""
    
    def hexists(self, name: str, key: str) -> bool:
        """Check if hash field exists."""
    
    def hkeys(self, name: str) -> list[str]:
        """Get all hash field names."""
    
    def hvals(self, name: str) -> list[Any]:
        """Get all hash field values."""
```

#### Lists Implementation
```python
# purr/structures/lists.py
class ListStore:
    def lpush(self, key: str, *values: Any) -> int:
        """Push values to head."""
    
    def rpush(self, key: str, *values: Any) -> int:
        """Push values to tail."""
    
    def lpop(self, key: str) -> Any | None:
        """Pop from head."""
    
    def rpop(self, key: str) -> Any | None:
        """Pop from tail."""
    
    def lrange(self, key: str, start: int, stop: int) -> list[Any]:
        """Get range of elements."""
    
    def llen(self, key: str) -> int:
        """Get list length."""
    
    def lindex(self, key: str, index: int) -> Any | None:
        """Get element by index."""
    
    def lset(self, key: str, index: int, value: Any) -> bool:
        """Set element by index."""
    
    def lrem(self, key: str, count: int, value: Any) -> int:
        """Remove elements by value."""
```

#### Sets Implementation
```python
# purr/structures/sets.py
class SetStore:
    def sadd(self, key: str, *values: Any) -> int:
        """Add members to set."""
    
    def srem(self, key: str, *values: Any) -> int:
        """Remove members from set."""
    
    def smembers(self, key: str) -> set:
        """Get all members."""
    
    def sismember(self, key: str, value: Any) -> bool:
        """Check membership."""
    
    def scard(self, key: str) -> int:
        """Get set cardinality."""
    
    def sunion(self, *keys: str) -> set:
        """Union of sets."""
    
    def sinter(self, *keys: str) -> set:
        """Intersection of sets."""
    
    def sdiff(self, *keys: str) -> set:
        """Difference of sets."""
```

---

### Phase 2: Transactions

Добавить транзакции как в Redis (MULTI/EXEC).

| Feature | Redis Commands | Priority |
|---|---|---|
| **Transactions** | MULTI, EXEC, DISCARD, WATCH | P0 |
| **Pipelines** | BATCH, PIPELINE | P1 |
| **Lua Scripting** | EVAL, EVALSHA | P2 |

#### Transactions Implementation
```python
# purr/transactions.py
class Transaction:
    def __init__(self, store: Store):
        self._store = store
        self._commands: list[tuple[str, tuple, dict]] = []
        self._active = False
    
    def multi(self) -> None:
        """Start transaction."""
        self._active = True
        self._commands.clear()
    
    def queue(self, method: str, *args, **kwargs) -> None:
        """Queue a command."""
        if not self._active:
            raise RuntimeError("No active transaction")
        self._commands.append((method, args, kwargs))
    
    def exec(self) -> list[Any]:
        """Execute all queued commands atomically."""
        results = []
        for method, args, kwargs in self._commands:
            fn = getattr(self._store, method)
            results.append(fn(*args, **kwargs))
        self._active = False
        return results
    
    def discard(self) -> None:
        """Discard queued commands."""
        self._commands.clear()
        self._active = False
```

---

### Phase 3: Networking

Добавить серверную часть для удалённого доступа.

| Feature | Description | Priority |
|---|---|---|
| **TCP Server** | Redis-совместимый протокол | P1 |
| **HTTP API** | REST API для CRUD | P1 |
| **WebSocket** | Pub/Sub через WebSocket | P2 |
| **Redis Protocol** | RESP (Redis Serialization Protocol) | P1 |

#### TCP Server
```python
# purr/server.py
class PurrServer:
    def __init__(self, store: Store, host: str = "0.0.0.0", port: int = 6380):
        self._store = store
        self._host = host
        self._port = port
    
    async def start(self) -> None:
        """Start TCP server."""
        server = await asyncio.start_server(
            self._handle_client, self._host, self._port
        )
        async with server:
            await server.serve_forever()
    
    async def _handle_client(self, reader, writer) -> None:
        """Handle client connection (RESP protocol)."""
        # Parse RESP, execute commands, return results
        pass
```

#### HTTP API
```python
# purr/http_api.py
from aiohttp import web

class PurrHTTP:
    def __init__(self, store: Store):
        self._store = store
        self._app = web.Application()
        self._setup_routes()
    
    def _setup_routes(self) -> None:
        self._app.router.add_get("/kv/{key}", self._get)
        self._app.router.add_put("/kv/{key}", self._put)
        self._app.router.add_delete("/kv/{key}", self._delete)
        self._app.router.add_get("/health", self._health)
    
    async def _get(self, request) -> web.Response:
        key = request.match_info["key"]
        value = self._store.get(key)
        if value is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"key": key, "value": value})
    
    async def _put(self, request) -> web.Response:
        key = request.match_info["key"]
        data = await request.json()
        self._store.set(key, data["value"], ttl=data.get("ttl"))
        return web.json_response({"ok": True})
    
    async def _delete(self, request) -> web.Response:
        key = request.match_info["key"]
        self._store.delete(key)
        return web.json_response({"ok": True})
    
    async def _health(self, request) -> web.Response:
        return web.json_response({"status": "ok", "size": self._store.size()})
```

---

### Phase 4: Advanced Features

| Feature | Description | Priority |
|---|---|---|
| **Pub/Sub** | Real-time pub/sub через streams | P1 |
| **Cluster** | Multi-node replication | P2 |
| **Persistence** | RDB snapshots + AOF | P1 |
| **Eviction** | LRU/LFU eviction policies | P2 |
| **TLS** | Encrypted connections | P2 |
| **Auth** | Password/AUTH command | P1 |

#### Pub/Sub Implementation
```python
# purr/pubsub.py
class PubSub:
    def __init__(self, stream: EventStream):
        self._stream = stream
        self._subscribers: dict[str, list[Callable]] = {}
    
    async def subscribe(self, channel: str, callback: Callable) -> None:
        """Subscribe to channel."""
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)
    
    async def publish(self, channel: str, message: Any) -> int:
        """Publish message to channel."""
        event = Event(
            type=EventType.STORE,
            topic=f"pubsub:{channel}",
            payload={"message": message},
        )
        self._stream.append(event)
        
        # Notify subscribers
        for callback in self._subscribers.get(channel, []):
            await callback(message)
        
        return len(self._subscribers.get(channel, []))
```

---

### Phase 5: Developer Experience

| Feature | Description | Priority |
|---|---|---|
| **CLI** | Command-line интерфейс | P0 |
| **Client Library** | Python client для удалённого доступа | P1 |
| **Docker** | Docker image | P1 |
| **Benchmarking** | Performance tests | P2 |
| **Documentation** | Полная документация API | P0 |

#### CLI
```bash
# purr-cli
$ purr set mykey "hello"
OK

$ purr get mykey
"hello"

$ purr hset myhash field1 value1
(integer) 1

$ purr hgetall myhash
1) "field1"
2) "value1"

$ purr lpush mylist a b c
(integer) 3

$ purr lrange mylist 0 -1
1) "c"
2) "b"
3) "a"

$ purr info
# Server
redis_version:0.1.0-purr
uptime_in_seconds:12345
# Keyspace
db0:keys=42,expires=10,avg_ttl=3600
```

---

## 3. Architecture Evolution

### Current (v0.1.0)
```
purr/
├── store.py          # KV store
├── state_machine.py  # FSM
├── saga.py           # Sagas
├── event.py          # Event bus
├── event_stream.py   # Event stream
├── middleware.py     # Pipeline
├── retry.py          # Retry
├── health.py         # Health
├── versioning.py     # Versioning
└── __init__.py       # Public API
```

### Target (v1.0.0)
```
purr/
├── core/
│   ├── store.py          # KV store (enhanced)
│   ├── transactions.py   # MULTI/EXEC
│   └── commands.py       # Command registry
├── structures/
│   ├── strings.py        # String operations
│   ├── hashes.py         # Hash operations
│   ├── lists.py          # List operations
│   ├── sets.py           # Set operations
│   ├── sorted_sets.py    # Sorted set operations
│   └── streams.py        # Stream operations
├── state/
│   ├── state_machine.py  # FSM
│   └── saga.py           # Sagas
├── events/
│   ├── event.py          # Event types
│   ├── event_bus.py      # Pub/sub
│   ├── event_stream.py   # Persistent stream
│   └── versioning.py     # Schema migration
├── infra/
│   ├── middleware.py     # Pipeline
│   ├── retry.py          # Retry
│   ├── health.py         # Health
│   └── auth.py           # Authentication
├── server/
│   ├── tcp.py            # TCP server (RESP)
│   ├── http.py           # REST API
│   └── websocket.py      # WebSocket
├── client/
│   ├── __init__.py       # Python client
│   └── connection.py     # Connection pool
└── cli/
    └── main.py           # CLI entry point
```

---

## 4. Performance Targets

| Metric | Target | Current |
|---|---|---|
| **SET/GET latency** | < 1ms (local) | ~0.5ms |
| **Throughput** | > 100K ops/sec | ~50K ops/sec |
| **Memory** | < 1MB per 1K keys | ~0.5MB |
| **Startup time** | < 100ms | ~50ms |
| **WAL checkpoint** | Every 1000 writes | Manual |

---

## 5. Use Cases

### 1. Configuration Store
```python
from purr import Store

config = Store("config.db")
config.set("app.name", "MyApp")
config.set("app.version", "1.0.0")
config.set("db.host", "localhost", ttl=3600)  # Cache for 1 hour
```

### 2. Session Store
```python
from purr import Store

sessions = Store("sessions.db")
sessions.set("session:abc123", {"user_id": 1, "role": "admin"}, ttl=86400)
```

### 3. Task Queue
```python
from purr import EventStream

queue = EventStream("tasks.db")
queue.append(Event(type=EventType.SYSTEM, topic="task.new", payload={"job": "send_email"}))
```

### 4. State Machine
```python
from purr import StateMachine

order = StateMachine("order", db_path="orders.db")
order.add_transition("pending", "processing", "pay")
order.add_transition("processing", "shipped", "ship")
order.add_transition("shipped", "delivered", "deliver")
```

### 5. Saga Pattern
```python
from purr import Saga

saga = Saga("order-creation")
saga.add_step("create_order", create_order, compensation=delete_order)
saga.add_step("charge_payment", charge_payment, compensation=refund_payment)
saga.add_step("send_email", send_email)
await saga.execute({"user_id": 1, "items": [...]})
```

---

## 6. Comparison with Redis

| Feature | Redis | PURR |
|---|---|---|
| **Storage** | In-memory + RDB/AOF | SQLite WAL |
| **Persistence** | Optional | Always (SQLite) |
| **Thread Safety** | Single-threaded | Thread-safe (threading.local) |
| **Replication** | Master-slave | Planned (Phase 4) |
| **Cluster** | Redis Cluster | Planned (Phase 4) |
| **Protocol** | RESP | Planned (Phase 3) |
| **Scripting** | Lua | Python (sagas) |
| **Cost** | RAM-heavy | Disk-efficient |

**PURR advantages over Redis:**
- Persistent by default (no data loss on crash)
- Thread-safe (no single-thread bottleneck)
- Python-native (no C dependency)
- Disk-efficient (SQLite vs RAM)
- Built-in sagas and state machines

**Redis advantages over PURR:**
- Faster (in-memory)
- More mature (15+ years)
- Larger ecosystem
- Cluster support
- More data structures

---

## 7. Milestones

| Milestone | Features | ETA |
|---|---|---|
| **v0.2.0** | Hashes, Lists, Sets | 1 week |
| **v0.3.0** | Transactions, Pipelines | 2 weeks |
| **v0.4.0** | TCP Server, HTTP API | 3 weeks |
| **v0.5.0** | Pub/Sub, Auth | 1 month |
| **v0.6.0** | Client Library, CLI | 1.5 months |
| **v0.7.0** | Cluster, Replication | 2 months |
| **v1.0.0** | Full Redis compatibility | 3 months |

---

## 8. Open Questions

1. **RESP Protocol**: Implement full RESP2 or simplified version?
2. **Persistence**: RDB snapshots vs AOF vs both?
3. **Cluster**: Consensus algorithm (Raft vs Paxos)?
4. **Auth**: Password-only or ACL-based?
5. **License**: MIT vs Apache 2.0?
