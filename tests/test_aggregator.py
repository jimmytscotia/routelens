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


def test_accumulator_folds_origin_asn_hourly_buckets():
    acc = ActivityAccumulator()

    acc.ingest({**msg(T0 + 1, ann_prefixes=["192.0.2.0/24", "198.51.100.0/24"]), "path": [64500, 3356, 15169]})
    acc.ingest({**msg(T0 + 30, ann_prefixes=["203.0.113.0/24"]), "path": [64501, 15169]})
    acc.ingest({**msg(T0 + 40, ann_prefixes=["2001:db8::/32"]), "path": [64501, 2856]})
    # Withdrawal-only update has no path: no origin attribution.
    acc.ingest(msg(T0 + 50, wdr_prefixes=["203.0.113.0/24"]))
    # AS_SET as the last element is skipped rather than misattributed.
    acc.ingest({**msg(T0 + 55, ann_prefixes=["192.0.2.0/24"]), "path": [64500, [64512, 64513]]})

    asn_buckets = acc.asn_snapshot()

    b15169 = asn_buckets[("2026-07-14T13:00:00", 15169)]
    assert b15169["updates"] == 2
    assert b15169["announcements"] == 3
    # 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24 — three distinct prefixes.
    assert b15169["distinct"] == 3
    b2856 = asn_buckets[("2026-07-14T13:00:00", 2856)]
    assert b2856["updates"] == 1
    assert b2856["distinct"] == 1
    assert len(asn_buckets) == 2


def test_flush_writes_asn_buckets_hourly(tmp_path):
    store = RouteLensStore(tmp_path / "agg2.db")
    store.init_schema()
    acc = ActivityAccumulator()
    acc.ingest({**msg(T0 + 1, ann_prefixes=["192.0.2.0/24"]), "path": [64500, 15169]})

    acc.flush(store, now_ts=T0 + 30)

    league = store.asn_league(since="2026-07-14T00:00:00", limit=5)
    assert league[0]["asn"] == 15169
    assert league[0]["updates"] == 1
    assert league[0]["peak_distinct"] == 1

    # Same prefix announced again in the same hour: distinct stays 1.
    acc.ingest({**msg(T0 + 90, ann_prefixes=["192.0.2.0/24"]), "path": [64500, 15169]})
    acc.flush(store, now_ts=T0 + 95)
    league = store.asn_league(since="2026-07-14T00:00:00", limit=5)
    assert league[0]["announcements"] == 2
    assert league[0]["peak_distinct"] == 1


def test_accumulator_folds_prefix_hourly_buckets_with_origin():
    acc = ActivityAccumulator()

    acc.ingest({**msg(T0 + 1, ann_prefixes=["203.0.113.0/24"]), "path": [64500, 15169]})
    acc.ingest({**msg(T0 + 10, wdr_prefixes=["203.0.113.0/24"])})
    acc.ingest({**msg(T0 + 20, ann_prefixes=["203.0.113.0/24"]), "path": [64501, 15169]})
    acc.ingest({**msg(T0 + 30, ann_prefixes=["198.51.100.0/24"]), "path": [64500, 2856]})

    buckets = acc.prefix_snapshot()

    flappy = buckets[("2026-07-14T13:00:00", "203.0.113.0/24")]
    assert flappy["announcements"] == 2
    assert flappy["withdrawals"] == 1
    assert flappy["origin_asn"] == 15169
    quiet = buckets[("2026-07-14T13:00:00", "198.51.100.0/24")]
    assert quiet["announcements"] == 1
    assert quiet["withdrawals"] == 0


