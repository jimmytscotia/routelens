from routelens.app import create_app
from routelens.collectors import ACTIVE_COLLECTORS


def _app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})


def test_root_serves_pulse_page(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.get("/")
    body = response.data.decode()

    assert response.status_code == 200
    assert 'id="pulse-map"' in body
    assert 'id="ticker"' in body
    assert "ris-live" in body  # the live layer connects to RIS Live


def test_watchlist_is_removed_for_now(tmp_path):
    client = _app(tmp_path).test_client()

    assert client.get("/watchlist").status_code == 404


def test_api_collectors_returns_active_rrcs_with_coordinates(tmp_path):
    client = _app(tmp_path).test_client()

    response = client.get("/api/collectors")
    payload = response.get_json()

    assert response.status_code == 200
    assert len(payload["collectors"]) == len(ACTIVE_COLLECTORS) == 23
    rrc01 = next(c for c in payload["collectors"] if c["rrc"] == "rrc01")
    assert rrc01["city"] == "London"
    assert 51 < rrc01["lat"] < 52
    assert -1 < rrc01["lon"] < 1


def test_collector_table_has_no_duplicate_ids():
    ids = [c["rrc"] for c in ACTIVE_COLLECTORS]

    assert len(ids) == len(set(ids))


def test_pulse_map_has_layer_controls_and_data_sources(tmp_path):
    client = _app(tmp_path).test_client()

    body = client.get("/").data.decode()

    # Layer switcher pills for the three activity views + UK preset.
    for layer in ("collectors", "churn", "events"):
        assert f'data-layer="{layer}"' in body, layer
    assert 'id="uk-btn"' in body
    # The map is fed by the vendored boundaries and the map APIs.
    assert "/static/world.geojson" in body
    assert "/api/map/collectors" in body
    assert "/api/map/countries" in body
    assert "/api/map/events" in body
    # Choropleth legend and the allocation caveat are present.
    assert 'id="map-legend"' in body
    assert "registration" in body
