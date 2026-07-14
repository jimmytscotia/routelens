from routelens.aggregator import ActivityAccumulator
from routelens.store import RouteLensStore


def msg(ts, host="rrc01.ripe.net", ann_prefixes=None, wdr_prefixes=None):
    return {
        "timestamp": ts,
        "host": host,
        "type": "UPDATE",
        "announcements": [{"next_hop": "192.0.2.1", "prefixes": ann_prefixes or []}] if ann_prefixes else [],
        "withdrawals": wdr_prefixes or [],
    }


# 2026-07-14T13:00:00Z and 13:01:00Z as unix timestamps
T0 = 1784034000.0
T1 = T0 + 60


def test_accumulator_folds_messages_into_minute_buckets():
    acc = ActivityAccumulator()

    acc.ingest(msg(T0 + 1, ann_prefixes=["192.0.2.0/24", "198.51.100.0/24"]))
    acc.ingest(msg(T0 + 30, wdr_prefixes=["203.0.113.0/24"]))
    acc.ingest(msg(T0 + 59, host="rrc06.ripe.net", ann_prefixes=["2001:db8::/32"]))
    acc.ingest(msg(T1 + 5, ann_prefixes=["192.0.2.0/24"]))

    buckets = acc.snapshot()

    b0 = buckets[("2026-07-14T13:00:00", "rrc01")]
    assert b0 == {"updates": 2, "announcements": 2, "withdrawals": 1}
    b6 = buckets[("2026-07-14T13:00:00", "rrc06")]
    assert b6 == {"updates": 1, "announcements": 1, "withdrawals": 0}
    b1 = buckets[("2026-07-14T13:01:00", "rrc01")]
    assert b1 == {"updates": 1, "announcements": 1, "withdrawals": 0}


def test_accumulator_ignores_junk_messages():
    acc = ActivityAccumulator()

    acc.ingest({"host": None, "timestamp": T0})          # no collector
    acc.ingest({"host": "rrc01.ripe.net"})               # no timestamp
    acc.ingest(msg(T0))                                   # no prefixes at all still counts as an update

    buckets = acc.snapshot()
    assert buckets == {("2026-07-14T13:00:00", "rrc01"): {"updates": 1, "announcements": 0, "withdrawals": 0}}


def test_flush_writes_buckets_and_drops_only_completed_minutes(tmp_path):
    store = RouteLensStore(tmp_path / "agg.db")
    store.init_schema()
    acc = ActivityAccumulator()
    acc.ingest(msg(T0 + 1, ann_prefixes=["192.0.2.0/24"]))
    acc.ingest(msg(T1 + 1, ann_prefixes=["192.0.2.0/24"]))

    # Flush while the second minute is still "current".
    acc.flush(store, now_ts=T1 + 30)

    league = store.activity_league(since="2026-07-14T00:00:00")
    assert sum(row["updates"] for row in league) == 2
    # Completed minute dropped from memory; current minute retained.
    assert ("2026-07-14T13:00:00", "rrc01") not in acc.snapshot()
    assert ("2026-07-14T13:01:00", "rrc01") in acc.snapshot()

    # More traffic in the current minute, re-flush: idempotent upsert wins.
    acc.ingest(msg(T1 + 40, ann_prefixes=["198.51.100.0/24"]))
    acc.flush(store, now_ts=T1 + 50)

    rrc01 = next(r for r in store.activity_league(since="2026-07-14T00:00:00") if r["rrc"] == "rrc01")
    assert rrc01["updates"] == 3
    assert rrc01["minutes"] == 2
