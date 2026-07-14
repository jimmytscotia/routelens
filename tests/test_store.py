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
