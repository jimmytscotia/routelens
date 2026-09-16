"""CARTO basemap key plumbing.

CARTO put their raster basemaps behind an API key in 2026: keyless tiles come
back stamped "API KEY REQUIRED". The key is a public, domain-restricted one that
has to reach the browser, so it is rendered into the page rather than proxied.
"""

from routelens.app import create_app

MAP_PAGES = ("/", "/dashboards/weather")


def _app(tmp_path, **config):
    app = create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True, **config})
    # The weather map only renders alongside a briefing, so seed one.
    app.config["ROUTELENS_STORE"].save_weather_report(
        period_hours=6, headline="Test briefing", severity="calm",
        body_md="Nothing to report.", evidence={"ioda": [{"entity_code": "SD"}]},
        model="mistral-small-latest",
    )
    return app


def test_map_pages_send_the_carto_key_when_configured(tmp_path):
    client = _app(tmp_path, CARTO_BASEMAP_KEY="test_key_123").test_client()

    for page in MAP_PAGES:
        body = client.get(page).data.decode()

        assert "test_key_123" in body, f"{page} did not carry the CARTO key"


def test_map_pages_omit_the_key_parameter_when_unset(tmp_path):
    client = _app(tmp_path, CARTO_BASEMAP_KEY="").test_client()

    for page in MAP_PAGES:
        body = client.get(page).data.decode()

        # No dangling "?key=" — an empty key is worse than none, as CARTO would
        # reject the request outright rather than serve a watermarked tile.
        assert "?key=" not in body, f"{page} sent an empty key parameter"


def test_carto_key_is_read_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CARTO_BASEMAP_KEY", "from_env")
    monkeypatch.setenv("ROUTELENS_DATABASE", str(tmp_path / "env.db"))

    app = create_app()

    assert app.config["CARTO_BASEMAP_KEY"] == "from_env"


def test_carto_key_defaults_to_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("CARTO_BASEMAP_KEY", raising=False)
    monkeypatch.setenv("ROUTELENS_DATABASE", str(tmp_path / "env.db"))

    app = create_app()

    assert app.config["CARTO_BASEMAP_KEY"] == ""
