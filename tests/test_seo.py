from routelens.app import create_app


def _client(tmp_path, config=None):
    cfg = {"DATABASE": str(tmp_path / "seo.db"), "TESTING": True}
    if config:
        cfg.update(config)
    return create_app(cfg).test_client()


def test_robots_txt_allows_crawl_and_points_at_sitemap(tmp_path):
    client = _client(tmp_path)

    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    body = response.data.decode()
    assert "User-agent: *" in body
    assert "Sitemap:" in body
    assert "/sitemap.xml" in body


def test_sitemap_lists_key_public_pages(tmp_path):
    client = _client(tmp_path)

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert "xml" in response.mimetype
    body = response.data.decode()
    assert "<urlset" in body
    # Home, looking glass, dashboards index and about should be discoverable.
    for path in ("/", "/q", "/dashboards/", "/about"):
        assert f"<loc>http://localhost{path}</loc>" in body


def test_home_page_has_description_and_canonical_and_og(tmp_path):
    client = _client(tmp_path)

    body = client.get("/").data.decode()

    assert '<meta name="description"' in body
    assert '<link rel="canonical"' in body
    assert 'property="og:image"' in body
    assert "/static/og.png" in body
    assert 'name="twitter:card"' in body


def test_home_page_has_webapplication_structured_data(tmp_path):
    client = _client(tmp_path)

    body = client.get("/").data.decode()

    assert 'application/ld+json' in body
    assert '"@type": "WebApplication"' in body


def test_beacon_absent_without_token(tmp_path):
    client = _client(tmp_path)

    body = client.get("/").data.decode()

    assert "cloudflareinsights.com" not in body


def test_beacon_present_with_token(tmp_path):
    client = _client(tmp_path, {"CLOUDFLARE_ANALYTICS_TOKEN": "test-token-123"})

    body = client.get("/").data.decode()

    assert "static.cloudflareinsights.com/beacon.min.js" in body
    assert "test-token-123" in body
