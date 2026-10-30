# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Breaking
- **The journal event shape changed.** `flush()` now emits one
  `{"op": "flush"}` event instead of a `delete` per key, and `set`/`incr`/
  `mset` events carry `expires_at` when the key has an expiry. A consumer
  that replays the journal must handle the new op and the new field. The
  `flush` event carries neither `key` nor `value`: a reader that indexes
  those fields directly raises `KeyError` on it, while one that uses
  `.get()` is unaffected — both measured. A replayer that silently skips
  ops it does not know loses `flush` and keeps deleted keys alive.
- **The journal is co-located with the data (ADR-001, variant C).** `Store`
  and `StateMachine` now reject a journal that lives in another file:
  `Store("purr.db", journal=EventStream("events.db"))` raises `ValueError` at
  start-up, and so does `StateMachine(..., journal=EventStream("events.db"))`.
  Two files cannot share one transaction, so an event could be lost after the
  data was committed with nothing left to report the gap. Pass
  `EventStream(<the same path>)` or no journal at all.
- A failing event insert now **rolls the data back**. The event is written
  inside the data's transaction, so "the data is durable, the journal is not"
  is no longer a reachable state: a journal write that raises — a full disk, a
  locked file, a payload SQLite refuses — takes the mutation with it, and the
  caller gets the ordinary `sqlite3` error from the write instead of a
  successful commit with a gap behind it. Inside `transaction()` the whole
  block is undone, not just the operation that failed. Catch `sqlite3.Error`
  where the code used to expect a committed write.
- `JournalFlushError` is **removed**, class and export together:
  `purr.JournalFlushError` raises `AttributeError` and
  `from purr.store import JournalFlushError` raises `ImportError`. It reported
  the one state that can no longer happen — a commit that succeeded while its
  events did not.
- The journal **buffer and the post-commit flush step are gone**. Events used
  to be queued per thread and written after the commit; now each one is written
  where it happens. When a call returns, its event is either committed with the
  row or the call failed: there is no longer a window in which the data is
  durable and the event is still pending, and nothing to flush at the end of a
  transaction.
- **Upgrading a two-file deployment.** The old `events.db` remains a readable
  standalone stream and nothing is deleted, but the journal in the data file
  starts empty. Open the store once with `EventStream(<the data file>)` — that
  creates the `events` and `cursors` tables there — then merge the old log
  with `ATTACH DATABASE 'events.db' AS old`, `INSERT OR IGNORE INTO events
  SELECT * FROM old.events` and the same for `cursors`. The cursor rows move
  with the events, so consumers resume where they stopped. Skipping the merge
  leaves a consumer whose saved cursor id came from the old file with
  `ValueError("cursor references missing event id")`; `reset_cursor(name)`
  restarts it from the beginning of the new log. README carries the runnable
  recipe.
- `EventStream.append()` is now truly append-only: appending an event whose
  id already exists raises `ValueError` instead of silently overwriting the
  original event (P1-5). Code that relied on overwrite-by-id must switch to
  explicit delete/recreate or new ids.
- `EventStream(...)` validates its retention limits at construction
  (pass-6 audit): `max_events` must be `None` or an `int >= 1`,
  `max_age_seconds` must be `None` or a number `> 0`; otherwise `ValueError`.
  `max_events=0` used to mean "prune the whole stream" — it is now rejected
  (delete explicitly with `clear()`), as are negatives (`-1` reached SQLite as
  `LIMIT -1`, i.e. every pruning statement deleted nothing and retention was
  silently off), floats (`2.9` died later with
  `sqlite3.IntegrityError: datatype mismatch`), numeric strings (`"2"` was
  coerced silently) and booleans.
- **Reading an expired key no longer deletes it.** `get()`, `exists()` and
  `mget()` answer an expired key as missing — `None`, `False`, and `None` in
  the requested position — and leave the row where it is: no `DELETE`, no
  `delete` event in the journal, no write on the read path. Physical cleanup
  belongs to `sweep()` and `maintain()`. What changes for you: an expired key
  stays in `keys()` and still counts in `size()` until one of those runs, and
  the journal no longer carries a `delete` event for every read that happened
  to touch a dead key. Code that sized its store by `size()`, watched the
  journal for `delete`, or leaned on `get()` to clean up after itself must
  call `sweep()` on its own schedule.

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
- `Store.set/delete/expire/incr/mset` and `StateMachine.send/set_state` write
  their journal event **inside the data's transaction** instead of after the
  commit: no second commit, no per-thread journal buffer, no flush step. The
  event and the row it describes are committed or rolled back together, so the
  crash window between them is gone by construction (measured: a batch of 500
  keys killed mid-flight leaves `разрыв 0`).
- `EventStream.insert_in(conn, event)` — insert an event on a caller-owned
  connection and transaction (no commit). Used by the engines that share the
  file; `append()` keeps its own-commit, duplicate-id contract.
