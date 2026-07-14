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

CREATE TABLE IF NOT EXISTS api_cache (
  cache_key TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ris_activity (
  bucket_ts TEXT NOT NULL,           -- minute bucket, ISO8601 UTC
  rrc TEXT NOT NULL,                 -- collector short id, e.g. 'rrc01'
  updates INTEGER NOT NULL DEFAULT 0,
  announcements INTEGER NOT NULL DEFAULT 0,
  withdrawals INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket_ts, rrc)
);
CREATE INDEX IF NOT EXISTS idx_ris_activity_rrc_time ON ris_activity(rrc, bucket_ts);

CREATE TABLE IF NOT EXISTS ris_asn_activity (
  bucket_ts TEXT NOT NULL,           -- hour bucket, ISO8601 UTC
  asn INTEGER NOT NULL,              -- origin ASN (last hop of announced paths)
  updates INTEGER NOT NULL DEFAULT 0,
  announcements INTEGER NOT NULL DEFAULT 0,
  distinct_prefixes INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket_ts, asn)
);

CREATE TABLE IF NOT EXISTS asn_names (
  asn INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  country TEXT NOT NULL DEFAULT ''
);
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
            # Migrations for tables created before a column existed
            # (CREATE IF NOT EXISTS won't touch an existing table).
            try:
                conn.execute("ALTER TABLE ris_asn_activity ADD COLUMN distinct_prefixes INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # column already present

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

    def cache_get(self, cache_key: str, *, max_age_seconds: int) -> Any | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM api_cache
                 WHERE cache_key = ?
                   AND fetched_at >= datetime('now', ?)
                """,
                (cache_key, f"-{int(max_age_seconds)} seconds"),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def cache_set(self, cache_key: str, payload: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO api_cache(cache_key, payload_json, fetched_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(cache_key) DO UPDATE
                   SET payload_json = excluded.payload_json,
                       fetched_at = excluded.fetched_at
                """,
                (cache_key, json.dumps(payload, sort_keys=True)),
            )

    def record_activity_bucket(
        self, *, bucket_ts: str, rrc: str, updates: int, announcements: int, withdrawals: int
    ) -> None:
        """Idempotent flush: re-writing the same (bucket, rrc) replaces counts."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ris_activity(bucket_ts, rrc, updates, announcements, withdrawals)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(bucket_ts, rrc) DO UPDATE
                   SET updates = excluded.updates,
                       announcements = excluded.announcements,
                       withdrawals = excluded.withdrawals
                """,
                (bucket_ts, rrc, updates, announcements, withdrawals),
            )

    def activity_league(self, *, since: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT rrc,
                       SUM(updates) AS updates,
                       SUM(announcements) AS announcements,
                       SUM(withdrawals) AS withdrawals,
                       COUNT(*) AS minutes
                  FROM ris_activity
                 WHERE bucket_ts >= ?
                 GROUP BY rrc
                 ORDER BY updates DESC
                """,
                (since,),
            ).fetchall()
        return [dict(row) for row in rows]

    def activity_series(self, *, rrc: str, since: str) -> list[tuple[str, int]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT bucket_ts, updates FROM ris_activity
                 WHERE rrc = ? AND bucket_ts >= ?
                 ORDER BY bucket_ts
                """,
                (rrc, since),
            ).fetchall()
        return [(row["bucket_ts"], row["updates"]) for row in rows]

    def prune_activity(self, *, before: str) -> int:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM ris_activity WHERE bucket_ts < ?", (before,))
            return cur.rowcount

    def record_asn_bucket(
        self, *, bucket_ts: str, asn: int, updates: int, announcements: int, distinct: int = 0
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ris_asn_activity(bucket_ts, asn, updates, announcements, distinct_prefixes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(bucket_ts, asn) DO UPDATE
                   SET updates = excluded.updates,
                       announcements = excluded.announcements,
                       distinct_prefixes = excluded.distinct_prefixes
                """,
                (bucket_ts, asn, updates, announcements, distinct),
            )

    def upsert_asn_names(self, rows: list[tuple[int, str, str]]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO asn_names(asn, name, country) VALUES (?, ?, ?)
                ON CONFLICT(asn) DO UPDATE SET name = excluded.name, country = excluded.country
                """,
                rows,
            )

    def asn_league(self, *, since: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT a.asn,
                       COALESCE(n.name, '') AS name,
                       COALESCE(n.country, '') AS country,
                       SUM(a.updates) AS updates,
                       SUM(a.announcements) AS announcements,
                       MAX(a.distinct_prefixes) AS peak_distinct
                  FROM ris_asn_activity a
                  LEFT JOIN asn_names n ON n.asn = a.asn
                 WHERE a.bucket_ts >= ?
                 GROUP BY a.asn
                 ORDER BY announcements DESC
                 LIMIT ?
                """,
                (since, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def prune_asn_activity(self, *, before: str) -> int:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM ris_asn_activity WHERE bucket_ts < ?", (before,))
            return cur.rowcount

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
