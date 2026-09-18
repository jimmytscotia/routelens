"""Resource pages are private by default, and seeds carry no operator's estate.

The resource detail page exposes whatever the operator monitors — internal
hostnames, private-range answers, which services they run. On a public
deployment that is information disclosure, so the page is off unless the
operator opts in. The seeded defaults likewise have to be neutral: a fresh
database belongs to whoever cloned the repo, not to its author.
"""

from routelens.store import DEFAULT_RESOURCES, RouteLensStore
from routelens.app import create_app


def _app(tmp_path, **config):
    return create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True, **config})


def _seeded_resource_id(app):
    store = app.config["ROUTELENS_STORE"]
    return store.upsert_resource(
        name="example.net", resource_type="hostname", expected_mode="public",
        expected_ips=["192.0.2.10"], expected_url="https://example.net/",
    )


def test_resource_pages_are_404_by_default(tmp_path):
    app = _app(tmp_path)
    resource_id = _seeded_resource_id(app)

    assert app.test_client().get(f"/resources/{resource_id}").status_code == 404


def test_resource_pages_can_be_opted_into(tmp_path):
    app = _app(tmp_path, PUBLIC_RESOURCE_PAGES=True)
    resource_id = _seeded_resource_id(app)

    response = app.test_client().get(f"/resources/{resource_id}")

    assert response.status_code == 200
    assert b"example.net" in response.data


def test_opted_in_pages_still_404_for_unknown_resources(tmp_path):
    app = _app(tmp_path, PUBLIC_RESOURCE_PAGES=True)

    assert app.test_client().get("/resources/99999").status_code == 404


def test_resource_pages_flag_is_read_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTELENS_PUBLIC_RESOURCE_PAGES", "1")
    monkeypatch.setenv("ROUTELENS_DATABASE", str(tmp_path / "env.db"))

    assert create_app().config["PUBLIC_RESOURCE_PAGES"] is True


def test_default_seeds_contain_no_private_addresses_or_operator_hosts(tmp_path):
    store = RouteLensStore(str(tmp_path / "seed.db"))
    store.init_schema()
    store.seed_defaults()

    blob = repr(DEFAULT_RESOURCES)
    assert "nexthop" not in blob
    # Tailscale CGNAT (100.64.0.0/10) and RFC1918 have no place in public seeds.
    for private_prefix in ("100.6", "100.7", "100.8", "100.9", "10.", "192.168.", "172.16."):
        assert f'"{private_prefix}' not in blob.replace("'", '"')
    assert all(r["expected_mode"] != "private_lab" for r in DEFAULT_RESOURCES)


def test_seeding_never_removes_an_operators_own_resources(tmp_path):
    """Existing estates must survive an upgrade that changes the defaults."""
    store = RouteLensStore(str(tmp_path / "seed.db"))
    store.init_schema()
    mine = store.upsert_resource(
        name="grafana.internal.example", resource_type="hostname",
        expected_mode="private_lab", expected_ips=["192.0.2.20"],
    )

    store.seed_defaults()

    assert store.get_resource(mine) is not None
