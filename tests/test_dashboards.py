from datetime import datetime, timedelta, timezone

from routelens.app import create_app


def _bucket(minutes_ago: int) -> str:
    dt = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})


def test_collector_league_page_serves_shell(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.get("/dashboards/collectors")
    body = response.data.decode()

    assert response.status_code == 200
    assert "Collector activity" in body
    assert "/partials/dashboards/collectors" in body


def test_collector_league_partial_ranks_and_annotates(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    for ago in (1, 2, 3):
        store.record_activity_bucket(bucket_ts=_bucket(ago), rrc="rrc01", updates=100, announcements=90, withdrawals=10)
        store.record_activity_bucket(bucket_ts=_bucket(ago), rrc="rrc06", updates=300, announcements=280, withdrawals=20)
    client = app.test_client()

    response = client.get("/partials/dashboards/collectors?window=3600")
    body = response.data.decode()

    assert response.status_code == 200
    # Tokyo outranks London.
    assert body.index("rrc06") < body.index("rrc01")
    # Collector metadata is joined in.
    assert "Tokyo" in body
    assert "London" in body
    # The UK collector is highlighted.
    assert "uk-row" in body
    # Sparkline SVG present.
    assert "<svg" in body


def test_collector_league_partial_empty_state(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.get("/partials/dashboards/collectors?window=3600")
    body = response.data.decode()

    assert response.status_code == 200
    assert "aggregator" in body.lower()


def test_collector_league_partial_rejects_bad_window(tmp_path):
    client = _app(tmp_path).test_client()

    assert client.get("/partials/dashboards/collectors?window=999999").status_code == 400
    assert client.get("/partials/dashboards/collectors?window=abc").status_code == 400


def test_all_pages_render_global_sidebar_with_categories(tmp_path):
    client = _app(tmp_path).test_client()

    for path in ("/", "/dashboards/collectors"):
        body = client.get(path).data.decode()
        assert 'class="sidenav"' in body, path
        # Category headers group the navigation.
        assert "Live" in body and "BGP activity" in body and "Routing table" in body, path
        # Pulse and the looking glass are first-class destinations.
        assert 'href="/"' in body and 'href="/q"' in body, path
        # All ten roadmap dashboards are listed by title.
        for title in [
            "Collector activity", "ASN churn", "Prefix flaps", "Origin changes",
            "RPKI scoreboard", "Address space", "ASN profiles", "Table growth",
            "Transit centrality", "Country instability",
        ]:
            assert title in body, (path, title)
        # The full roadmap shipped: every dashboard is a live link now.
        assert 'class="planned"' not in body, path

    # The current page is marked in the sidebar.
    assert 'aria-current="page"' in client.get("/dashboards/collectors").data.decode()


def test_bare_looking_glass_page_shows_prompt_not_error(tmp_path):
    client = _app(tmp_path).test_client()

    body = client.get("/q").data.decode()

    assert "not recognised" not in body.lower()
    assert "looking glass" in body.lower()


def test_dashboards_index_redirects_to_first_live(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.get("/dashboards/")

    assert response.status_code in (301, 302, 308)
    assert response.headers["Location"].endswith("/dashboards/collectors")


def _hour_bucket(hours_ago: int) -> str:
    dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def test_asn_league_page_and_partial(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(2856, "British Telecommunications PLC", "GB"), (15169, "Google LLC", "US")])
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=15169, updates=900, announcements=950)
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=2856, updates=400, announcements=420)
    client = app.test_client()

    page = client.get("/dashboards/asns")
    assert page.status_code == 200
    assert b"ASN churn" in page.data

    partial = client.get("/partials/dashboards/asns?window=21600")
    body = partial.data.decode()
    assert partial.status_code == 200
    assert body.index("AS15169") < body.index("AS2856")
    assert "Google LLC" in body
    assert "British Telecommunications PLC" in body
    # UK operators highlighted, mirroring the collector league.
    assert "uk-row" in body
    # ASNs link into the future profile/looking-glass flow via /q.
    assert "/q?query=AS15169" in body


def test_asn_league_partial_empty_and_bad_window(tmp_path):
    client = _app(tmp_path).test_client()

    empty = client.get("/partials/dashboards/asns?window=21600")
    assert empty.status_code == 200
    assert "aggregator" in empty.data.decode().lower()

    assert client.get("/partials/dashboards/asns?window=123").status_code == 400


def test_sidebar_marks_asn_dashboard_live(tmp_path):
    client = _app(tmp_path).test_client()

    body = client.get("/dashboards/collectors").data.decode()

    assert 'href="/dashboards/asns"' in body


def test_league_partials_carry_live_markers(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.record_activity_bucket(bucket_ts=_bucket(1), rrc="rrc01", updates=10, announcements=9, withdrawals=1)
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=15169, updates=10, announcements=11)
    client = app.test_client()

    collectors = client.get("/partials/dashboards/collectors?window=3600").data.decode()
    asns = client.get("/partials/dashboards/asns?window=21600").data.decode()

    assert 'data-live="rrc"' in collectors
    assert 'data-key="rrc01"' in collectors
    assert 'class="num mono c-upd" data-v="10"' in collectors
    assert 'data-live="asn"' in asns
    assert 'data-key="15169"' in asns


def test_dashboard_pages_include_live_league_script(tmp_path):
    client = _app(tmp_path).test_client()

    for path in ("/dashboards/collectors", "/dashboards/asns"):
        body = client.get(path).data.decode()
        assert "ris-live.ripe.net/v1/ws" in body, path
        assert 'id="livebadge"' in body, path


def test_asn_pattern_badges_carry_explanatory_tooltips(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    # 950 announcements over 10 distinct prefixes -> flappy (ratio > 20).
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=64500, updates=900, announcements=950, distinct=10)
    # Spread across 600 distinct prefixes -> estate-wide.
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=64501, updates=700, announcements=700, distinct=600)
    client = app.test_client()

    body = client.get("/partials/dashboards/asns?window=21600").data.decode()

    assert 'class="badge warning" title="' in body
    assert "instability" in body
    assert 'class="badge unknown" title="' in body
    assert "re-announcement" in body
    # The column header explains the heuristic too.
    assert '<th title="' in body


