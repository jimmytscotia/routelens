from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  resource_type TEXT NOT NULL CHECK (resource_type IN ('hostname','prefix','url')),
  expected_mode TEXT NOT NULL DEFAULT 'public'
    CHECK (expected_mode IN ('public','private_lab','bgp_public','internal_only')),
  expected_ips TEXT NOT NULL DEFAULT '[]',
  expected_origin_asn INTEGER,
  expected_url TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS check_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  resource_id INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
  check_type TEXT NOT NULL CHECK (check_type IN ('dns','tls','http','bgp','insight')),
  status TEXT NOT NULL CHECK (status IN ('healthy','warning','critical','unknown')),
  summary TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_check_results_resource_type_time
  ON check_results(resource_id, check_type, checked_at DESC, id DESC);
"""


DEFAULT_RESOURCES = [
    {
        "name": "nexthop.engineer",
        "resource_type": "hostname",
        "expected_mode": "public",
        "expected_ips": ["66.241.124.199"],
        "expected_url": "https://nexthop.engineer/",
    },
    {
        "name": "web.nexthop.engineer",
        "resource_type": "hostname",
        "expected_mode": "private_lab",
        "expected_ips": ["100.94.135.62"],
        "expected_url": "https://web.nexthop.engineer/",
    },
    {
        "name": "grafana.nexthop.engineer",
        "resource_type": "hostname",
        "expected_mode": "private_lab",
        "expected_ips": ["100.94.135.62"],
        "expected_url": "https://grafana.nexthop.engineer/",
    },
    {
        "name": "prometheus.nexthop.engineer",
        "resource_type": "hostname",
        "expected_mode": "private_lab",
        "expected_ips": ["100.94.135.62"],
        "expected_url": "https://prometheus.nexthop.engineer/",
    },
    {"name": "8.8.8.0/24", "resource_type": "prefix", "expected_mode": "bgp_public", "expected_origin_asn": 15169},
    {"name": "1.1.1.0/24", "resource_type": "prefix", "expected_mode": "bgp_public", "expected_origin_asn": 13335},
]


class RouteLensStore:
    """Small stdlib-sqlite repository for RouteLens snapshots.

    The schema intentionally keeps JSON payloads in TEXT so the project can run
    on Python's stdlib sqlite3 without requiring SQLAlchemy or SQLite JSON1.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def seed_defaults(self) -> None:
        for resource in DEFAULT_RESOURCES:
            self.upsert_resource(**resource)

    def upsert_resource(
        self,
        *,
        name: str,
        resource_type: str,
        expected_mode: str = "public",
        expected_ips: list[str] | None = None,
        expected_origin_asn: int | None = None,
        expected_url: str | None = None,
        enabled: bool = True,
    ) -> int:
        payload = json.dumps(expected_ips or [])
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM resources WHERE name = ?", (name,)).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE resources
                       SET resource_type=?, expected_mode=?, expected_ips=?, expected_origin_asn=?,
                           expected_url=?, enabled=?, updated_at=datetime('now')
                     WHERE id=?
                    """,
                    (resource_type, expected_mode, payload, expected_origin_asn, expected_url, int(enabled), row["id"]),
                )
                return int(row["id"])
            cur = conn.execute(
                """
                INSERT INTO resources(name, resource_type, expected_mode, expected_ips,
                                      expected_origin_asn, expected_url, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, resource_type, expected_mode, payload, expected_origin_asn, expected_url, int(enabled)),
            )
            return int(cur.lastrowid)

    def list_resources(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM resources"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY resource_type, name"
        with self.connect() as conn:
            return [self._resource_dict(row) for row in conn.execute(sql).fetchall()]

    def get_resource(self, resource_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        if row is None:
            return None
        return self._resource_dict(row)

    def record_check(
        self,
        *,
        resource_id: int,
        check_type: str,
        status: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO check_results(resource_id, check_type, status, summary, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (resource_id, check_type, status, summary, json.dumps(details or {}, sort_keys=True)),
            )
            return int(cur.lastrowid)

    def latest_checks(self, resource_id: int) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT cr.*
                  FROM check_results cr
                  JOIN (
                    SELECT check_type, MAX(id) AS max_id
                      FROM check_results
                     WHERE resource_id = ?
                     GROUP BY check_type
                  ) latest ON latest.max_id = cr.id
                 ORDER BY cr.check_type
                """,
                (resource_id,),
            ).fetchall()
        return {row["check_type"]: self._check_dict(row) for row in rows}

    @staticmethod
    def _resource_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["expected_ips"] = json.loads(item.get("expected_ips") or "[]")
        item["enabled"] = bool(item["enabled"])
        return item

    @staticmethod
    def _check_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json") or "{}")
        return item
