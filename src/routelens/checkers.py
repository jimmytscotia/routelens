from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass(frozen=True)
class CheckResult:
    resource_name: str
    check_type: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Checker(Protocol):
    check_type: str

    def run(self, resource: dict[str, Any]) -> CheckResult:
        """Run one check against a resource and return a serializable result."""


class IngestionSink(Protocol):
    def record_check(
        self,
        *,
        resource_id: int,
        check_type: str,
        status: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Persist a checker result and return the database row id."""
