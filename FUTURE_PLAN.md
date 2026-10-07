# PURR — Future Plan

> **Status:** Draft
> **Date:** 2026-07-24
> **Vision:** A full Redis-like database engine on SQLite

---

## 1. Current State (v0.1.0)

### Working
- **Store** — thread-safe KV with SQLite WAL, TTL, atomic writes
- **StateMachine** — FSM with persistence, snapshots, guards, actions
- **Saga** — compensating transactions
- **EventBus** — pub/sub
- **EventStream** — persistent event store with cursors (Redis Streams-like)
- **EventVersioner** — event schema migration
- **HealthChecker** — component health monitoring
- **Middleware** — pipeline (logging, rate limit, dedup, filter, transform)
- **Retry** — exponential backoff with jitter
- **Tests** — 44/44 passed

### Stats
- LOC: ~1500
- Files: 15
- Modules: 10
- Tests: 44

---

## 2. Roadmap

### Phase 1: Data Structures (Redis-like)

Add the core Redis data structures on top of Store.

| Feature | Redis Commands | Priority |
|---|---|---|
| **Strings** | GET, SET, DEL, INCR, DECR, APPEND, STRLEN | ✅ Done |
| **Hashes** | HSET, HGET, HDEL, HGETALL, HLEN, HMSET, HMGET | P0 |
| **Lists** | LPUSH, RPUSH, LPOP, RPOP, LRANGE, LLEN, LINDEX | P0 |
| **Sets** | SADD, SREM, SMEMBERS, SISMEMBER, SCARD, SUNION, SINTER | P0 |
| **Sorted Sets** | ZADD, ZREM, ZRANGE, ZSCORE, ZRANK, ZCARD | P1 |
| **Streams** | XADD, XREAD, XRANGE, XLEN, XINFO | ✅ Done (EventStream) |
| **FTS5** | Full-text search across keys and values | P1 |
| **Key Versioning** | Point-in-time recovery, version history | P1 |

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

Add transactions as in Redis (MULTI/EXEC).

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

Add the server side for remote access.

| Feature | Description | Priority |
|---|---|---|
| **TCP Server** | Redis-compatible protocol | P1 |
| **HTTP API** | REST API for CRUD | P1 |
| **WebSocket** | Pub/Sub over WebSocket | P2 |
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
| **Pub/Sub** | Real-time pub/sub over streams | P1 |
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
| **CLI** | Command-line interface | P0 |
| **Client Library** | Python client for remote access | P1 |
| **Docker** | Docker image | P1 |
| **Benchmarking** | Performance tests | P2 |
| **Metrics** | Reads/sec, TTL hits, DB size tracking | P1 |
| **Documentation** | Complete API documentation | P0 |

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

## 3. Advanced Ideas

Further ideas for developing PURR beyond basic Redis compatibility.

### 3.1 Key Versioning (Point-in-Time Recovery)

Every SET writes a new version to the history. A GET without parameters returns the latest; a GET with `?version=N` returns that specific one.

```python
# purr/versioned_store.py
class VersionedStore(Store):
    def set(self, key: str, value: Any, ttl: float | None = None) -> bool:
        """Set with automatic versioning."""
        # Store current version
        version = self._get_next_version(key)
        self._store_version(key, version, value)
        # Store as current
        return super().set(key, value, ttl)
    
    def get(self, key: str, version: int | None = None) -> Any | None:
        """Get by key, optionally at specific version."""
        if version is None:
            return super().get(key)
        return self._get_version(key, version)
    
    def history(self, key: str, limit: int = 10) -> list[dict]:
        """Get version history for a key."""
        # Returns [{version, value, timestamp}, ...]
    
    def restore(self, key: str, version: int) -> bool:
        """Restore key to specific version."""
```

**Advantages over Redis:** Point-in-time recovery out of the box. No Redis does this.

### 3.2 Lazy TTL

Do not scan the whole database every second — expire on GET/SET.