def test_flush_writes_only_prefixes_above_event_threshold(tmp_path):
    store = RouteLensStore(tmp_path / "agg3.db")
    store.init_schema()
    acc = ActivityAccumulator(flap_min_events=3)
    # Noisy prefix: 4 events. Quiet prefix: 1 event.
    acc.ingest({**msg(T0 + 1, ann_prefixes=["203.0.113.0/24"]), "path": [64500, 15169]})
    acc.ingest({**msg(T0 + 2, wdr_prefixes=["203.0.113.0/24"])})
    acc.ingest({**msg(T0 + 3, ann_prefixes=["203.0.113.0/24"]), "path": [64500, 15169]})
    acc.ingest({**msg(T0 + 4, wdr_prefixes=["203.0.113.0/24"])})
    acc.ingest({**msg(T0 + 5, ann_prefixes=["198.51.100.0/24"]), "path": [64500, 2856]})

    acc.flush(store, now_ts=T0 + 30)

    league = store.prefix_flap_league(since="2026-07-14T00:00:00", limit=10)
    assert [row["prefix"] for row in league] == ["203.0.113.0/24"]
    assert league[0]["announcements"] == 2
    assert league[0]["withdrawals"] == 2
    assert league[0]["origin_asn"] == 15169


def test_origin_tracker_requires_stability_and_confirmation():
    from routelens.aggregator import OriginTracker

    tracker = OriginTracker(stable_min=3, confirm_min=2)

    # Establish a stable baseline: AS64500 seen three times.
    for _ in range(3):
        assert tracker.observe("203.0.113.0/24", 64500, T0) is None
    # First sighting of a different origin: candidate only, no event yet.
    assert tracker.observe("203.0.113.0/24", 64666, T0 + 10) is None
    # Second consecutive sighting confirms the change.
    event = tracker.observe("203.0.113.0/24", 64666, T0 + 20)
    assert event == {"prefix": "203.0.113.0/24", "old_asn": 64500, "new_asn": 64666, "observed_ts": T0 + 20}
    # After the swap the new origin is current: no further events.
    assert tracker.observe("203.0.113.0/24", 64666, T0 + 30) is None


def test_origin_tracker_interleaved_moas_does_not_confirm():
    from routelens.aggregator import OriginTracker

    tracker = OriginTracker(stable_min=3, confirm_min=2)
    for _ in range(3):
        tracker.observe("203.0.113.0/24", 64500, T0)

    # Interleaved origins (classic multihoming as seen across peers):
    # the candidate never gets two consecutive sightings.
    assert tracker.observe("203.0.113.0/24", 64666, T0 + 1) is None
    assert tracker.observe("203.0.113.0/24", 64500, T0 + 2) is None
    assert tracker.observe("203.0.113.0/24", 64666, T0 + 3) is None
    assert tracker.observe("203.0.113.0/24", 64500, T0 + 4) is None


def test_origin_tracker_no_event_without_stable_baseline():
    from routelens.aggregator import OriginTracker

    tracker = OriginTracker(stable_min=3, confirm_min=2)

    # Only seen once: swapping origin is a silent update, not an event.
    tracker.observe("198.51.100.0/24", 64500, T0)
    assert tracker.observe("198.51.100.0/24", 64777, T0 + 1) is None
    assert tracker.observe("198.51.100.0/24", 64777, T0 + 2) is None


def test_origin_tracker_evicts_oldest_when_capped():
    from routelens.aggregator import OriginTracker

    tracker = OriginTracker(max_prefixes=100)
    for i in range(150):
        tracker.observe(f"10.{i}.0.0/16", 64500, T0 + i)

    assert len(tracker) <= 100
    # The most recent prefixes survive.
    assert tracker.current_origin("10.149.0.0/16") == 64500
    assert tracker.current_origin("10.0.0.0/16") is None


