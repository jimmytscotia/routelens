from routelens.companies import COMPANIES, all_company_asns


def test_registry_shape_and_no_chinese_companies():
    for c in COMPANIES:
        assert c["name"] and c["category"]
        assert isinstance(c["asns"], list)
        assert "status" in c
        if c["status"] is not None:
            assert c["status"]["type"] in ("statuspage", "gcp", "aws", "apple", "meta", "microsoft")
            assert c["status"]["url"].startswith("https://")
    names = {c["name"] for c in COMPANIES}
    # A few headline names present; nothing from the excluded set.
    assert {"Cloudflare", "Google Cloud", "Apple", "Meta"} <= names
    for banned in ("Alibaba", "Tencent", "Baidu", "Huawei", "ByteDance"):
        assert banned not in names


def test_uk_section_present():
    uk = [c for c in COMPANIES if c.get("uk")]
    assert {"BT / EE", "Sky", "Vodafone UK", "BBC"} <= {c["name"] for c in uk}


def test_all_company_asns_deduped():
    asns = all_company_asns()
    assert len(asns) == len(set(asns))
    assert 13335 in asns and 8075 in asns   # Cloudflare, Microsoft


def test_build_company_board_merges_status_and_bgp(tmp_path):
    from routelens.store import RouteLensStore
    from routelens.companies import build_company_board

    store = RouteLensStore(tmp_path / "board.db")
    store.init_schema()
    store.upsert_asn_names([(13335, "Cloudflare", "US")])
    store.record_asn_bucket(bucket_ts="2026-07-16T10:00:00", asn=13335, updates=50, announcements=120)
    store.upsert_rpki_score(asn=13335, total=100, valid=98, invalid=0, notfound=2)

    class FakeSources:
        def company_status(self, feed):
            if feed and "cloudflare" in feed.get("url", ""):
                return {"ok": True, "data": {"state": "degraded", "detail": "Minor Service Outage"}}
            return {"ok": True, "data": {"state": "unknown", "detail": "no public status feed"}}

    registry = [
        {"name": "Cloudflare", "category": "Cloud & infrastructure", "asns": [13335],
         "status": {"type": "statuspage", "url": "https://www.cloudflarestatus.com/api/v2/status.json"}},
        {"name": "X (Twitter)", "category": "Consumer & social", "asns": [13414], "status": None},
        {"name": "BBC", "category": "UK services", "asns": [2818], "status": None, "uk": True},
    ]

    board = build_company_board(store, FakeSources(), registry=registry,
                                since="2026-07-16T00:00:00")

    groups = {g["category"]: g for g in board["global"]}
    cf = next(c for c in groups["Cloud & infrastructure"]["companies"] if c["name"] == "Cloudflare")
    assert cf["state"] == "degraded"
    assert cf["detail"] == "Minor Service Outage"
    assert cf["announcements"] == 120
    assert cf["primary_asn"] == 13335
    assert cf["rpki_coverage"] == 98
    # No-feed company still gets a BGP row, status unknown.
    x = next(c for c in groups["Consumer & social"]["companies"] if c["name"] == "X (Twitter)")
    assert x["state"] == "unknown"
    # UK companies are split into their own section.
    uk_names = {c["name"] for g in board["uk"] for c in g["companies"]}
    assert "BBC" in uk_names
    assert all(c["name"] != "BBC" for g in board["global"] for c in g["companies"])


def test_bgp_stability_states(tmp_path):
    from routelens.store import RouteLensStore
    from routelens.companies import bgp_stability
    from datetime import datetime, timedelta, timezone

    store = RouteLensStore(tmp_path / "stab.db")
    store.init_schema()

    def hour(h):
        return (datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S")

    # AS100: steady ~100/hr for a day -> stable.
    for h in range(0, 24):
        store.record_asn_bucket(bucket_ts=hour(h), asn=100, updates=100, announcements=100)
    # AS200: flapping prefix in the last 6h -> unstable regardless of volume.
    store.record_asn_bucket(bucket_ts=hour(0), asn=200, updates=10, announcements=10)
    store.record_prefix_bucket(bucket_ts=hour(1), prefix="203.0.113.0/24",
                               announcements=40, withdrawals=40, origin_asn=200)
    # AS300: a big spike over its own baseline -> unstable (>=5x).
    for h in range(1, 24):
        store.record_asn_bucket(bucket_ts=hour(h), asn=300, updates=10, announcements=10)
    store.record_asn_bucket(bucket_ts=hour(0), asn=300, updates=800, announcements=800)

    stable = bgp_stability(store, [100])
    assert stable["state"] == "stable"

    unstable_flap = bgp_stability(store, [200])
    assert unstable_flap["state"] == "unstable"
    assert unstable_flap["flapping"] == 1

    unstable_spike = bgp_stability(store, [300])
    assert unstable_spike["state"] == "unstable"
    assert unstable_spike["spike"] >= 5


def test_bgp_stability_quiet_asn_is_stable(tmp_path):
    from routelens.store import RouteLensStore
    from routelens.companies import bgp_stability

    store = RouteLensStore(tmp_path / "quiet.db")
    store.init_schema()

    out = bgp_stability(store, [64500])
    assert out["state"] == "stable"
    assert out["announcements"] == 0