```python
# purr/lazy_ttl.py
class LazyTTL:
    def on_access(self, key: str) -> bool:
        """Check TTL on access. Returns True if expired."""
        meta = self._get_meta(key)
        if meta and meta.expires_at:
            if datetime.now(timezone.utc) > meta.expires_at:
                self._delete(key)
                return True
        return False
    
    def cleanup(self, batch_size: int = 100) -> int:
        """Background cleanup of expired keys."""
        # SELECT key FROM kv_meta WHERE expires_at < NOW() LIMIT batch_size
        # DELETE FROM kv WHERE key IN (...)
        # Return count deleted
```

### 3.3 Write Queue

SQLite does not tolerate concurrent writes. A queue is needed.

```python
# purr/write_queue.py
class WriteQueue:
    def __init__(self, store: Store, max_queue: int = 1000):
        self._store = store
        self._queue = asyncio.Queue(maxsize=max_queue)
        self._worker_task = None
    
    async def start(self):
        """Start background worker."""
        self._worker_task = asyncio.create_task(self._process_queue())
    
    async def enqueue(self, operation: Callable) -> None:
        """Queue a write operation."""
        await self._queue.put(operation)
    
    async def _process_queue(self):
        """Process writes sequentially."""
        while True:
            op = await self._queue.get()
            await op()
            self._queue.task_done()
```

### 3.4 FTS5 (full-text search)

SQLite FTS5 for indexing keys and values.

```python
# purr/fts.py
class FTSIndex:
    def __init__(self, db_path: str | Path):
        self._db_path = db_path
        self._init_fts()
    
    def _init_fts(self):
        """Create FTS5 virtual table."""
        # CREATE VIRTUAL TABLE IF NOT EXISTS kv_fts USING fts5(key, value)
    
    def index(self, key: str, value: str) -> None:
        """Index a key-value pair."""
        # INSERT INTO kv_fts VALUES (key, value)
    
    def search(self, query: str, limit: int = 10) -> list[str]:
        """Full-text search across keys and values."""
        # SELECT key FROM kv_fts WHERE kv_fts MATCH ? LIMIT ?
    
    def remove(self, key: str) -> None:
        """Remove from index."""
        # DELETE FROM kv_fts WHERE key = ?
```

### 3.5 Hybrid Pub/Sub

An in-process queue for local subscribers + SQLite events for external ones.

```python
# purr/hybrid_pubsub.py
class HybridPubSub:
    def __init__(self, stream: EventStream):
        self._stream = stream
        self._local_subscribers: dict[str, list[Callable]] = {}
    
    async def subscribe(self, channel: str, callback: Callable, external: bool = False):
        """Subscribe to channel."""
        if external:
            # External: use EventStream with cursor
            pass
        else:
            # Local: in-process queue
            if channel not in self._local_subscribers:
                self._local_subscribers[channel] = []
            self._local_subscribers[channel].append(callback)
    
    async def publish(self, channel: str, message: Any) -> int:
        """Publish to channel."""
        # 1. Write to EventStream (for external consumers)
        event = Event(type=EventType.STORE, topic=f"pubsub:{channel}", payload={"message": message})
        self._stream.append(event)
        
        # 2. Notify local subscribers
        for callback in self._local_subscribers.get(channel, []):
            await callback(message)
        
        return len(self._local_subscribers.get(channel, []))
```

### 3.6 Replication (WAL Log Shipping)

The master ships WAL logs; the replicas apply the diffs.

```python
# purr/replication.py
class ReplicationManager:
    def __init__(self, store: Store):
        self._store = store
        self._replicas: list[ReplicaConnection] = []
    
    async def add_replica(self, host: str, port: int) -> None:
        """Add a replica to replicate to."""
    
    async def sync(self) -> None:
        """Send WAL changes to replicas."""
        # 1. Read WAL checkpoint
        # 2. Send diff to each replica
        # 3. Wait for acknowledgment
    
    async def catchup(self, replica: ReplicaConnection) -> None:
        """Full sync for new replica."""
```

### 3.7 Sharding (hash-based partitioning)

Each partition in its own SQLite file.

```python
# purr/sharded_store.py
class ShardedStore:
    def __init__(self, base_path: str | Path, num_shards: int = 4):
        self._shards = [
            Store(base_path / f"shard_{i}.db")
            for i in range(num_shards)
        ]
        self._num_shards = num_shards
    
    def _get_shard(self, key: str) -> Store:
        """Get shard for key using consistent hashing."""
        shard_id = hash(key) % self._num_shards
        return self._shards[shard_id]
    
    def set(self, key: str, value: Any, **kwargs) -> bool:
        return self._get_shard(key).set(key, value, **kwargs)
    
    def get(self, key: str) -> Any | None:
        return self._get_shard(key).get(key)
```

