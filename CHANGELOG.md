# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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

### Docs
- README tours rewritten to match the real API (verified by execution);
  test count updated.
- English docstrings for all public API.

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

## [0.1.0] - 2026-08-14

- Initial release: `Store`, `StateMachine`, `Saga`, `EventBus`,
  `EventStream`, middleware pipeline, health, retry, event versioning.
