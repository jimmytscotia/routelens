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


def test_dashboard_pages_render_sidebar_with_all_dashboards(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.get("/dashboards/collectors")
    body = response.data.decode()

    assert response.status_code == 200
    assert 'class="dashnav"' in body
    # Live dashboards are links; the current one is marked.
    assert 'aria-current="page"' in body
    # All ten roadmap dashboards are listed by title.
    for title in [
        "Collector activity",
        "ASN churn",
        "Prefix flaps",
        "Origin changes",
        "RPKI scoreboard",
        "Address space",
        "ASN profiles",
        "Table growth",
        "Transit centrality",
        "Country instability",
    ]:
        assert title in body
    # Planned ones are labelled, not linked.
    assert "soon" in body.lower()


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