def test_league_column_headers_carry_tooltips(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.record_activity_bucket(bucket_ts=_bucket(1), rrc="rrc01", updates=10, announcements=9, withdrawals=1)
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=15169, updates=10, announcements=11, distinct=5)
    client = app.test_client()

    asns = client.get("/partials/dashboards/asns?window=21600").data.decode()
    collectors = client.get("/partials/dashboards/collectors?window=3600").data.decode()

    # Every data column in the ASN league explains itself on hover.
    for phrase in ("origin AS", "bgp.tools", "distinct", "BGP UPDATE"):
        assert phrase in asns, phrase
    assert asns.count('title="') >= 7
    # Same for the collector league.
    for phrase in ("route collector", "peers", "withdraw"):
        assert phrase in collectors, phrase
    assert collectors.count('title="') >= 9


def test_flap_league_page_and_partial(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(15169, "Google LLC", "US"), (2856, "British Telecommunications PLC", "GB")])
    store.record_prefix_bucket(
        bucket_ts=_hour_bucket(0), prefix="203.0.113.0/24",
        announcements=40, withdrawals=35, origin_asn=15169,
    )
    store.record_prefix_bucket(
        bucket_ts=_hour_bucket(0), prefix="198.51.100.0/24",
        announcements=30, withdrawals=0, origin_asn=2856,
    )
    client = app.test_client()

    page = client.get("/dashboards/flaps")
    assert page.status_code == 200
    assert b"Prefix flap" in page.data

    body = client.get("/partials/dashboards/flaps?window=21600").data.decode()
    assert body.index("203.0.113.0/24") < body.index("198.51.100.0/24")
    assert "Google LLC" in body
    # Announce+withdraw cycling is flagged; announce-only churn is not.
    assert 'class="badge critical"' in body and "flapping" in body
    # UK-origin prefixes highlighted.
    assert "uk-row" in body
    # Prefixes link into the looking glass; live markers present.
    assert "/q?query=203.0.113.0/24" in body
    assert 'data-live="prefix"' in body
    assert 'data-key="203.0.113.0/24"' in body


