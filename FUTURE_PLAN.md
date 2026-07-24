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
| **Metrics** | Reads/sec, TTL hits, DB size tracking | P1 |
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

## 3. Advanced Ideas (from redis.md)

Дополнительные идеи для развития PURR beyond basic Redis compatibility.

### 3.1 Key Versioning (Point-in-Time Recovery)

Каждая SET пишет новую версию в историю. GET без параметров — последняя. GET с `?version=N` — конкретная.

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

**Преимущества над Redis:** Point-in-time recovery из коробки. Ни один Redis так не умеет.

### 3.2 Lazy TTL (ленивая экспирация)

Не сканировать всю базу каждую секунду — чистить при GET/SET.

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

### 3.3 Write Queue (конкурентная запись)

SQLite не терпит конкурентной записи. Нужна очередь.

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

### 3.4 FTS5 (полнотекстовый поиск)

SQLite FTS5 для индексации ключей и значений.

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

In-process очередь для локальных подписчиков + SQLite events для внешних.

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

Мастер шлёт WAL-логи, слейвы применяют диффы.

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

Каждая партиция в отдельном SQLite-файле.

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

SQLite для persistence, LRU слой для скорости.

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

PURR как embedded хранилище для mobile/embedded систем.

**Преимущества:**
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

Один пакет — два режима работы (из statebus-spec.md):

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

Чистый API для两种 режимов:

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
purr serve --port 6379          # Redis-совместимый протокол (RESP)
purr serve --http --port 8080   # HTTP API
purr inspect data/purr.db       # Показать содержимое
purr stats data/purr.db         # Статистика: чтений/записей, размер WAL
purr dump data/purr.db          # Дамп в JSON
purr vacuum data/purr.db        # VACUUM + восстановление размера
```

### 3.15 Auto-VACUUM

SQLite без VACUUM растёт. Автоматический VACUUM при превышении порога:

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

**Месседж первой строки:**

> **PURR — SQLite, который отвечает как Redis. Одна библиотека — три модуля: Store, StateMachine, EventBus.**

**УТП:**
1. Zero dependency — `pip install purr` и готово
2. Три модуля в одном пакете — KV + FSM + Events
3. SQLite WAL — данные не теряются
4. EventBus middleware — RateLimit, Dedup, Transform из коробки
5. Atomic write — temp file + rename, ни одного битого файла

**Кому нужно:**
- Разработчикам агентов — внутреннее состояние (настроение, энергия)
- Backend-разработчикам — замена Redis для маленьких проектов
- Хобби-проектам на VPS — каждая зависимость считается
- Dev-средам — не хочется поднимать Redis для тестов

### 3.17 Competitive Analysis

| Решение | StateMachine | KV Store | EventBus | SQLite |
|---------|:---:|:---:|:---:|:---:|
| **PURR** | ✅ | ✅ | ✅ | ✅ |
| `redis` | ❌ | ✅ (родной) | ❌ | ❌ |
| `sqlite-redis` | ❌ | Partial | ❌ | ✅ |
| `pickle + файл` | ⚠️ самописно | ❌ | ❌ | ❌ |

**PURR — единственный, кто даёт и StateMachine, и KV, и EventBus — на чистом SQLite, без сервера.**

### 3.18 Key Decisions (из spec)

- **WAL обязателен**: `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`
- **Sync API — фича**: для маленьких операций асинхронность — оверхед
- **VACUUM автоматический**: при превышении порога (50% dead data)
- **RESP не обязательно в v1**: начать с HTTP + Python SDK

### 3.19 Launch Strategy

- **PyPI**: `pip install purr`
- **Hacker News**: "I replaced Redis with a SQLite file — here's the library"
- **GitHub**: README с бейджами и release notes
- **Документация**: MkDocs или аналог

### 3.20 Streams with Consumer Groups (из sqredis_ARCH.md)

Расширенные streams с consumer groups для балансировки нагрузки.

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

**Операции:**
- `XADD(stream, data)` — добавить запись
- `XREAD(stream, from_id, count)` — чтение с позиции
- `XREADGROUP(group, consumer, count)` — чтение с балансировкой
- `XACK(group, consumer, entry_id)` — подтверждение
- `XTRIM(stream, maxlen)` — усечение
- `XDEL(stream, entry_id)` — удаление одной записи

### 3.21 Saga with SQL Savepoints (из sqredis_ARCH.md)

Саги с настоящим откатом через SQLite savepoints.

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

**Схема работы:**
```sql
BEGIN;
    INSERT INTO kv_store ...;      -- Шаг 1
    INSERT INTO stream_entries ...; -- Шаг 2
    INSERT INTO pubsub_messages ...; -- Шаг 3
COMMIT;
-- Если COMMIT не удался — всё откатилось на уровне SQLite
-- Если бизнес-логика упала ПОСЛЕ COMMITа — запуск компенсации
```

### 3.22 Extended Middleware (из sqredis_ARCH.md)

6 встроенных middleware (у нас 5, добавляем Validate и Metrics):

| Middleware | Назначение | Конфиг |
|---|---|---|
| RateLimit | N событий за окно | RateLimit(count, window_seconds) |
| Dedup | Дедупликация по хешу | Dedup(hash_fields, window_seconds) |
| Transform | Обогащение (timestamp, source) | Transform(enrichers...) |
| Logging | Аудит | Logging(output, level) |
| **Validate** | **Валидация схемы** | **Validate(json_schema)** |
| **Metrics** | **Сбор метрик** | **Metrics(prometheus_registry)** |

### 3.23 REST API Spec (из sqredis_ARCH.md)

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
GET    /stats                — Статистика
```

### 3.24 MCP Integration (из sqredis_ARCH.md)

Тулы для интеграции с AI-агентами:

```python
# MCP tools
sqredis_set(key, value, ttl=None)       # SET
sqredis_get(key)                        # GET
sqredis_del(key)                        # DEL
sqredis_keys(pattern)                   # LIKE-поиск

sqredis_publish(channel, payload)       # PUBLISH
sqredis_subscribe(channel)              # SUBSCRIBE

sqredis_stream_add(stream, data)        # XADD
sqredis_stream_read(stream, from_id)    # XREAD

sqredis_saga_begin()                    # BEGIN SAGA
sqredis_saga_step(saga_id, type, data)  # ADD STEP
sqredis_saga_execute(saga_id)           # EXECUTE
```

### 3.25 TTL Daemon (из sqredis_ARCH.md)

Фоновая горутина для очистки истёкших данных:

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

### 3.26 Limitations (из sqredis_ARCH.md)

Честная оценка ограничений:

| Ограничение | Описание | Решение |
|---|---|---|
| **Не для распределённых систем** | PURR живёт на одной машине | Кластер в будущем |
| **WAL растёт** | Нужна периодическая checkpoint | Auto-VACUUM |
| **Не in-memory** | Для high-frequency кэшей Redis быстрее | LRU cache layer |
| **SQLite single writer** | Конкурентная запись — узкое место | Write queue |

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
