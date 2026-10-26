# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Breaking
- `EventStream.append()` is now truly append-only: appending an event whose
  id already exists raises `ValueError` instead of silently overwriting the
  original event (P1-5). Code that relied on overwrite-by-id must switch to
  explicit delete/recreate or new ids.

### Added
- `EventStream.append_many()` — atomic batch append (duplicate id rolls back
  the whole batch); ~10× faster than per-event appends.
- Schema migration v2 for `EventStream`: composite index
  `idx_events_topic_ts (topic, timestamp)` — measured 20.10 → 0.74 ms/op on
  100k events for `read(cursor, topic)`.
- Per-engine migration registry: `_purr_schema (engine, version)` table lets
  `Store`, `EventStream` and `StateMachine` share one database file without
  skipping each other's migrations (P1-8). `PRAGMA user_version` is still
  raised for compatibility; legacy databases (user_version > 0, no registry)
  are upgraded by re-applying migrations idempotently.

### Changed
- `incr()`/`decr()` are atomic (own `BEGIN IMMEDIATE` when outside
  `transaction()`); expired keys are not resurrected — incrementing an
  expired or missing key starts from 0 (Redis semantics); TTL of a live key
  is preserved (P1-3, P1-4).
- `publish_sync()` now delivers to subscribers: sync handlers directly,
  async handlers via `asyncio.run()` outside a loop; inside a running loop
  it raises `RuntimeError` directing to `await publish()` (P1-7).
- Saga `execute()` resets per-step state, so re-executing a saga never fires
  compensations left over from a previous run; compensation now also removes
  the keys a compensated step wrote from `saga.data` (P1-6).

### Fixed
- P1-1: failed `BEGIN IMMEDIATE` no longer poisons the transaction flag
  (records were silently lost afterwards).
- P1-2: transaction flag is thread-local, matching the per-thread
  connections.
- P1-3/P1-4: see Changed — atomic `incr` with Redis expiry semantics.
- P1-5: see Breaking — enforced append-only event stream.
- P1-6: see Changed — saga re-execution and data rollback.
- P1-7: see Changed — `publish_sync` delivery.
- P1-8: see Added — per-engine migration registry for shared db files.
- README contracts aligned with actual behavior: saga is in-memory and its
  rollback covers previously completed steps only; TTL expiry is lazy;
  suite size updated.

### Added
- `EventStream(..., max_events=..., max_age_seconds=...)` retention limits
  (P2-2): `maintain()` now prunes the log when limits are configured —
  oldest events by `max_age_seconds` (timestamp) and/or events beyond
  `max_events` (newest kept). The report gains a `pruned_events` key.
  Default (`None`/`None`) is unchanged: no pruning.
- `EventBus(on_handler_error=...)` optional callback (P2-4): invoked as
  `(event, exception)` when a subscriber handler raises, instead of the
  exception being silently swallowed. Default `None` keeps the historical
  silent behavior. Exceptions in the callback itself are swallowed so the
  dispatcher never breaks.

### Changed
- `EventStream.read()` cursor semantics (P2-1): reading with a cursor id
  that does not exist in the stream now raises
  `ValueError("cursor references missing event id: ...")` — previously it
  silently returned `[]` forever, deadlocking consumers. An empty read
  (no new events) now returns `last_event_id=None` instead of `""`, so a
  consumer saving it cannot accidentally replay from the beginning.
  `cursor=None` (default) still reads from the beginning of the stream.
- `Store.mset()` now emits journal events *after* the commit, matching
  `set()`/`delete()` ordering (P2-3): journal consumers never observe
  uncommitted (or rolled-back) mset data. Inside an explicit
  `transaction()` behavior is unchanged (buffered, flushed after commit).
- `Store`'s internal journal buffer is per-thread (P2-5), matching the
  per-thread connections and transaction flag: concurrent `transaction()`
  blocks in different threads no longer mix or drop each other's buffered
  journal events.

## [0.1.0] - 2026-10-07

First public release. The distribution is named **`py-purr`** and imported as
**`purr`** — see Packaging below for why the two differ.

> Nothing was published before this release, so everything below ships as
> `0.1.0`. There is no earlier version on PyPI to upgrade from.

### Added
- Opt-in mutation journal: `Store` and `StateMachine` append mutation/transition
  events to an `EventStream` (`journal=`), replayable by folding the stream.
- `Store.transaction()` atomic blocks with deferred commits and rollback.
- `Store.sweep()` expired-key cleanup.
- `StateMachine.prune_snapshots(keep)` snapshot retention.
- `EventStream.count_since()` trailing-window counts (compute-on-read).
- `maintain()` reports on `Store`/`StateMachine`/`EventStream`
  (sweep/prune, checkpoint, integrity, file sizes).
- `SQLiteBackend` shared base: connection lifecycle, pragmas
  (WAL, `busy_timeout=5000`), checkpoint, integrity check, backup, stats.
- `user_version` migration runner; all engines declare `MIGRATIONS`.
- Contract tests locking README tours; coverage for health, middleware,
  retry and versioning modules.

### Fixed
- `Store.delete()` on missing keys returned `True` (used cumulative
  `total_changes`); now uses cursor `rowcount`.
- `transaction()` never committed (data visible only inside the connection);
  now commits on clean exit, rolls back on error.
- Stream cursor ordered by timestamp only: same-microsecond events were lost;
  now ordered by `(timestamp, rowid)`.
- `keys()` treated `%` and `_` as wildcards; now escaped (only `*` is special).
- `incr()` truncated floats via `int()`; fractional values preserved.

### Changed
- Middleware pipeline chain simplified (same order semantics, B023-clean).
- `str, Enum` mixins moved to `StrEnum`; `contextlib.suppress` for
  close-paths; `collections.abc` imports.
- Instance-isolation contract documented on all engines (own connection
  per instance, safe file sharing, `close()` discipline).

### Packaging
- **Distribution renamed to `py-purr`.** The name `purr` on PyPI already belongs
  to an unrelated package, so `pip install purr` would fetch somebody else's
  library. The **import is unchanged**: `from purr import Store`.
- `pyproject.toml` filled in for a public release: `authors`, `keywords`,
  `classifiers`, `[project.urls]`, and an explicit `packages = ["purr"]`.
- Version is now dynamic, read from `purr/__init__.py`, so the wheel metadata
  and `purr.__version__` cannot drift apart.
- README install line, CI badge and clone instructions updated to the new
  repository name.

### Docs
- README tours rewritten to match the real API (verified by execution);
  test count updated.
- English docstrings for all public API.
- `FUTURE_PLAN.md` translated to English, with the references to internal
  design documents removed — they pointed at files that were never part of
  this repository.

### CI
- `ruff check` + `ruff format --check` + coverage gate (`--fail-under=85`).
- Test matrix extended to Python 3.11/3.12/3.13.
- New `package` job: builds the sdist and wheel, installs the wheel into an
  empty environment and imports it. The test matrix imports `purr` from the
  source tree, so it would not notice a broken wheel.
- New CodeQL workflow (`security-extended`), gated on repository visibility.
- New publish workflow for PyPI via Trusted Publisher (no token in the repo),
  which refuses to publish unless the git tag matches the version in
  `purr/__init__.py`.
- `concurrency` cancel-in-progress, and workflow action versions updated
  (`checkout@v7`, `setup-python@v7`, `codeql-action@v4`).