### 3.8 In-Memory LRU Cache

SQLite for persistence, an LRU layer for speed.

```python
# purr/cache.py
from collections import OrderedDict

class LRUCache:
    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._max_size = max_size
    
    def get(self, key: str) -> Any | None:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None
    
    def set(self, key: str, value: Any) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

class CachedStore:
    def __init__(self, store: Store, cache_size: int = 1000):
        self._store = store
        self._cache = LRUCache(cache_size)
    
    def get(self, key: str) -> Any | None:
        # Try cache first
        value = self._cache.get(key)
        if value is not None:
            return value
        # Fall through to store
        value = self._store.get(key)
        if value is not None:
            self._cache.set(key, value)
        return value
```

### 3.9 ARCHIVE Command

WAL checkpoint + compress + versioned backup.

```python
# purr/archive.py
class Archiver:
    def __init__(self, store: Store, archive_dir: str | Path):
        self._store = store
        self._archive_dir = Path(archive_dir)
        self._archive_dir.mkdir(parents=True, exist_ok=True)
    
    def archive(self, name: str | None = None) -> Path:
        """Create a versioned archive."""
        # 1. WAL checkpoint
        conn = self._store._get_conn()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        
        # 2. Copy DB
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = name or f"archive_{timestamp}"
        archive_path = self._archive_dir / f"{archive_name}.db"
        shutil.copy2(self._store._db_path, archive_path)
        
        # 3. Compress (optional)
        # gzip archive_path
        
        return archive_path
    
    def restore(self, archive_path: str | Path) -> bool:
        """Restore from archive."""
        shutil.copy2(archive_path, self._store._db_path)
        return True
    
    def list_archives(self) -> list[dict]:
        """List available archives."""
        archives = []
        for f in self._archive_dir.glob("*.db*"):
            archives.append({
                "name": f.stem,
                "path": str(f),
                "size": f.stat().st_size,
                "created": datetime.fromtimestamp(f.stat().st_ctime),
            })
        return sorted(archives, key=lambda x: x["created"], reverse=True)
```

### 3.10 Metrics

```python
# purr/metrics.py
class Metrics:
    def __init__(self):
        self._counters: dict[str, int] = {}
        self._histograms: dict[str, list[float]] = {}
    
    def increment(self, name: str, value: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value
    
    def observe(self, name: str, value: float) -> None:
        if name not in self._histograms:
            self._histograms[name] = []
        self._histograms[name].append(value)
    
    def get_counter(self, name: str) -> int:
        return self._counters.get(name, 0)
    
    def get_histogram(self, name: str) -> dict:
        values = self._histograms.get(name, [])
        if not values:
            return {"count": 0, "min": 0, "max": 0, "avg": 0}
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
        }
    
    def get_all(self) -> dict:
        return {
            "counters": self._counters.copy(),
            "histograms": {k: self.get_histogram(k) for k in self._histograms},
        }
```

### 3.11 Embedded Use Case

PURR as an embedded store for mobile and embedded systems.

**Advantages:**
- Single file (.db)
- No daemons
- No ports
- Python-native
- Thread-safe
- Persistent by default

**Use cases:**
- Mobile app local storage
- IoT device data
- Desktop app configuration
- Embedded Python applications

### 3.12 Dual Mode (StateMachine + KV)

One package, two modes of operation:

```python
from purr import Store, StateMachine

# KV mode
kv = Store("cache.db")
kv.set("user:123:prefs", {"theme": "dark"})
kv.lpush("queue:jobs", "job1")
kv.incr("counter:visits")

# StateMachine mode
sm = StateMachine("agent", db_path="state.db")
sm.apply_delta({"energy": -0.1}, "module")
snap = sm.get_snapshot()

# Both in one process
# (share same DB or separate files)
```

### 3.13 Python SDK

A clean API for both modes:

```python
# purr/client.py
class PurrClient:
    """Unified client for StateMachine and KV modes."""
    
    def __init__(self, db_path: str | Path, mode: str = "kv"):
        if mode == "state":
            self._backend = StateMachine("default", db_path)
        else:
            self._backend = Store(db_path)
    
    # KV operations
    def set(self, key: str, value: Any, **kwargs) -> bool: ...
    def get(self, key: str) -> Any | None: ...
    def delete(self, key: str) -> bool: ...
    
    # StateMachine operations
    def apply_delta(self, data: dict, module: str) -> None: ...
    def get_snapshot(self) -> dict: ...
```

### 3.14 CLI Tools

```
purr serve --port 6379          # Redis-compatible protocol (RESP)
purr serve --http --port 8080   # HTTP API
purr inspect data/purr.db       # Show the contents
purr stats data/purr.db         # Stats: reads/writes, WAL size
purr dump data/purr.db          # Dump to JSON
purr vacuum data/purr.db        # VACUUM + reclaim disk space
```

### 3.15 Auto-VACUUM

SQLite grows without VACUUM. Automatic VACUUM above a threshold:

```python
# purr/vacuum.py
class AutoVacuum:
    def __init__(self, store: Store, threshold: float = 0.5):
        self._store = store
        self._threshold = threshold  # 50% dead data
    
    def check_and_vacuum(self) -> bool:
        """Check if VACUUM needed, run if so."""
        conn = self._store._get_conn()
        
        # Check page count vs freelist
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
        
        if freelist / page_count > self._threshold:
            conn.execute("VACUUM")
            return True
        return False
```

### 3.16 Positioning

**One-line pitch:**

> **PURR — SQLite that answers like Redis. One library, three modules: Store, StateMachine, EventBus.**

**USP:**
1. Zero dependencies — `pip install py-purr` and you are done
2. Three modules in one package — KV + FSM + Events
3. SQLite WAL — data survives crashes
4. EventBus middleware — RateLimit, Dedup, Transform out of the box
5. Atomic writes — temp file + rename, never a torn file

**Who needs it:**
- Agent developers — internal state (mood, energy)
- Backend developers — a Redis replacement for small projects
- Hobby projects on a VPS — every dependency counts
- Dev environments — you do not want to run Redis just for tests

### 3.17 Competitive Analysis

| Solution | StateMachine | KV Store | EventBus | SQLite |
|---------|:---:|:---:|:---:|:---:|
| **PURR** | ✅ | ✅ | ✅ | ✅ |
| `redis` | ❌ | ✅ (native) | ❌ | ❌ |
| `sqlite-redis` | ❌ | Partial | ❌ | ✅ |
| `pickle + file` | ⚠️ hand-rolled | ❌ | ❌ | ❌ |

**PURR is the only one that gives you StateMachine, KV and EventBus — on plain SQLite, with no server.**

### 3.18 Key Decisions

- **WAL is mandatory**: `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`
- **A sync API is a feature**: for small operations, async is overhead
- **VACUUM is automatic**: above a threshold (50% dead data)
- **RESP is not required in v1**: start with HTTP + the Python SDK

### 3.19 Launch Strategy

- **PyPI**: `pip install py-purr`
- **Hacker News**: "I replaced Redis with a SQLite file — here's the library"
- **GitHub**: a README with badges and release notes
- **Documentation**: MkDocs or equivalent

### 3.20 Streams with Consumer Groups

Extended streams with consumer groups for load balancing.

```sql
CREATE TABLE IF NOT EXISTS streams (
    name TEXT PRIMARY KEY,
    maxlen INTEGER NOT NULL DEFAULT 10000,
    ttl_seconds INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stream_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_name TEXT NOT NULL REFERENCES streams(name),
    data TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS consumer_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_name TEXT NOT NULL,
    group_name TEXT NOT NULL,
    last_delivered_id INTEGER NOT NULL DEFAULT 0,
    pending_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(stream_name, group_name)
);

CREATE TABLE IF NOT EXISTS consumer_group_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES consumer_groups(id),
    consumer_name TEXT NOT NULL,
    last_acked_id INTEGER NOT NULL DEFAULT 0,
    pending_ids TEXT NOT NULL DEFAULT '[]',
    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(group_id, consumer_name)
);
```

