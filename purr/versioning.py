"""PURR EventVersioner — event schema migration.

Extracted from an internal agent core.
Migrates events between schema versions.
"""

from __future__ import annotations

from collections.abc import Callable

from .event import Event


class MigrationGapError(ValueError):
    """A migration step needed to reach the latest version is not registered."""


class EventVersioner:
    """Event schema versioning and migration."""

    def __init__(self) -> None:
        self._migrations: dict[str, dict[int, Callable[[dict], dict]]] = {}
        self._latest_version: dict[str, int] = {}

    def register_migration(
        self,
        topic: str,
        from_version: int,
        to_version: int,
        migrate_fn: Callable[[dict], dict],
    ) -> None:
        """Register a migration function for a topic."""
        if topic not in self._migrations:
            self._migrations[topic] = {}
        self._migrations[topic][from_version] = migrate_fn

        if topic not in self._latest_version or to_version > self._latest_version[topic]:
            self._latest_version[topic] = to_version

    def migrate(self, event: Event) -> Event:
        """Migrate an event to the latest version.

        Never mutates the input: migrations run on a deep copy, so the event
        already held by an EventBus history or an EventStream keeps the
        schema version it was stored with. Events that need no migration
        (unknown topic, or version already at/past the latest) are returned
        unchanged and identical.
        """
        if event.topic not in self._migrations:
            return event

        current_version = event.version
        latest = self._latest_version.get(event.topic, current_version)
        if current_version >= latest:
            return event

        migrated = event.model_copy(deep=True)
        while current_version < latest:
            migration = self._migrations[event.topic].get(current_version)
            if not migration:
                registered = sorted(self._migrations[event.topic])
                raise MigrationGapError(
                    f"no migration registered for {event.topic} "
                    f"v{current_version} -> v{current_version + 1} "
                    f"(registered: {registered})"
                )
            migrated.payload = migration(migrated.payload)
            migrated.version = current_version + 1
            current_version = migrated.version

        return migrated

    def get_latest_version(self, topic: str) -> int:
        """Get latest version for a topic."""
        return self._latest_version.get(topic, 1)

    def get_migrations(self, topic: str) -> list[int]:
        """Get available migration versions for a topic."""
        return sorted(self._migrations.get(topic, {}).keys())