def test_accumulator_records_confirmed_origin_changes_on_flush(tmp_path):
    store = RouteLensStore(tmp_path / "agg4.db")
    store.init_schema()
    acc = ActivityAccumulator()

    for i in range(3):
        acc.ingest({**msg(T0 + i, ann_prefixes=["203.0.113.0/24"]), "path": [64444, 64500]})
    acc.ingest({**msg(T0 + 10, ann_prefixes=["203.0.113.0/24"]), "path": [64444, 64666]})
    acc.ingest({**msg(T0 + 20, ann_prefixes=["203.0.113.0/24"]), "path": [64445, 64666]})

    acc.flush(store, now_ts=T0 + 30)

    events = store.recent_origin_events(since="2026-07-14T00:00:00")
    assert len(events) == 1
    assert events[0]["prefix"] == "203.0.113.0/24"
    assert events[0]["old_asn"] == 64500
    assert events[0]["new_asn"] == 64666


def test_accumulator_folds_transit_hops_dedup_prepending():
    acc = ActivityAccumulator()

    # peer 64500 -> transit 3356, 1299 -> origin 15169
    acc.ingest({**msg(T0 + 1, ann_prefixes=["192.0.2.0/24"]), "path": [64500, 3356, 1299, 15169]})
    # Prepending: 3356 appears three times but counts once for this path.
    acc.ingest({**msg(T0 + 2, ann_prefixes=["198.51.100.0/24"]), "path": [64501, 3356, 3356, 3356, 15169]})
    # Two-hop path has no transit hops at all.
    acc.ingest({**msg(T0 + 3, ann_prefixes=["203.0.113.0/24"]), "path": [64500, 15169]})
    # Withdrawal-only: no path, ignored.
    acc.ingest(msg(T0 + 4, wdr_prefixes=["203.0.113.0/24"]))

    transit = acc.transit_snapshot()
    stats = acc.path_stats_snapshot()

    assert transit[("2026-07-14T13:00:00", 3356)] == 2
    assert transit[("2026-07-14T13:00:00", 1299)] == 1
    assert 15169 not in [asn for _, asn in transit]
    assert 64500 not in [asn for _, asn in transit]
    # Path stats: 3 announcement paths; dedup lengths 4 + 3 + 2 = 9 hops.
    assert stats[("2026-07-14T13:00:00")] == {"paths": 3, "hops": 9}


def test_flush_writes_transit_and_path_stats(tmp_path):
    store = RouteLensStore(tmp_path / "agg9.db")
    store.init_schema()
    acc = ActivityAccumulator()
    acc.ingest({**msg(T0 + 1, ann_prefixes=["192.0.2.0/24"]), "path": [64500, 3356, 15169]})
    acc.ingest({**msg(T0 + 2, ann_prefixes=["198.51.100.0/24"]), "path": [64501, 3356, 15169]})

    acc.flush(store, now_ts=T0 + 30)

    league = store.transit_league(since="2026-07-14T00:00:00", limit=5)
    assert league[0]["asn"] == 3356
    assert league[0]["paths"] == 2
    stats = store.path_stats(since="2026-07-14T00:00:00")
    assert stats["paths"] == 2
    assert stats["avg_len"] == 3.0


def test_initial_last_weather_cold_db_fires_after_warmup(tmp_path):
    from routelens.aggregator import _initial_last_weather, WEATHER_REFRESH_S, WEATHER_WARMUP_S
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "w.db")
    store.init_schema()
    now = 1_000_000.0

    seed = _initial_last_weather(store, now)

    # First briefing fires WARMUP seconds after start, not a full period.
    assert now - seed == WEATHER_REFRESH_S - WEATHER_WARMUP_S
    assert (now - seed) < WEATHER_REFRESH_S


def test_initial_last_weather_tracks_last_report(tmp_path):
    from routelens.aggregator import _initial_last_weather
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "w.db")
    store.init_schema()
    store.save_weather_report(period_hours=6, headline="h", severity="calm",
                              body_md="b", evidence={}, model="m")

    seed = _initial_last_weather(store, 9_999_999_999.0)

    # Seeded from the stored report's timestamp, so the next one fires 6h
    # after THAT report — not immediately, not a fresh 6h from restart.
    latest = store.latest_weather_report()
    from datetime import datetime, timezone
    expected = datetime.strptime(latest["generated_at"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc).timestamp()
    assert seed == expected