def test_flap_league_partial_empty_and_bad_window(tmp_path):
    client = _app(tmp_path).test_client()

    empty = client.get("/partials/dashboards/flaps?window=21600")
    assert empty.status_code == 200
    assert "aggregator" in empty.data.decode().lower()

    assert client.get("/partials/dashboards/flaps?window=42").status_code == 400


def test_origin_changes_page_and_partial(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(64500, "Old Net Ltd", "GB"), (64666, "New Net LLC", "TR")])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    store.record_origin_event(observed_at=now, prefix="203.0.113.0/24", old_asn=64500, new_asn=64666)
    for _ in range(3):
        store.record_origin_event(observed_at=now, prefix="198.51.100.0/24", old_asn=64500, new_asn=64777)
        store.record_origin_event(observed_at=now, prefix="198.51.100.0/24", old_asn=64777, new_asn=64500)
    client = app.test_client()

    page = client.get("/dashboards/origin-changes")
    assert page.status_code == 200
    assert b"Origin change" in page.data

    body = client.get("/partials/dashboards/origin-changes?window=21600").data.decode()
    assert "203.0.113.0/24" in body
    assert "Old Net Ltd" in body
    assert "New Net LLC" in body
    assert "AS64500" in body and "AS64666" in body
    # Repeated same-pair transitions are marked as flip-flopping, not a move.
    assert "flip-flop" in body
    assert "moved" in body
    # Old origin was UK: row highlighted.
    assert "uk-row" in body
    assert "/q?query=203.0.113.0/24" in body


def test_origin_changes_partial_empty_and_bad_window(tmp_path):
    client = _app(tmp_path).test_client()

    empty = client.get("/partials/dashboards/origin-changes?window=21600")
    assert empty.status_code == 200
    assert "no confirmed origin changes" in empty.data.decode().lower()

    assert client.get("/partials/dashboards/origin-changes?window=7").status_code == 400


def test_rpki_scoreboard_page_and_partial(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(2856, "British Telecommunications PLC", "GB"), (64666, "Sloppy Networks", "US")])
    store.upsert_rpki_score(asn=2856, total=100, valid=97, invalid=0, notfound=3)
    store.upsert_rpki_score(asn=64666, total=50, valid=10, invalid=3, notfound=37)
    client = app.test_client()

    page = client.get("/dashboards/rpki")
    assert page.status_code == 200
    assert b"RPKI" in page.data

    body = client.get("/partials/dashboards/rpki").data.decode()
    # Ranked by coverage: BT (97%) before Sloppy (20%).
    assert body.index("AS2856") < body.index("AS64666")
    assert "97%" in body
    assert "signed" in body       # >=95% coverage verdict
    assert "poor" in body         # <50% coverage verdict
    # Invalid routes get called out loudly.
    assert "3 invalid" in body
    assert "uk-row" in body


def test_rpki_scoreboard_empty_state(tmp_path):
    client = _app(tmp_path).test_client()

    body = client.get("/partials/dashboards/rpki").data.decode()

    assert "no rpki scores yet" in body.lower()


def test_table_growth_page_and_partial(tmp_path):
    app = _app(tmp_path)

    class FakeSources:
        def table_growth(self, **kwargs):
            return {
                "ok": True,
                "data": {
                    "current_v4": 1064633, "current_v6": 256115,
                    "week_delta_v4": 1200, "year_delta_v4": 42000,
                    "week_delta_v6": 300, "year_delta_v6": 21000,
                    "v4": [["2025-07-01", 1022000], ["2026-07-14", 1064633]],
                    "v6": [["2025-07-01", 235000], ["2026-07-14", 256115]],
                },
            }

    app.config["ROUTELENS_SOURCES"] = FakeSources()
    client = app.test_client()

    page = client.get("/dashboards/table-growth")
    assert page.status_code == 200
    assert b"Table growth" in page.data or b"table growth" in page.data

    body = client.get("/partials/dashboards/table-growth").data.decode()
    assert "1,064,633" in body
    assert "256,115" in body
    # Charts are server-rendered SVG polylines.
    assert body.count("<svg") >= 2
    assert "polyline" in body
    # Deltas shown.
    assert "42,000" in body