- `EventStream.db_path` — the file the stream is bound to, so an engine can
  check that its journal is co-located before writing anything.
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
- `sweep()` journals every removal and `flush()` writes a single `flush`
  event. Both used to delete rows with raw SQL and write nothing, so a
  replay kept the removed keys alive. One event for `flush` instead of one
  per key: the journal should grow with operations, not with rows —
  measured on 50 000 keys, per-key events took the call from 122 ms to
  1.6 s and grew the file by half.
- `set(..., ttl=)`, `incr()` and `mset()` now record `expires_at` in the
  journal event when the key has an expiry. Without it a replay turned a
  key that should vanish into one that lives forever. Events for keys
  without a TTL carry no such field, so journals written before this
  change replay exactly as they did.
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
  rollback covers previously completed steps only; TTL expiry is lazy — a
  read reports an expired key as missing and leaves it in place (see
  Breaking); suite size updated.
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
- `publish_sync()` (pass-6 audit) detects a running event loop *before*
  dispatching: it used to call every sync handler while merely collecting
  coroutines and only then raise `RuntimeError`, so the side effects were
  already committed when the caller was told the call cannot work. Delivery
  also follows subscription order now — an `async def` handler subscribed
  first runs first; before, async handlers were all pushed to the end
  (`async-1, sync-2, sync-3` arrived as `sync-2, sync-3, async-1`).
- An async `on_handler_error` callback is no longer a lost coroutine
  (pass-6 audit): `publish()` awaits it, `publish_sync()` runs it with
  `asyncio.run()` or closes it when a loop is running. It used to fail with
  `RuntimeWarning: coroutine ... was never awaited` and the error vanished.
- `close()` resets the calling thread's per-thread state — `conn`, `in_txn`
  and the journal buffer (pass-6 audit). Closing inside a transaction left
  `in_txn=True` and a stale buffer behind, so every later `transaction()` on
  that thread died with "nested transaction() is not supported", forever.
  Other threads' state is untouched (their connections are a separate known
  issue).
- `run_migrations()` writes the *final* version to the `_purr_schema`
  registry (pass-6 audit): the row was written before the clamp, so with
  `SCHEMA_VERSION=3` and `MIGRATIONS={1}` the registry recorded 1 while
  `PRAGMA user_version` said 3, and the registry stayed at 1 for good. The row
  and `user_version` now hold the same value — the highest applied migration,
  capped at `SCHEMA_VERSION`. `SCHEMA_VERSION` is a ceiling, never a claim:
  registering 3 would make a v2/v3 migration added later look applied and
  silently skip it.
- A migration script now runs inside one transaction (pass-7 audit):
  `executescript()` committed each statement implicitly, so a script that
  failed half-way left the tables it had already created behind while the
  version stayed 0 — and because those tables then existed, the same script
  could never succeed on retry, making the database permanently unopenable.
  A failure now rolls the whole script back.
- `EventVersioner.migrate()` no longer mutates the event it is given
  (pass-7 audit): it returns a deep copy. Rewriting `payload`/`version` in
  place corrupted objects already held by `EventBus` history and event streams,
  which breaks the immutability event sourcing relies on.
- `RetryHandler` clamps the delay *after* applying jitter (pass-8): the
  effective maximum was 1.5 × `max_delay`. The never-written `_pending` state
  was removed.
- A health check returning something that is neither `bool` nor `HealthStatus`
  is reported as `UNHEALTHY` with the offending type in the message (pass-8):
  the status used to be left unchanged, so a check returning `"ok"` silently
  counted as neither healthy nor unhealthy.
- `db_stats()` reports the real WAL size for a database path without a file
  extension. SQLite appends to the whole file name (`store` → `store-wal`,
  `store.db` → `store.db-wal`), but the size was read from `<path>.db-wal`,
  which does not exist, so a suffix-less database answered `wal_bytes: 0` no
  matter how much WAL was on disk — 61 832 bytes in the audit probe, and a
  monitor reading `db_stats()` saw an empty WAL. Paths with a `.db` suffix and
  `:memory:` report exactly what they did before.
- The crash stand's `run-journal` mode (`tools/crash_harness.py`,
  `cmd_verify_journal`) refuses on a journal gap: the gap was computed and
  printed, but the exit condition looked only at lost confirmed keys, phantom
  events and integrity, so a run whose journal lagged behind KV exited `0` and
  passed the stand. A gap now exits `1` like the other divergences, and `0`
  means KV and the journal agree on every key. Measured: `run-journal 1` on a
  healthy database reports `разрыв 0` → `exit=0`; the same check on a copy with
  one journal event deleted reports `gap=1` → `exit=1`.

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
  **Superseded before release:** the class is removed — the state it reported
  (commit succeeded, events did not) no longer exists; see Breaking.
