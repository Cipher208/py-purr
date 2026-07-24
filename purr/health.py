"""PURR Health — component health monitoring.

Extracted from an internal agent core.
Generic health checking for any system components.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health state of a component."""

    name: str
    status: HealthStatus = HealthStatus.HEALTHY
    last_check: float = field(default_factory=time.monotonic)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class HealthChecker:
    """Health monitoring for system components."""

    def __init__(self) -> None:
        self._components: dict[str, ComponentHealth] = {}
        self._checks: dict[str, Any] = {}

    def register(self, name: str, check_fn: Any | None = None) -> None:
        """Register a component for health checking."""
        self._components[name] = ComponentHealth(name=name)
        if check_fn:
            self._checks[name] = check_fn

    def update(
        self,
        name: str,
        status: HealthStatus,
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update component health status."""
        if name not in self._components:
            self.register(name)

        self._components[name].status = status
        self._components[name].last_check = time.monotonic()
        self._components[name].error = error
        if metadata:
            self._components[name].metadata.update(metadata)

    def check(self, name: str) -> HealthStatus:
        """Check health of a specific component."""
        if name not in self._components:
            return HealthStatus.UNHEALTHY

        check_fn = self._checks.get(name)
        if check_fn:
            try:
                result = check_fn()
                if isinstance(result, HealthStatus):
                    self.update(name, result)
                elif isinstance(result, bool):
                    status = HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY
                    self.update(name, status)
            except Exception as e:
                self.update(name, HealthStatus.UNHEALTHY, error=str(e))

        return self._components[name].status

    def check_all(self) -> dict[str, HealthStatus]:
        """Check health of all components."""
        results = {}
        for name in self._components:
            results[name] = self.check(name)
        return results

    def get_status(self) -> dict[str, Any]:
        """Get overall health status."""
        overall = HealthStatus.HEALTHY
        components = {}

        for name, health in self._components.items():
            components[name] = {
                "status": health.status.value,
                "last_check": health.last_check,
                "error": health.error,
                "metadata": health.metadata,
            }
            if health.status == HealthStatus.UNHEALTHY:
                overall = HealthStatus.UNHEALTHY
            elif health.status == HealthStatus.DEGRADED and overall != HealthStatus.UNHEALTHY:
                overall = HealthStatus.DEGRADED

        return {
            "overall": overall.value,
            "components": components,
        }
