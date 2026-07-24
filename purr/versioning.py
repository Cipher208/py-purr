"""PURR EventVersioner — event schema migration.

Extracted from an internal agent core.
Migrates events between schema versions.
"""

from __future__ import annotations

from typing import Any, Callable

from .event import Event


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
        """Migrate an event to the latest version."""
        if event.topic not in self._migrations:
            return event

        current_version = event.version
        latest = self._latest_version.get(event.topic, current_version)

        while current_version < latest:
            migration = self._migrations[event.topic].get(current_version)
            if not migration:
                break
            event.payload = migration(event.payload)
            event.version = current_version + 1
            current_version = event.version

        return event

    def get_latest_version(self, topic: str) -> int:
        """Get latest version for a topic."""
        return self._latest_version.get(topic, 1)

    def get_migrations(self, topic: str) -> list[int]:
        """Get available migration versions for a topic."""
        return sorted(self._migrations.get(topic, {}).keys())