def test_table_growth_partial_degrades_on_error(tmp_path):
    app = _app(tmp_path)

    class FakeSources:
        def table_growth(self, **kwargs):
            return {"ok": False, "error": "potaroo unreachable"}

    app.config["ROUTELENS_SOURCES"] = FakeSources()

    body = app.test_client().get("/partials/dashboards/table-growth").data.decode()

    assert "potaroo unreachable" in body


def test_transit_league_page_and_partial(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(3356, "Lumen (Level 3)", "US"), (2856, "British Telecommunications PLC", "GB")])
    store.record_transit_bucket(bucket_ts=_hour_bucket(0), asn=3356, paths=9000)
    store.record_transit_bucket(bucket_ts=_hour_bucket(0), asn=2856, paths=1000)
    store.record_path_stats(bucket_ts=_hour_bucket(0), paths=20000, hops=84000)
    client = app.test_client()

    page = client.get("/dashboards/transit")
    assert page.status_code == 200
    assert b"Transit centrality" in page.data

    body = client.get("/partials/dashboards/transit?window=21600").data.decode()
    assert body.index("AS3356") < body.index("AS2856")
    assert "Lumen" in body
    # Share of observed paths: 9000/20000 = 45%.
    assert "45.0%" in body
    # Average dedup path length: 84000/20000 = 4.2.
    assert "4.2" in body
    assert "uk-row" in body
    assert 'data-live="transit"' in body
    assert 'data-key="3356"' in body


def test_transit_partial_empty_and_bad_window(tmp_path):
    client = _app(tmp_path).test_client()

    empty = client.get("/partials/dashboards/transit?window=21600")
    assert empty.status_code == 200
    assert "aggregator" in empty.data.decode().lower()

    assert client.get("/partials/dashboards/transit?window=1").status_code == 400


def test_country_league_page_and_partial(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(1, "BR One", "BR"), (2, "BR Two", "BR"), (3, "GB One", "GB")])
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=1, updates=100, announcements=120)
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=2, updates=200, announcements=230)
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=3, updates=50, announcements=60)
    client = app.test_client()

    page = client.get("/dashboards/countries")
    assert page.status_code == 200
    assert b"Country instability" in page.data

    body = client.get("/partials/dashboards/countries?window=21600").data.decode()
    assert body.index("Brazil") < body.index("United Kingdom")
    # Flag emojis are derived from the ISO code.
    assert "🇧🇷" in body and "🇬🇧" in body
    # Intensity = announcements per active origin (350/2 = 175).
    assert "175" in body
    assert "uk-row" in body


def test_country_league_partial_empty_and_bad_window(tmp_path):
    client = _app(tmp_path).test_client()

    empty = client.get("/partials/dashboards/countries?window=21600")
    assert empty.status_code == 200
    assert "aggregator" in empty.data.decode().lower()

    assert client.get("/partials/dashboards/countries?window=2").status_code == 400


def test_asn_profiles_index_lists_uk_operators_and_churners(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(2856, "British Telecommunications PLC", "GB"), (15169, "Google LLC", "US")])
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=15169, updates=900, announcements=950)
    client = app.test_client()

    response = client.get("/dashboards/asn-profiles")
    body = response.data.decode()

    assert response.status_code == 200
    assert "ASN profiles" in body
    # UK operators listed with names, linking into the profile view.
    assert "/q?query=AS2856" in body
    assert "British Telecommunications PLC" in body
    # Current churners offered as examples too.
    assert "/q?query=AS15169" in body


def test_address_space_page_and_partial(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(3356, "Lumen", "US"), (2856, "British Telecommunications PLC", "GB")])
    store.replace_address_space([
        {"asn": 3356, "v4_slash24": 100000, "v6_slash48": 5000000, "prefixes": 9000},
        {"asn": 2856, "v4_slash24": 40000, "v6_slash48": 2000000, "prefixes": 500},
    ])
    client = app.test_client()

    page = client.get("/dashboards/address-space")
    assert page.status_code == 200
    assert b"Address space" in page.data

    body = client.get("/partials/dashboards/address-space").data.decode()
    assert body.index("AS3356") < body.index("AS2856")
    assert "100,000" in body
    assert "uk-row" in body
    assert "scanned" in body.lower()