**Operations:**
- `XADD(stream, data)` — append an entry
- `XREAD(stream, from_id, count)` — read from a position
- `XREADGROUP(group, consumer, count)` — balanced read
- `XACK(group, consumer, entry_id)` — acknowledge
- `XTRIM(stream, maxlen)` — trim
- `XDEL(stream, entry_id)` — delete one entry

### 3.21 Saga with SQL Savepoints

Sagas with real rollback through SQLite savepoints.

```sql
CREATE TABLE IF NOT EXISTS sagas (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS saga_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    saga_id TEXT NOT NULL REFERENCES sagas(id),
    step_order INTEGER NOT NULL,
    step_type TEXT NOT NULL,
    step_data TEXT NOT NULL,
    compensating_data TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    UNIQUE(saga_id, step_order)
);
```

**How it works:**
```sql
BEGIN;
    INSERT INTO kv_store ...;      -- Step 1
    INSERT INTO stream_entries ...; -- Step 2
    INSERT INTO pubsub_messages ...; -- Step 3
COMMIT;
-- If COMMIT failed, everything rolled back at the SQLite level
-- If business logic failed AFTER the COMMIT, run the compensation
```

### 3.22 Extended Middleware

Six built-in middleware (we have five; adding Validate and Metrics):

| Middleware | Purpose | Config |
|---|---|---|
| RateLimit | N events per window | RateLimit(count, window_seconds) |
| Dedup | Deduplicate by hash | Dedup(hash_fields, window_seconds) |
| Transform | Enrichment (timestamp, source) | Transform(enrichers...) |
| Logging | Audit trail | Logging(output, level) |
| **Validate** | **Schema validation** | **Validate(json_schema)** |
| **Metrics** | **Metrics collection** | **Metrics(prometheus_registry)** |

### 3.23 REST API Spec

```
GET    /kv/:key              — GET
POST   /kv/:key              — SET (body: value, ttl?)
DELETE /kv/:key              — DEL
POST   /kv/batch             — MSET
GET    /kv/batch?keys=...    — MGET

POST   /pubsub/publish       — Publish { channel, payload }
POST   /pubsub/subscribe     — Subscribe { channel, callback_url }
DELETE /pubsub/subscribe/:id — Unsubscribe

POST   /stream/:name/add     — XADD
GET    /stream/:name/read    — XREAD (since_id, count)
POST   /stream/:name/group   — Create consumer group

POST   /saga/begin           — Begin saga
POST   /saga/:id/step        — Add step
POST   /saga/:id/execute     — Execute
POST   /saga/:id/compensate  — Compensate
GET    /saga/:id             — Status

GET    /health               — Health check
GET    /stats                — Stats
```

### 3.24 MCP Integration

Tools for integration with AI agents:

```python
# MCP tools
purr_set(key, value, ttl=None)       # SET
purr_get(key)                        # GET
purr_del(key)                        # DEL
purr_keys(pattern)                   # LIKE search

purr_publish(channel, payload)       # PUBLISH
purr_subscribe(channel)              # SUBSCRIBE

purr_stream_add(stream, data)        # XADD
purr_stream_read(stream, from_id)    # XREAD

purr_saga_begin()                    # BEGIN SAGA
purr_saga_step(saga_id, type, data)  # ADD STEP
purr_saga_execute(saga_id)           # EXECUTE
```

### 3.25 TTL Daemon

A background goroutine that clears expired data:

```python
# purr/ttl_daemon.py
class TTLDaemon:
    def __init__(self, store: Store, interval: float = 60.0):
        self._store = store
        self._interval = interval
        self._running = False
    
    async def start(self) -> None:
        """Start background cleanup."""
        self._running = True
        while self._running:
            await self._cleanup()
            await asyncio.sleep(self._interval)
    
    async def _cleanup(self) -> int:
        """Delete expired keys."""
        conn = self._store._get_conn()
        cursor = conn.execute(
            "DELETE FROM kv_meta WHERE expires_at < ?",
            (datetime.now(timezone.utc).isoformat(),)
        )
        return cursor.rowcount
    
    def stop(self) -> None:
        self._running = False
```

### 3.26 Limitations

