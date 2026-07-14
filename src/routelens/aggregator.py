"""RIS Live stream aggregator.

Consumes the RIPE RIS Live firehose (UPDATE messages from all collectors),
folds them into per-minute activity buckets per collector, and flushes them
to SQLite. Run as a daemon:

    ROUTELENS_DATABASE=/var/lib/routelens/routelens.db python -m routelens.aggregator

The folding logic (ActivityAccumulator) is pure and unit-tested; only the
WebSocket loop touches the network.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

from .sources import refresh_asn_names, refresh_rpki_scores
from .store import RouteLensStore
from .uk import UK_OPERATORS

log = logging.getLogger("routelens.aggregator")

RIS_LIVE_URL = "wss://ris-live.ripe.net/v1/ws/?client=routelens-aggregator"
FLUSH_INTERVAL_S = 15
PRUNE_INTERVAL_S = 3600
NAMES_REFRESH_S = 86400  # bgp.tools asks for at most daily fetches
RPKI_REFRESH_S = 3600    # ~20 paced RouteViews calls per hour
RETENTION_DAYS = int(os.environ.get("ROUTELENS_RETENTION_DAYS", "7"))


def _minute_bucket(unix_ts: float) -> str:
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).replace(second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _hour_bucket(unix_ts: float) -> str:
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


class OriginTracker:
    """Tracks last-known origin AS per prefix and emits change events.

    Tuned against the two big noise sources: interleaved multi-origin
    announcements (multihoming/anycast seen across ~300 RIS peers) and
    prefixes with no established baseline. An origin change is only reported
    when the old origin was stable (seen >= stable_min times) AND the new
    origin is confirmed by consecutive sightings (confirm_min) with no
    counter-sighting in between.
    """

    def __init__(self, *, stable_min: int = 3, confirm_min: int = 2, max_prefixes: int = 400_000):
        self.stable_min = stable_min
        self.confirm_min = confirm_min
        self.max_prefixes = max_prefixes
        # prefix -> [origin, seen_count, candidate_origin, candidate_count]
        self._state: dict[str, list] = {}

    def __len__(self) -> int:
        return len(self._state)

    def current_origin(self, prefix: str) -> int | None:
        entry = self._state.get(prefix)
        return entry[0] if entry else None

    def observe(self, prefix: str, origin: int, ts: float) -> dict | None:
        entry = self._state.get(prefix)
        if entry is None:
            if len(self._state) >= self.max_prefixes:
                # Evict the oldest ~10% (dicts preserve insertion order).
                for key in list(self._state)[: max(1, self.max_prefixes // 10)]:
                    del self._state[key]
            self._state[prefix] = [origin, 1, None, 0]
            return None

        if origin == entry[0]:
            entry[1] = min(entry[1] + 1, 1000)
            entry[2], entry[3] = None, 0  # counter-sighting resets any candidate
            return None

        # Different origin. Without a stable baseline, just adopt it silently.
        if entry[1] < self.stable_min:
            self._state[prefix] = [origin, 1, None, 0]
            return None

        if entry[2] == origin:
            entry[3] += 1
        else:
            entry[2], entry[3] = origin, 1
        if entry[3] >= self.confirm_min:
            old = entry[0]
            self._state[prefix] = [origin, self.confirm_min, None, 0]
            return {"prefix": prefix, "old_asn": old, "new_asn": origin, "observed_ts": ts}
        return None


class ActivityAccumulator:
    def __init__(self, *, flap_min_events: int = 8, flap_max_rows: int = 5000) -> None:
        self._buckets: dict[tuple[str, str], dict[str, int]] = {}
        # Origin-ASN buckets are hourly: per-minute buckets across ~10k+
        # active origins would explode row counts for no analytical gain.
        self._asn_buckets: dict[tuple[str, int], dict[str, int]] = {}
        # Per-prefix hourly counts. Hundreds of thousands of prefixes update
        # each hour, almost all once or twice — only rows with at least
        # flap_min_events are ever flushed, capped at flap_max_rows per flush.
        self._prefix_buckets: dict[tuple[str, str], dict] = {}
        self.flap_min_events = flap_min_events
        self.flap_max_rows = flap_max_rows
        self.origin_tracker = OriginTracker()
        self._origin_events: list[dict] = []
        # Transit centrality: (hour, asn) -> paths carried; (hour) -> totals.
        self._transit_buckets: dict[tuple[str, int], int] = {}
        self._path_stats: dict[str, dict[str, int]] = {}

    def ingest(self, data: dict) -> None:
        host = data.get("host") or ""
        rrc = host.split(".")[0] if host else ""
        ts = data.get("timestamp")
        if not rrc or ts is None:
            return
        key = (_minute_bucket(float(ts)), rrc)
        bucket = self._buckets.setdefault(key, {"updates": 0, "announcements": 0, "withdrawals": 0})
        bucket["updates"] += 1
        ann_prefixes = 0
        for ann in data.get("announcements") or []:
            ann_prefixes += len(ann.get("prefixes") or [])
        bucket["announcements"] += ann_prefixes
        bucket["withdrawals"] += len(data.get("withdrawals") or [])

        # Attribute announced prefixes to the origin AS (last hop). AS_SETs
        # (a list in the last position) are rare and ambiguous: skip them.
        path = data.get("path") or []
        origin = path[-1] if path else None
        if ann_prefixes and isinstance(origin, int):
            akey = (_hour_bucket(float(ts)), origin)
            abucket = self._asn_buckets.setdefault(
                akey, {"updates": 0, "announcements": 0, "prefixes": set()}
            )
            abucket["updates"] += 1
            abucket["announcements"] += ann_prefixes
            for ann in data.get("announcements") or []:
                abucket["prefixes"].update(ann.get("prefixes") or [])

        # Transit centrality: count each AS once per announcement path,
        # so prepending (64500 3356 3356 3356 …) doesn't inflate anyone.
        hour = _hour_bucket(float(ts))
        if ann_prefixes and len(path) >= 2 and all(isinstance(a, int) for a in path):
            dedup = list(dict.fromkeys(path))
            for asn in dedup[1:-1]:  # middle hops: not the peer, not the origin
                key = (hour, asn)
                self._transit_buckets[key] = self._transit_buckets.get(key, 0) + 1
            stats = self._path_stats.setdefault(hour, {"paths": 0, "hops": 0})
            stats["paths"] += 1
            stats["hops"] += len(dedup)

        # Per-prefix flap counting (hourly) + origin-change tracking.
        for ann in data.get("announcements") or []:
            for prefix in ann.get("prefixes") or []:
                pb = self._prefix_buckets.setdefault(
                    (hour, prefix), {"announcements": 0, "withdrawals": 0, "origin_asn": None}
                )
                pb["announcements"] += 1
                if isinstance(origin, int):
                    pb["origin_asn"] = origin
                    event = self.origin_tracker.observe(prefix, origin, float(ts))
                    if event:
                        self._origin_events.append(event)
        for prefix in data.get("withdrawals") or []:
            pb = self._prefix_buckets.setdefault(
                (hour, prefix), {"announcements": 0, "withdrawals": 0, "origin_asn": None}
            )
            pb["withdrawals"] += 1

    def snapshot(self) -> dict[tuple[str, str], dict[str, int]]:
        return dict(self._buckets)

    def asn_snapshot(self) -> dict[tuple[str, int], dict]:
        return {
            key: {**{k: v for k, v in b.items() if k != "prefixes"}, "distinct": len(b["prefixes"])}
            for key, b in self._asn_buckets.items()
        }

    def prefix_snapshot(self) -> dict[tuple[str, str], dict]:
        return dict(self._prefix_buckets)

    def transit_snapshot(self) -> dict[tuple[str, int], int]:
        return dict(self._transit_buckets)

    def path_stats_snapshot(self) -> dict[str, dict[str, int]]:
        return dict(self._path_stats)

    def flush(self, store: RouteLensStore, *, now_ts: float | None = None) -> int:
        """Write all buckets (idempotent upsert); drop completed periods from
        memory, keep the current minute/hour so they keep accumulating."""
        now = now_ts if now_ts is not None else time.time()
        current_minute = _minute_bucket(now)
        written = 0
        for (bucket_ts, rrc), counts in list(self._buckets.items()):
            store.record_activity_bucket(
                bucket_ts=bucket_ts,
                rrc=rrc,
                updates=counts["updates"],
                announcements=counts["announcements"],
                withdrawals=counts["withdrawals"],
            )
            written += 1
            if bucket_ts < current_minute:
                del self._buckets[(bucket_ts, rrc)]

        current_hour = _hour_bucket(now)
        for (bucket_ts, asn), counts in list(self._asn_buckets.items()):
            store.record_asn_bucket(
                bucket_ts=bucket_ts,
                asn=asn,
                updates=counts["updates"],
                announcements=counts["announcements"],
                distinct=len(counts["prefixes"]),
            )
            written += 1
            if bucket_ts < current_hour:
                del self._asn_buckets[(bucket_ts, asn)]

        # Prefixes: flush only the noisy ones, loudest first, capped per flush.
        noisy = [
            (key, pb) for key, pb in self._prefix_buckets.items()
            if pb["announcements"] + pb["withdrawals"] >= self.flap_min_events
        ]
        noisy.sort(key=lambda item: item[1]["announcements"] + item[1]["withdrawals"], reverse=True)
        for (bucket_ts, prefix), pb in noisy[: self.flap_max_rows]:
            store.record_prefix_bucket(
                bucket_ts=bucket_ts,
                prefix=prefix,
                announcements=pb["announcements"],
                withdrawals=pb["withdrawals"],
                origin_asn=pb["origin_asn"],
            )
            written += 1
        # Completed hours are dropped entirely (flushed or below threshold).
        for (bucket_ts, prefix) in list(self._prefix_buckets):
            if bucket_ts < current_hour:
                del self._prefix_buckets[(bucket_ts, prefix)]

        for (bucket_ts, asn), paths in list(self._transit_buckets.items()):
            store.record_transit_bucket(bucket_ts=bucket_ts, asn=asn, paths=paths)
            written += 1
            if bucket_ts < current_hour:
                del self._transit_buckets[(bucket_ts, asn)]
        for bucket_ts, stats in list(self._path_stats.items()):
            store.record_path_stats(bucket_ts=bucket_ts, paths=stats["paths"], hops=stats["hops"])
            written += 1
            if bucket_ts < current_hour:
                del self._path_stats[bucket_ts]

        # Confirmed origin-change events (rare: dozens per hour, not thousands).
        for event in self._origin_events:
            store.record_origin_event(
                observed_at=datetime.fromtimestamp(
                    event["observed_ts"], tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%S"),
                prefix=event["prefix"],
                old_asn=event["old_asn"],
                new_asn=event["new_asn"],
            )
            written += 1
        self._origin_events.clear()
        return written


async def run(store: RouteLensStore) -> None:
    import websockets

    acc = ActivityAccumulator()
    last_flush = time.time()
    last_prune = 0.0
    last_names = 0.0
    last_rpki = 0.0
    retry_s = 1

    while True:
        try:
            async with websockets.connect(RIS_LIVE_URL, ping_interval=30) as ws:
                await ws.send(json.dumps({"type": "ris_subscribe", "data": {"type": "UPDATE"}}))
                log.info("subscribed to RIS Live firehose")
                retry_s = 1
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "ris_message":
                        acc.ingest(msg["data"])
                    now = time.time()
                    if now - last_flush >= FLUSH_INTERVAL_S:
                        written = acc.flush(store)
                        last_flush = now
                        log.debug("flushed %d buckets", written)
                    if now - last_prune >= PRUNE_INTERVAL_S:
                        cutoff = datetime.fromtimestamp(
                            now - RETENTION_DAYS * 86400, tz=timezone.utc
                        ).strftime("%Y-%m-%dT%H:%M:%S")
                        removed = store.prune_activity(before=cutoff)
                        removed += store.prune_asn_activity(before=cutoff)
                        removed += store.prune_prefix_activity(before=cutoff)
                        removed += store.prune_origin_events(before=cutoff)
                        removed += store.prune_transit_activity(before=cutoff)
                        removed += store.prune_path_stats(before=cutoff)
                        last_prune = now
                        log.info("pruned %d buckets older than %s", removed, cutoff)
                    if now - last_rpki >= RPKI_REFRESH_S:
                        last_rpki = now
                        day_ago = datetime.fromtimestamp(now - 86400, tz=timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%S"
                        )
                        churners = [row["asn"] for row in store.asn_league(since=day_ago, limit=10)]
                        targets = list(dict.fromkeys(UK_OPERATORS + churners))

                        def _score(asns=targets) -> None:
                            try:
                                count = refresh_rpki_scores(store, asns)
                                log.info("scored RPKI coverage for %d ASNs", count)
                            except Exception as exc:
                                log.warning("RPKI scoring failed: %s", exc)

                        asyncio.get_running_loop().run_in_executor(None, _score)
                    if now - last_names >= NAMES_REFRESH_S:
                        # Off the event loop: a blocking multi-second fetch here
                        # would stall the stream and get us cut off as a slow consumer.
                        last_names = now

                        def _refresh() -> None:
                            try:
                                count = refresh_asn_names(store)
                                log.info("refreshed %d ASN names from bgp.tools", count)
                            except Exception as exc:
                                log.warning("ASN name refresh failed: %s", exc)

                        asyncio.get_running_loop().run_in_executor(None, _refresh)
        except asyncio.CancelledError:
            acc.flush(store)
            raise
        except Exception as exc:
            log.warning("stream error (%s); reconnecting in %ds", exc, retry_s)
            acc.flush(store)
            await asyncio.sleep(retry_s)
            retry_s = min(retry_s * 2, 60)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = os.environ.get("ROUTELENS_DATABASE", "/var/lib/routelens/routelens.db")
    store = RouteLensStore(db)
    store.init_schema()
    log.info("aggregating RIS Live into %s (retention %dd)", db, RETENTION_DAYS)
    asyncio.run(run(store))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
