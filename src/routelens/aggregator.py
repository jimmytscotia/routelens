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

from .sources import refresh_asn_names
from .store import RouteLensStore

log = logging.getLogger("routelens.aggregator")

RIS_LIVE_URL = "wss://ris-live.ripe.net/v1/ws/?client=routelens-aggregator"
FLUSH_INTERVAL_S = 15
PRUNE_INTERVAL_S = 3600
NAMES_REFRESH_S = 86400  # bgp.tools asks for at most daily fetches
RETENTION_DAYS = int(os.environ.get("ROUTELENS_RETENTION_DAYS", "7"))


def _minute_bucket(unix_ts: float) -> str:
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).replace(second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _hour_bucket(unix_ts: float) -> str:
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


class ActivityAccumulator:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], dict[str, int]] = {}
        # Origin-ASN buckets are hourly: per-minute buckets across ~10k+
        # active origins would explode row counts for no analytical gain.
        self._asn_buckets: dict[tuple[str, int], dict[str, int]] = {}

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
            abucket = self._asn_buckets.setdefault(akey, {"updates": 0, "announcements": 0})
            abucket["updates"] += 1
            abucket["announcements"] += ann_prefixes

    def snapshot(self) -> dict[tuple[str, str], dict[str, int]]:
        return dict(self._buckets)

    def asn_snapshot(self) -> dict[tuple[str, int], dict[str, int]]:
        return dict(self._asn_buckets)

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
            )
            written += 1
            if bucket_ts < current_hour:
                del self._asn_buckets[(bucket_ts, asn)]
        return written


async def run(store: RouteLensStore) -> None:
    import websockets

    acc = ActivityAccumulator()
    last_flush = time.time()
    last_prune = 0.0
    last_names = 0.0
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
                        last_prune = now
                        log.info("pruned %d buckets older than %s", removed, cutoff)
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
