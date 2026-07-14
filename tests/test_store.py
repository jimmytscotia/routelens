from routelens.store import RouteLensStore


def test_store_initializes_schema_and_seeds_resources(tmp_path):
    db_path = tmp_path / "routelens.db"
    store = RouteLensStore(db_path)
    store.init_schema()
    store.seed_defaults()

    resources = store.list_resources()

    names = {r["name"] for r in resources}
    assert "nexthop.engineer" in names
    assert "web.nexthop.engineer" in names
    assert "8.8.8.0/24" in names


def test_store_records_check_result_and_returns_latest_snapshot(tmp_path):
    db_path = tmp_path / "routelens.db"
    store = RouteLensStore(db_path)
    store.init_schema()
    resource_id = store.upsert_resource(name="web.nexthop.engineer", resource_type="hostname", expected_mode="private_lab")

    store.record_check(
        resource_id=resource_id,
        check_type="dns",
        status="healthy",
        summary="private DNS present and public DNS absent",
        details={"public_ips": [], "private_ips": ["100.94.135.62"]},
    )

    latest = store.latest_checks(resource_id)
    assert latest["dns"]["status"] == "healthy"
    assert latest["dns"]["details"]["private_ips"] == ["100.94.135.62"]


def test_api_cache_roundtrip_and_ttl(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "cache.db")
    store.init_schema()

    assert store.cache_get("rv:8.8.8.0/24", max_age_seconds=60) is None

    store.cache_set("rv:8.8.8.0/24", {"paths": [[3356, 15169]]})
    hit = store.cache_get("rv:8.8.8.0/24", max_age_seconds=60)
    assert hit == {"paths": [[3356, 15169]]}

    # An entry older than max_age is a miss.
    with store.connect() as conn:
        conn.execute(
            "UPDATE api_cache SET fetched_at = datetime('now', '-120 seconds') WHERE cache_key = ?",
            ("rv:8.8.8.0/24",),
        )
    assert store.cache_get("rv:8.8.8.0/24", max_age_seconds=60) is None


def test_api_cache_set_overwrites_existing_key(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "cache.db")
    store.init_schema()

    store.cache_set("k", {"v": 1})
    store.cache_set("k", {"v": 2})

    assert store.cache_get("k", max_age_seconds=60) == {"v": 2}


def test_activity_buckets_upsert_and_league(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "activity.db")
    store.init_schema()

    store.record_activity_bucket(
        bucket_ts="2026-07-14T13:00:00", rrc="rrc01", updates=120, announcements=100, withdrawals=20
    )
    store.record_activity_bucket(
        bucket_ts="2026-07-14T13:01:00", rrc="rrc01", updates=80, announcements=70, withdrawals=10
    )
    store.record_activity_bucket(
        bucket_ts="2026-07-14T13:00:00", rrc="rrc06", updates=300, announcements=280, withdrawals=20
    )
    # Same bucket re-flushed with a higher count wins (idempotent upsert).
    store.record_activity_bucket(
        bucket_ts="2026-07-14T13:00:00", rrc="rrc06", updates=310, announcements=290, withdrawals=20
    )

    league = store.activity_league(since="2026-07-14T12:59:00")

    assert [row["rrc"] for row in league] == ["rrc06", "rrc01"]
    assert league[0]["updates"] == 310
    assert league[1]["updates"] == 200
    assert league[1]["announcements"] == 170
    assert league[1]["withdrawals"] == 30
    assert league[1]["minutes"] == 2


def test_activity_series_returns_per_minute_counts(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "activity.db")
    store.init_schema()
    store.record_activity_bucket(bucket_ts="2026-07-14T13:00:00", rrc="rrc01", updates=5, announcements=5, withdrawals=0)
    store.record_activity_bucket(bucket_ts="2026-07-14T13:02:00", rrc="rrc01", updates=9, announcements=8, withdrawals=1)

    series = store.activity_series(rrc="rrc01", since="2026-07-14T12:59:00")

    assert series == [("2026-07-14T13:00:00", 5), ("2026-07-14T13:02:00", 9)]


def test_activity_prune_removes_old_buckets(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "activity.db")
    store.init_schema()
    store.record_activity_bucket(bucket_ts="2026-07-01T00:00:00", rrc="rrc01", updates=1, announcements=1, withdrawals=0)
    store.record_activity_bucket(bucket_ts="2026-07-14T13:00:00", rrc="rrc01", updates=2, announcements=2, withdrawals=0)

    removed = store.prune_activity(before="2026-07-07T00:00:00")

    assert removed == 1
    assert store.activity_league(since="2026-01-01T00:00:00")[0]["updates"] == 2


def test_asn_activity_league_with_names(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "asn.db")
    store.init_schema()
    store.upsert_asn_names([(2856, "British Telecommunications PLC", "GB"), (15169, "Google LLC", "US")])
    store.record_asn_bucket(bucket_ts="2026-07-14T13:00:00", asn=2856, updates=50, announcements=60, distinct=12)
    store.record_asn_bucket(bucket_ts="2026-07-14T13:00:00", asn=15169, updates=200, announcements=220, distinct=80)
    store.record_asn_bucket(bucket_ts="2026-07-14T14:00:00", asn=2856, updates=30, announcements=35, distinct=40)
    # Unknown ASN still appears, with empty name.
    store.record_asn_bucket(bucket_ts="2026-07-14T13:00:00", asn=64500, updates=500, announcements=500, distinct=2)

    league = store.asn_league(since="2026-07-14T12:00:00", limit=10)

    # Ranked by announcements now, not message count.
    assert [row["asn"] for row in league] == [64500, 15169, 2856]
    assert league[0]["peak_distinct"] == 2
    # Peak distinct across the window is the max hourly value, never a sum.
    assert league[2]["peak_distinct"] == 40
    assert league[1]["name"] == "Google LLC"
    assert league[2]["name"] == "British Telecommunications PLC"
    assert league[2]["country"] == "GB"
    assert league[2]["updates"] == 80
    assert league[0]["name"] == ""