- `MigrationGapError` (`purr.versioning`, exported as `purr.MigrationGapError`)
  — raised when a migration chain has a hole (pass-7 audit). A missing hop used
  to `break` out of the loop and hand the consumer a pre-migration payload with
  no signal at all.
- Store schema v2: index `idx_kv_meta_expires` on `kv_meta(expires_at)`
  (pass-8 audit). `sweep()` scanned the whole table: 3.13 ms → 0.005 ms per
  sweep on 50k TTL rows.
- `EventStream.append_many(events)` — atomic batch insert, ~10–15× faster than
  per-event `append()`.

### Changed
- `Store.incr()` emits its journal event after its own commit, matching
  `set()`/`mset()`/`delete()` (pass-4 audit): the event used to be appended
  inside the write transaction, so subscribers saw data that was not committed
  yet, and on a shared file (`Store(db, journal=EventStream(db))`) `incr()`
  waited out the 5 s busy timeout on its own `RESERVED` lock and failed with
  `database is locked` while `set()` worked. Inside `transaction()` the event
  is still buffered until the block commits. **Superseded:** the event is now
  written inside the data's transaction and no buffer exists; see Breaking.
- `Store.transaction()` flushes the journal after the commit and outside the
  rollback path (pass-4 audit): a failing flush no longer drops the caller into
  a rollback branch that cannot undo anything. Every buffered event is
  attempted — one rejected event no longer drops the rest — and partial loss
  raises `JournalFlushError`. **Superseded:** there is no flush step and no
  partial loss any more — a failed event insert rolls the block back; see
  Breaking.
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
  **Superseded:** events are written inside the data's transaction; see
  Breaking.
- `Store`'s internal journal buffer is per-thread (P2-5), matching the
  per-thread connections and transaction flag: concurrent `transaction()`
  blocks in different threads no longer mix or drop each other's buffered
  journal events. **Superseded:** the buffer is gone; see Breaking.
- `EventStream` stores event timestamps in UTC and rejects an event dated more
  than a day in the future (pass-7 audit). Retention compared timestamps as
  text: an event carrying a `-05:00` offset was deleted as "old" the moment it
  was written, and an event stamped `9999-12-31` was immortal, so
  `max_age_seconds` could not bound growth.
- `Store.set()` is one statement on create and two on overwrite (pass-8): the
  `SELECT key ...` probe and the correlated `COALESCE((SELECT created_at ...))`
  are gone. A single UPSERT with `RETURNING created_at` was rejected on purpose
  — on Windows `datetime.now()` has a ~16 ms tick, so a create and an immediate
  overwrite share a timestamp and the "did I create it?" flag would lie.
- `Store.mget()` fetches in two batched queries instead of N×2 per-key calls
  (pass-8): 1000 keys 9.65 ms → 2.84 ms, same semantics and ordering as
  `[get(k) for k in keys]`.
- Connection pragmas tuned (pass-8): `cache_size=-16000`, `mmap_size=256 MB`,
  `temp_store=MEMORY`, `journal_size_limit=64 MB`; randomness: 10k random gets
  on a 50k-key database went 130 ms → 92 ms.
- `keys()` is case-sensitive, like Redis `KEYS` (pass-8): the connection sets
  `PRAGMA case_sensitive_like=ON`, so `keys("USER:*")` no longer matches
  `user:1`.
- `PRAGMA foreign_keys` is now ON (pass-8): the schema declared foreign keys
  that SQLite never enforced. Orphan rows are cleaned once at open (read-only
  probe first, so a clean database still opens without a write lock), and
  deletes are ordered child-first in `delete()`, `incr()` (expired branch),
  `sweep()` and `flush()`, which the new constraint makes mandatory.
- Dev tooling: `ruff` is pinned to `==0.17.2` in the `dev` extra instead of a
  `>=0.1.0` range, and the sources are formatted with that version, so the
  `ruff format --check` step of CI passes again — it had been red since
  2026-10-26, because a range let CI install whichever ruff was released last.
  Formatting only: no runtime behavior changed.
- Dev tooling: the crash-durability stand lives in the repository as
  `tools/crash_harness.py` — it used to sit in a dated workspace folder and
  could vanish with it. Its `run`, `run-txn` and `run-journal-txn` modes now
  exit `1` when the scenario diverges and `0` when it does not, so the stand
  can fail a script instead of only printing; apart from one added
  `конфигурация:` line in the `run-journal-txn` report, the text is unchanged.
  `run-journal-txn-nonatomic` models the pre-fix order — data committed, event
  written in a second transaction — and has to stay red: measured on this
  machine, the atomic run reports `разрыв 0` and exits `0`, the control reports
  `разрыв 496` and exits `1`. A stand that always passes cannot hide behind it.
  `run-journal` prints its gap and now exits `1` on one as well — see Fixed.

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