An honest assessment of the limits:

| Limitation | Description | Mitigation |
|---|---|---|
| **Not for distributed systems** | PURR lives on one machine | Clustering in the future |
| **WAL grows** | Needs periodic checkpointing | Auto-VACUUM |
| **Not in-memory** | Redis is faster for high-frequency caches | LRU cache layer |
| **SQLite single writer** | Concurrent writes are the bottleneck | Write queue |

### 3.27 Three-Layer Architecture

Three layers of reactivity, stacked on top of one another:

```
Layer 3: Stream (Windowed Aggregation)
  ↓ uses
Layer 2: EventBus (pub/sub + middleware)
  ↓ uses
Layer 1: Core (SSoT + Delta)
```

**Principles:**
1. **Zero-dep core** — the base state machine with no external dependencies
2. **Layered, not coupled** — EventBus uses Core, but Core knows nothing about EventBus
3. **Deterministic replay** — every state change is an event; the log reproduces the state
4. **Fail-fast validation** — a delta with an invalid field is an error, not a silent drop

### 3.28 Field Registration

Registering fields with types and validators:

```python
# purr/field_registry.py
class FieldOptions:
    default_value: Any = None
    min_value: float | None = None
    max_value: float | None = None
    validator: Callable[[Any], bool] | None = None
    persistent: bool = True

class FieldRegistry:
    def __init__(self):
        self._fields: dict[str, FieldOptions] = {}
    
    def register(self, name: str, options: FieldOptions) -> None:
        """Register a field with type and validator."""
        self._fields[name] = options
    
    def validate(self, name: str, value: Any) -> bool:
        """Validate value against field options."""
        if name not in self._fields:
            raise ValueError(f"Unknown field: {name}")
        
        opts = self._fields[name]
        if opts.min_value is not None and value < opts.min_value:
            return False
        if opts.max_value is not None and value > opts.max_value:
            return False
        if opts.validator and not opts.validator(value):
            return False
        return True
```

### 3.29 Wildcard Trie

Topic matching with wildcards:

```
"state.energy"        — exact match
"state.*"             — single-level wildcard
"state.**"            — multi-level
"#"                   — catch-all
```

```python
# purr/topic_trie.py
class TopicTrie:
    def __init__(self):
        self._root = TrieNode()
    
    def insert(self, topic: str, handler: Callable) -> None:
        """Insert a topic pattern."""
        node = self._root
        for part in topic.split("."):
            if part == "#":
                node.catch_all = handler
                return
            if part not in node.children:
                node.children[part] = TrieNode()
            node = node.children[part]
        node.handlers.append(handler)
    
    def match(self, topic: str) -> list[Callable]:
        """Find all matching handlers for a topic."""
        results = []
        node = self._root
        parts = topic.split(".")
        
        for i, part in enumerate(parts):
            if "#" in node.children:
                results.extend(node.children["#"].handlers)
            if "*" in node.children:
                results.extend(node.children["*"].handlers)
            if part in node.children:
                node = node.children[part]
            else:
                break
        else:
            results.extend(node.handlers)
        
        return results
```

### 3.30 Outbox Pattern

Events are written to an outbox before being delivered to subscribers:

```python
# purr/outbox.py
class Outbox:
    def __init__(self, db_path: str | Path):
        self._db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                delivered_at TEXT
            );
        """)
    
    def enqueue(self, topic: str, payload: Any) -> int:
        """Write event to outbox."""
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO outbox (topic, payload, created_at) VALUES (?, ?, ?)",
            (topic, json.dumps(payload), datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        return cursor.lastrowid
    
    def mark_delivered(self, event_id: int) -> None:
        """Mark event as delivered."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE outbox SET delivered_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), event_id)
        )
        conn.commit()
    
    def get_pending(self, limit: int = 100) -> list[dict]:
        """Get undelivered events."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM outbox WHERE status = 'pending' LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
```

### 3.31 Dead Letter Queue

Events not delivered after N retries:

```python
# purr/dlq.py
class DeadLetterQueue:
    def __init__(self, db_path: str | Path, max_retries: int = 3):
        self._db_path = db_path
        self._max_retries = max_retries
        self._init_db()
    
    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS dead_letters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL,
                error TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_retry_at TEXT
            );
        """)
    
    def add(self, topic: str, payload: Any, error: str) -> None:
        """Add event to DLQ."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO dead_letters (topic, payload, error, created_at) VALUES (?, ?, ?, ?)",
            (topic, json.dumps(payload), error, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
    
    def retry(self, event_id: int) -> dict | None:
        """Retry an event. Returns None if max retries exceeded."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dead_letters WHERE id = ?", (event_id,)
        ).fetchone()
        
        if not row:
            return None
        
        if row["retry_count"] >= self._max_retries:
            return None
        
        conn.execute(
            "UPDATE dead_letters SET retry_count = retry_count + 1, last_retry_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), event_id)
        )
        conn.commit()
        
        return dict(row)
```

### 3.32 Stream Windows

Windowed aggregation of events:

```python
# purr/windows.py
from enum import Enum
from typing import Callable

class WindowType(Enum):
    TUMBLING = "tumbling"    # fixed size, no overlap
    SLIDING = "sliding"      # fixed size, with overlap
    SESSION = "session"      # by inactivity gap

class WindowSpec:
    topic: str
    type: WindowType
    size: int  # seconds
    slide: int = 0  # seconds (for sliding)
    gap: int = 0  # seconds (for session)
    aggregate: Callable | None = None
    max_lateness: int = 0  # seconds

class StreamWindow:
    def __init__(self, spec: WindowSpec):
        self._spec = spec
        self._events: list[dict] = []
        self._max_timestamp: float = 0
    
    def push(self, event: dict) -> None:
        """Add event to window."""
        self._events.append(event)
        ts = event.get("timestamp", time.time())
        if ts > self._max_timestamp:
            self._max_timestamp = ts
    
    def get_result(self) -> dict:
        """Get aggregated result."""
        if self._spec.aggregate:
            return self._spec.aggregate(self._events)
        return {"count": len(self._events)}
    
    def is_closed(self) -> bool:
        """Check if window should be closed."""
        now = time.time()
        if self._spec.type == WindowType.TUMBLING:
            return now - self._events[0].get("timestamp", 0) >= self._spec.size
        return False
```

### 3.33 Built-in Aggregations

```python
# purr/aggregations.py
def aggregate_count(events: list) -> dict:
    return {"count": len(events)}

def aggregate_sum(field: str) -> Callable:
    def agg(events: list) -> dict:
        total = sum(e.get(field, 0) for e in events)
        return {"sum": total}
    return agg

def aggregate_avg(field: str) -> Callable:
    def agg(events: list) -> dict:
        values = [e.get(field, 0) for e in events]
        avg = sum(values) / len(values) if values else 0
        return {"avg": avg}
    return agg

def aggregate_min_max(field: str) -> Callable:
    def agg(events: list) -> dict:
        values = [e.get(field, 0) for e in events]
        return {"min": min(values), "max": max(values)} if values else {"min": 0, "max": 0}
    return agg

def aggregate_histogram(field: str, bins: list[float]) -> Callable:
    def agg(events: list) -> dict:
        values = [e.get(field, 0) for e in events]
        hist = [0] * (len(bins) + 1)
        for v in values:
            for i, b in enumerate(bins):
                if v < b:
                    hist[i] += 1
                    break
            else:
                hist[-1] += 1
        return {"histogram": hist, "bins": bins}
    return agg

def aggregate_topk(field: str, k: int) -> Callable:
    def agg(events: list) -> dict:
        values = [e.get(field, 0) for e in events]
        sorted_vals = sorted(values, reverse=True)[:k]
        return {"topk": sorted_vals}
    return agg
```

### 3.34 Metrics Export