def test_asn_names_upsert_replaces(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "asn.db")
    store.init_schema()
    store.upsert_asn_names([(2856, "Old Name", "GB")])
    store.upsert_asn_names([(2856, "British Telecommunications PLC", "GB")])
    store.record_asn_bucket(bucket_ts="2026-07-14T13:00:00", asn=2856, updates=1, announcements=1, distinct=1)

    assert store.asn_league(since="2026-01-01T00:00:00", limit=1)[0]["name"] == "British Telecommunications PLC"


def test_prune_asn_activity(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "asn.db")
    store.init_schema()
    store.record_asn_bucket(bucket_ts="2026-07-01T00:00:00", asn=1, updates=1, announcements=1, distinct=1)
    store.record_asn_bucket(bucket_ts="2026-07-14T13:00:00", asn=1, updates=1, announcements=1, distinct=1)

    assert store.prune_asn_activity(before="2026-07-07T00:00:00") == 1


def test_prefix_flap_league_joins_names_and_ranks_by_events(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "flap.db")
    store.init_schema()
    store.upsert_asn_names([(15169, "Google LLC", "US"), (2856, "British Telecommunications PLC", "GB")])
    store.record_prefix_bucket(
        bucket_ts="2026-07-14T13:00:00", prefix="203.0.113.0/24",
        announcements=40, withdrawals=35, origin_asn=15169,
    )
    store.record_prefix_bucket(
        bucket_ts="2026-07-14T14:00:00", prefix="203.0.113.0/24",
        announcements=10, withdrawals=8, origin_asn=15169,
    )
    store.record_prefix_bucket(
        bucket_ts="2026-07-14T13:00:00", prefix="198.51.100.0/24",
        announcements=30, withdrawals=0, origin_asn=2856,
    )

    league = store.prefix_flap_league(since="2026-07-14T12:00:00", limit=10)

    assert [row["prefix"] for row in league] == ["203.0.113.0/24", "198.51.100.0/24"]
    assert league[0]["announcements"] == 50
    assert league[0]["withdrawals"] == 43
    assert league[0]["events"] == 93
    assert league[0]["hours"] == 2
    assert league[0]["origin_asn"] == 15169
    assert league[0]["origin_name"] == "Google LLC"
    assert league[1]["origin_country"] == "GB"


def test_prune_prefix_activity(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "flap.db")
    store.init_schema()
    store.record_prefix_bucket(bucket_ts="2026-07-01T00:00:00", prefix="p", announcements=1, withdrawals=0, origin_asn=None)
    store.record_prefix_bucket(bucket_ts="2026-07-14T13:00:00", prefix="p", announcements=1, withdrawals=0, origin_asn=None)

    assert store.prune_prefix_activity(before="2026-07-07T00:00:00") == 1


def test_origin_events_dedupe_per_hour_and_join_names(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "origin.db")
    store.init_schema()
    store.upsert_asn_names([(64500, "Old Net", "GB"), (64666, "New Net", "TR")])

    store.record_origin_event(
        observed_at="2026-07-14T13:02:11", prefix="203.0.113.0/24", old_asn=64500, new_asn=64666
    )
    # Same transition again in the same hour: flips increments, no new row.
    store.record_origin_event(
        observed_at="2026-07-14T13:40:00", prefix="203.0.113.0/24", old_asn=64500, new_asn=64666
    )
    # The reverse transition is its own row (flip-flop pattern).
    store.record_origin_event(
        observed_at="2026-07-14T13:45:00", prefix="203.0.113.0/24", old_asn=64666, new_asn=64500
    )

    events = store.recent_origin_events(since="2026-07-14T13:00:00", limit=10)

    assert len(events) == 2
    # Most recent last-seen first.
    assert events[0]["old_asn"] == 64666 and events[0]["new_asn"] == 64500
    forward = events[1]
    assert forward["flips"] == 2
    assert forward["old_name"] == "Old Net"
    assert forward["new_name"] == "New Net"
    assert forward["new_country"] == "TR"
    assert forward["last_seen"] == "2026-07-14T13:40:00"


def test_prune_origin_events(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "origin.db")
    store.init_schema()
    store.record_origin_event(observed_at="2026-07-01T00:00:00", prefix="p", old_asn=1, new_asn=2)
    store.record_origin_event(observed_at="2026-07-14T13:00:00", prefix="p", old_asn=1, new_asn=2)

    assert store.prune_origin_events(before="2026-07-07T00:00:00") == 1


def test_rpki_scores_upsert_and_list(tmp_path):
    from routelens.store import RouteLensStore

    store = RouteLensStore(tmp_path / "rpki.db")
    store.init_schema()
    store.upsert_asn_names([(2856, "British Telecommunications PLC", "GB")])

    store.upsert_rpki_score(asn=2856, total=100, valid=97, invalid=1, notfound=2)
    store.upsert_rpki_score(asn=64500, total=10, valid=0, invalid=0, notfound=10)
    # Re-scoring replaces.
    store.upsert_rpki_score(asn=2856, total=101, valid=99, invalid=0, notfound=2)

    scores = store.list_rpki_scores()

    assert len(scores) == 2
    bt = next(s for s in scores if s["asn"] == 2856)
    assert bt["total"] == 101
    assert bt["valid"] == 99
    assert bt["name"] == "British Telecommunications PLC"
    assert bt["checked_at"]