def test_address_space_empty_state(tmp_path):
    client = _app(tmp_path).test_client()

    body = client.get("/partials/dashboards/address-space").data.decode()

    assert "no address-space scan yet" in body.lower()


def test_linx_dashboard_removed_league_carries_the_uk_angle(tmp_path):
    client = _app(tmp_path).test_client()

    # The separate LINX activity section is gone...
    assert client.get("/dashboards/linx").status_code == 404
    assert client.get("/partials/dashboards/linx-exchange?group=LINX%20Scotland").status_code == 404
    # ...and so is its sidebar category.
    body = client.get("/dashboards/collectors").data.decode()
    assert "United Kingdom" not in body
    assert "/dashboards/linx" not in body


def test_league_linx_tag_is_ixp_driven(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.record_activity_bucket(bucket_ts=_bucket(1), rrc="rrc01", updates=10, announcements=9, withdrawals=1)
    store.record_activity_bucket(bucket_ts=_bucket(1), rrc="rrc12", updates=10, announcements=9, withdrawals=1)
    client = app.test_client()

    body = client.get("/partials/dashboards/collectors?window=3600").data.decode()

    # The LINX tag rides on IXP hosting data and explains itself.
    assert "hosted at LINX" in body
    # Frankfurt (DE-CIX) gets no LINX tag.
    rrc12_row = body[body.index('data-key="rrc12"'):body.index('data-key="rrc12"') + 400]
    assert "LINX" not in rrc12_row


def test_weather_page_renders_latest_report(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.save_weather_report(
        period_hours=6, headline="Squall over Sudan", severity="minor",
        body_md="## Summary\nA regional outage in **Sudan** lines up with a churn spike.",
        evidence={"ioda": [{"entity_code": "SD"}]}, model="mistral-small-latest",
    )
    client = app.test_client()

    body = client.get("/dashboards/weather").data.decode()

    assert "Internet Weather" in body
    assert "Squall over Sudan" in body
    # Markdown body is rendered (bold -> strong), severity shown, sources credited.
    assert "<strong>Sudan</strong>" in body
    assert "minor" in body
    assert "IODA" in body and "GRIP" in body and "Radar" in body


def test_weather_page_empty_state_when_no_report(tmp_path):
    client = _app(tmp_path).test_client()

    body = client.get("/dashboards/weather").data.decode()

    assert "Internet Weather" in body
    assert "no briefing" in body.lower()


def test_weather_in_sidebar_under_live(tmp_path):
    body = _app(tmp_path).test_client().get("/dashboards/weather").data.decode()

    assert "/dashboards/weather" in body


def test_map_outages_merges_ioda_and_radar_by_country(tmp_path):
    app = _app(tmp_path)

    class FakeSources:
        def ioda_alerts(self):
            return {"ok": True, "data": {"alerts": [
                {"entity_type": "country", "entity_code": "SD", "entity_name": "Sudan",
                 "datasource": "merit-nt", "level": "critical", "value": 10, "history": 55},
                {"entity_type": "asn", "entity_code": "64500", "entity_name": "AS64500",
                 "datasource": "bgp", "level": "critical", "value": 1, "history": 9},
            ]}}

        def radar_outages(self):
            return {"ok": True, "data": {"outages": [
                {"id": "o1", "locations": ["SD"], "cause": "POWER_OUTAGE", "scope": "NATIONWIDE",
                 "description": "Nationwide outage", "asns": [], "start": "x", "end": None},
            ]}}

    app.config["ROUTELENS_SOURCES"] = FakeSources()
    payload = app.test_client().get("/api/map/outages").get_json()

    countries = payload["countries"]
    sd = next(c for c in countries if c["country"] == "SD")
    # The client places rings using its own world.geojson centroids, so the
    # server returns country codes + metadata, not coordinates.
    assert sd["name"] == "Sudan"
    assert sd["ioda"] is True
    assert sd["radar"] is True
    assert "POWER_OUTAGE" in sd["causes"]
    # ASN-scoped IODA alerts don't get a map ring (no location), but are counted.
    assert payload["asn_alert_count"] == 1


def test_weather_page_renders_visual_evidence(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.save_weather_report(
        period_hours=6, headline="Squall over Sudan", severity="minor",
        body_md="## Summary\nSee below.",
        evidence={
            "internal": {
                "collector_spikes": [{"rrc": "rrc01", "last_hour": 5000, "hourly_baseline": 500, "ratio": 10.0}],
                "country_hotspots": [{"country": "SD", "intensity": 9000, "announcements": 9000, "origins": 1}],
                "top_churners": [{"asn": 15169, "name": "Google LLC", "announcements": 800}],
                "flap_leaders": [{"prefix": "203.0.113.0/24", "events": 900, "origin_asn": 15169, "flapping": True}],
                "origin_changes": {"count": 1, "recent": [
                    {"prefix": "198.51.100.0/24", "old_asn": 64500, "new_asn": 64666, "flips": 2, "last_seen": "x"}]},
            },
            "ioda": [{"entity_type": "country", "entity_code": "AF", "entity_name": "Afghanistan",
                      "datasource": "merit-nt", "level": "critical", "value": 10, "history": 55}],
            "grip": [{"id": "g1", "suspicion": 85, "label": "suspicious", "attackers": ["64666"],
                      "victims": ["64500"], "explanation": "hijack-y"}],
            "radar_outages": [],
        },
        model="mistral-small-latest",
    )
    body = app.test_client().get("/dashboards/weather").data.decode()

    # Stat tiles, hero severity, and section anchors.
    assert 'class="wx-tile"' in body and "churn hotspots" in body
    assert 'id="wx-hotspots"' in body and 'id="wx-hijacks"' in body
    # Data-driven map payload + hotspot bar.
    assert 'id="wx-map"' in body and "/static/world.geojson" in body
    assert 'class="hbar' in body
    # Drill-down links to existing looking-glass pages.
    assert "/q?query=AS15169" in body            # churner
    assert "/q?query=AS64666" in body            # hijack attacker + origin change
    assert "/q?query=203.0.113.0/24" in body     # flap leader
    # Flag rendered for the hotspot country.
    assert "🇸🇩" in body


def test_weather_narrative_is_in_a_modal_and_tables_are_constrained(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.save_weather_report(
        period_hours=6, headline="H", severity="minor", body_md="Watch **AS15169**.",
        evidence={"internal": {"top_churners": [{"asn": 15169, "name": "X", "announcements": 5}]},
                  "ioda": [], "grip": [], "radar_outages": []},
        model="m",
    )
    body = app.test_client().get("/dashboards/weather").data.decode()

    # Narrative lives in a click-to-open dialog, opened by a button.
    assert '<dialog id="wx-briefing"' in body
    assert 'class="wx-open"' in body and "showModal()" in body
    # The narrative (with its linkified entity) is inside the dialog markup.
    assert 'query=AS15169' in body
    # Evidence tables are constrained so long content can't overflow the panel.
    assert "wx-evidence" in body
    assert "table-layout:fixed" in body


def test_companies_page_shell_and_sidebar(tmp_path):
    client = _app(tmp_path).test_client()

    body = client.get("/dashboards/companies").data.decode()
    assert "Service health" in body or "Company health" in body
    assert "/partials/dashboards/companies" in body
    # Sidebar links to it.
    assert '/dashboards/companies' in client.get("/dashboards/collectors").data.decode()


def test_companies_partial_renders_status_and_bgp(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(13335, "Cloudflare", "US")])
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=13335, updates=50, announcements=120)

    class FakeSources:
        def company_status(self, feed):
            if feed and "cloudflare" in feed.get("url", ""):
                return {"ok": True, "data": {"state": "operational", "detail": "All Systems Operational"}}
            return {"ok": True, "data": {"state": "unknown", "detail": "no public status feed"}}

    app.config["ROUTELENS_SOURCES"] = FakeSources()
    body = app.test_client().get("/partials/dashboards/companies").data.decode()

    assert "Cloudflare" in body
    assert "operational" in body
    # UK section present with its own heading.
    assert "United Kingdom" in body or "UK" in body
    assert "BT / EE" in body
    # Company ASNs drill into the looking glass.
    assert "/q?query=AS13335" in body
    # No-feed companies are shown honestly.
    assert "Netflix" in body