```python
# purr/metrics_export.py
class MetricsExporter:
    def counter(self, name: str, value: int, labels: dict = None) -> None: ...
    def gauge(self, name: float, value: float, labels: dict = None) -> None: ...
    def histogram(self, name: str, value: float, labels: dict = None) -> None: ...

class PrometheusExporter(MetricsExporter):
    def __init__(self):
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
    
    def counter(self, name, value, labels=None):
        key = f"{name}_{labels}" if labels else name
        self._counters[key] = self._counters.get(key, 0) + value
    
    def gauge(self, name, value, labels=None):
        key = f"{name}_{labels}" if labels else name
        self._gauges[key] = value
    
    def histogram(self, name, value, labels=None):
        key = f"{name}_{labels}" if labels else name
        if key not in self._histograms:
            self._histograms[key] = []
        self._histograms[key].append(value)
    
    def export(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        for k, v in self._counters.items():
            lines.append(f"purr_{k} {v}")
        for k, v in self._gauges.items():
            lines.append(f"purr_{k} {v}")
        for k, values in self._histograms.items():
            lines.append(f"purr_{k}_count {len(values)}")
            lines.append(f"purr_{k}_sum {sum(values)}")
        return "\n".join(lines)
```

### 3.35 Graceful Shutdown

```python
# purr/shutdown.py
import asyncio

async def graceful_shutdown(stream=None, bus=None, core=None, timeout: float = 30.0):
    """Shut down components in order: Stream → Bus → Core."""
    ctx = asyncio.wait_for(asyncio.sleep(timeout), timeout=timeout)
    
    if stream:
        await stream.close()
    if bus:
        await bus.close(ctx)
    if core:
        core.close()
```

### 3.36 Deterministic Replay

```python
# purr/replay.py
class ReplayEngine:
    def __init__(self, core):
        self._core = core
        self._log: list[dict] = []
    
    def record(self, delta: dict, source: str) -> None:
        """Record delta for replay."""
        self._log.append({
            "delta": delta,
            "source": source,
            "timestamp": time.time(),
        })
    
    def replay(self) -> None:
        """Replay all recorded deltas."""
        for entry in self._log:
            self._core.apply_delta(entry["delta"], entry["source"])
    
    def save_log(self, path: str) -> None:
        """Save replay log to file."""
        with open(path, "w") as f:
            json.dump(self._log, f)
    
    def load_log(self, path: str) -> None:
        """Load replay log from file."""
        with open(path, "r") as f:
            self._log = json.load(f)
```

### 3.37 Testing Strategy

The key tests:

1. **Replay test** — record a log, recreate Core, apply the log → the final state is identical
2. **Crash recovery test** — kill the process, restart → the state comes from the last snapshot
3. **Concurrency test** — 100 threads calling ApplyDelta at once → not a single race
4. **Backpressure test** — EventBus with a slow subscriber → the buffer does not overflow

### 3.38 Missing Items from Cross-Check

Additions after reconciling four design documents.

#### From the architecture review:
- **MSET/MGET** — atomic multi-key write/read (Phase 1)
- **EXISTS** — check whether a key exists (Phase 1)
- **PubSub subscriber_type + callback_url** — webhook delivery (Phase 3)
- **Persistent pubsub_messages table** — three tables for PubSub (Phase 3)

#### From the engine specification:
- **Core API methods** — SubscribeRaw, AddEvent, Close (Phase 1)
- **Config functional options** — WithInitialState, WithMaxLastEvents, etc. (Phase 1)
- **InteractionCount** — an interaction counter in the Snapshot (Phase 1)
- **Fail-fast validation** — the "error, not a silent drop" principle (Phase 1)
- **Named metrics** — nine concrete names (Phase 5):
  - `purr_state_fields`, `purr_delta_total`, `purr_delta_errors_total`
  - `purr_eventbus_published_total`, `purr_eventbus_delivered_total`, `purr_eventbus_dropped_total`
  - `purr_stream_windows_active`, `purr_stream_events_windowed_total`
  - `purr_persist_duration_seconds`
- **Exporters** — OpenTelemetry, Log-based (Phase 5)
- **Use cases** — Game Dev, Edge/Serverless, DevTools, Education (Use Cases)
- **EmitTrigger types** — EmitOnClose, EmitOnInterval, EmitOnThreshold (Phase 3)
- **Watermark algorithm** — maxTimestamp - maxLateness (Phase 3)
- **Code of Conduct** — safe space (Launch)
- **Star goals** — 50/100/500 stars (Launch)
- **Repository structure** — Go-targeted tree (Architecture)
- **Integration test layout** — replay_test.go, persistence_test.go, bench_test.go (Phase 6)

---

## 4. Architecture Evolution

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
