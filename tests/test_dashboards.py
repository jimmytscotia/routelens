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
