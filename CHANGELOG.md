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
- `EventStream.reset_cursor(name) -> bool` — drops a named cursor and returns
  whether it existed. Retention leaves cursors pointing at pruned events in
  place, which makes `read(cursor=...)` raise `ValueError` with no recovery
  through the API; `reset_cursor()` is the documented way to restart that
  consumer from the beginning.

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
- `EventStream.read()` returns `last_event_id=None` when there is nothing new
  (annotation is now `tuple[list[Event], str | None]`); the documented consumer
  loop guards the write-back with `if last_id:`. Writing that `None` back used
  to store SQL `NULL`, which read from the beginning of the stream — an endless
  replay loop.
- `EventStream.set_cursor()` rejects an empty/`None` event id with
  `ValueError`: use `reset_cursor(name)` to clear a cursor on purpose.

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
- `EventStream.append()` now rolls back the failed transaction before raising
  `ValueError` on a duplicate id (pass-2 audit regression): the rejected
  `INSERT` used to leave an open write transaction holding a `RESERVED` lock
  on the whole database file, so every other writer — other threads, other
  engines on the same file, fresh connections — blocked with
  `OperationalError: database is locked` until `close()`. `append_many()`
  already did this; `append()` now matches.
- README contracts aligned with actual behavior: saga is in-memory and its
  rollback covers previously completed steps only; TTL expiry is lazy;
  suite size updated.
- `EventStream._prune()` now commits whenever the connection holds a
  transaction, not only when rows were actually deleted (pass-3 regression):
  the `DELETE`s open an implicit transaction even with `rowcount == 0`, so
  with retention configured but nothing yet to prune, `maintain()` left a
  `RESERVED` lock on the whole file — a second instance's `append()` failed
  with `database is locked` after the 5 s busy timeout. A periodic maintainer
  could pin the database forever.
- `SQLiteBackend.run_migrations()` no longer writes when the schema is
  already current (pass-3 regression): the registry `CREATE TABLE`/`INSERT OR
  REPLACE` and the `user_version` clamp ran on every open, so an
  already-migrated read-only database raised `attempt to write a readonly
  database` and a concurrent opener waited out the 5 s busy timeout
  (`database is locked`). Writes now happen only when migrations are pending
  or `user_version` still needs clamping; if the database rejects that
  bookkeeping while no migration is pending, opening continues. Cold-start
  with 8 processes on a fresh file: 6/80 → 0/80 failures.
- `EventStream._prune()` keeps the newest events in the order `read()` walks
  them. Retention now ranks by `(timestamp, rowid)` DESC instead of `rowid`
  alone (pass-4 audit): with a producer writing out of timestamp order,
  `max_events` discarded the *newer* event and kept the older one, so a
  consumer positioned on the newest event got a permanent `ValueError` even
  though its cursor pointed at an event that should have survived.
- `EventStream.append_many()` rolls back on any exception, not just
  `IntegrityError` (pass-3 regression): a mid-batch `TypeError` (payload not
  JSON serializable) left the already-inserted events in an open transaction,
  and the next unrelated `append()` committed them — the "rolled back" batch
  reappeared. The `ValueError` contract for duplicate ids is unchanged.
- `Store.incr()` issues `BEGIN IMMEDIATE` only when the connection is not
  already in a transaction (pass-3 regression): a leftover implicit
  transaction — a raw write through the shared connection, or, before the
  pass-4 fix below, a failed `mset()`/`set()` — made `incr()` die with `cannot
  start a transaction within a transaction`. It now reuses the implicit
  transaction and commits at the end.
- `Store.set()`, `mset()` and `delete()` roll back a partially applied write
  before re-raising (pass-4 audit): a `TypeError` while serializing the
  second value of `mset()` or an `OSError` from a huge `ttl` in `set()` used
  to leave the
  half-written rows in an open implicit transaction holding a `RESERVED` lock,
  and the next unrelated `commit()` made them durable — `set("good", 1)` plus
  `set("bad", object())` resurrected `good`. Inside `transaction()` the
  rollback is left to the context manager, whose `finally` already handles it;
  a caller that catches the error and commits anyway still commits that op's
  partial rows, because per-op savepoints are not part of the no-nesting
  contract.
- Saga write tracking no longer compares old and new values with a bare `!=`
  and no longer relies on a shallow snapshot: a step writing an array-like
  value (`numpy.ndarray`, `pandas.Series`) used to raise `ValueError: truth
  value ... is ambiguous` *inside* the step's own try block, so a successful
  step was marked `failed`, the saga compensated and the caller got that
  `ValueError` instead of the real failure. Steps now record the previous
  values of the keys they touched (`SagaStep.restore`) from a deep snapshot,
  so in-place nested mutations are rolled back too. Rollback restores the old
  value of overwritten keys and re-adds keys the step deleted, instead of
  `pop()`-ing them out of `saga.data`.

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
- `JournalFlushError` (`purr.store`, exported as `purr.JournalFlushError`) —
  raised by `transaction()` when the commit succeeded but some buffered journal
  events could not be written (pass-4 audit). The message says so explicitly
  ("transaction committed, but N journal events failed to flush", data is
  durable), so a journal outage is no longer indistinguishable from a
  rollback. Failed payloads are collected and the rest still flushed.

### Changed
- `Store.incr()` emits its journal event after its own commit, matching
  `set()`/`mset()`/`delete()` (pass-4 audit): the event used to be appended
  inside the write transaction, so subscribers saw data that was not committed
  yet, and on a shared file (`Store(db, journal=EventStream(db))`) `incr()`
  waited out the 5 s busy timeout on its own `RESERVED` lock and failed with
  `database is locked` while `set()` worked. Inside `transaction()` the event
  is still buffered until the block commits.
- `Store.transaction()` flushes the journal after the commit and outside the
  rollback path (pass-4 audit): a failing flush no longer drops the caller into
  a rollback branch that cannot undo anything. Every buffered event is
  attempted — one rejected event no longer drops the rest — and partial loss
  raises `JournalFlushError`.
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
