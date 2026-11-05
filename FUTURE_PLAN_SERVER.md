# PURR — Server Roadmap (вынесено, отложено)

> **Status:** Отложено / deferred
> **Date:** 2026-11-04
> **Решение владельца (2026-11-04):** «Берем за основу концепцию А, сервер возможно потом».
> **Vision (исторический, не активный):** сетевой сервер, совместимый с Redis, с кластером и репликацией.
>
> Этот документ не входит в активный план. Он сохраняет дословно разделы, перенесённые из `FUTURE_PLAN.md` 2026-11-04, чтобы решение владельца не привело к потере наработок. Возврат к серверу требует отдельного решения и отдельного ADR. Содержимое ниже — исторический черновик от 2026-07-24, он не описывает текущий продукт и не является обещанием.

### Шапка исходного черновика (снимок на 2026-07-24)

> **Status:** Draft
> **Date:** 2026-07-24
> **Vision:** A full Redis-like database engine on SQLite

---

## Phase 3: Networking (из раздела 2)

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

---

## Серверные строки таблиц Phase 4 и Phase 5

Исходные строки таблицы приоритетов, перенесённые дословно:

| **Cluster** | Multi-node replication | P2 |
| **Persistence** | RDB snapshots + AOF | P1 |
| **TLS** | Encrypted connections | P2 |
| **Auth** | Password/AUTH command | P1 |
| **Client Library** | Python client for remote access | P1 |
| **Docker** | Docker image | P1 |

---

## Redis-совместимый вывод CLI (из 3.14)

Команда и её вывод из примера CLI:

$ purr info
# Server
redis_version:0.1.0-purr
uptime_in_seconds:12345
# Keyspace
db0:keys=42,expires=10,avg_ttl=3600

---

## Команды purr serve (из 3.14)

purr serve --port 6379          # Redis-compatible protocol (RESP)
purr serve --http --port 8080   # HTTP API

---

## 3.6 Replication и 3.7 Sharding

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

---

## 3.18 Key Decisions — решение по RESP

- **RESP is not required in v1**: start with HTTP + the Python SDK

---

## 3.23 REST API Spec

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

---

## 3.24 MCP Integration

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

---

## 3.26 Limitations — кластеризация

| **Not for distributed systems** | PURR lives on one machine | Clustering in the future |

---

## Target (v1.0.0): целевая архитектура

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

---

## 6. Comparison with Redis — серверные строки

| **Replication** | Master-slave | Planned (Phase 4) |
| **Cluster** | Redis Cluster | Planned (Phase 4) |
| **Protocol** | RESP | Planned (Phase 3) |
- Cluster support

---

## 7. Milestones — серверные этапы

| Milestone | Features | ETA |
|---|---|---|
| **v0.4.0** | TCP Server, HTTP API | 3 weeks |
| **v0.5.0** | Pub/Sub, Auth | 1 month |
| **v0.6.0** | Client Library, CLI | 1.5 months |
| **v0.7.0** | Cluster, Replication | 2 months |
| **v1.0.0** | Full Redis compatibility | 3 months |

---

## 8. Open Questions — серверные вопросы

1. **RESP Protocol**: Implement full RESP2 or simplified version?
2. **Persistence**: RDB snapshots vs AOF vs both?
3. **Cluster**: Consensus algorithm (Raft vs Paxos)?
4. **Auth**: Password-only or ACL-based?

---

## 3.38 Missing Items — сетевые пункты

- **PubSub subscriber_type + callback_url** — webhook delivery (Phase 3)
- **Persistent pubsub_messages table** — three tables for PubSub (Phase 3)
- **EmitTrigger types** — EmitOnClose, EmitOnInterval, EmitOnThreshold (Phase 3)
- **Watermark algorithm** — maxTimestamp - maxLateness (Phase 3)

---
