import pytest

from routelens.app import create_app


class FakeSources:
    """Stands in for SourceClient; returns canned summaries."""

    def __init__(self):
        self.calls = []

    def ripestat_looking_glass(self, prefix):
        self.calls.append(("lg", prefix))
        return {
            "ok": True,
            "data": {
                "rrc_count": 1,
                "peer_count": 2,
                "origins": [15169],
                "query_time": "2026-07-14T10:00:00",
                "rrcs": [
                    {
                        "rrc": "RRC01",
                        "location": "London, United Kingdom",
                        "scope": "LINX",
                        "peer_count": 2,
                        "origins": [15169],
                        "sample_paths": [["3356", "15169"]],
                        "last_updated": "2026-07-14T09:00:00",
                    }
                ],
            },
        }

    def ripestat_routing_status(self, prefix):
        self.calls.append(("routing", prefix))
        return {
            "ok": True,
            "data": {
                "resource": prefix,
                "visibility_seeing": 110,
                "visibility_total": 110,
                "visibility_pct": 100,
                "origins": [15169],
                "first_seen": {"time": "2002-11-06T16:00:00", "origin": "21284"},
                "last_seen": {"time": "2026-07-14T08:00:00", "origin": "15169"},
                "less_specific_count": 2,
                "more_specific_count": 0,
            },
        }

    def ripestat_rpki(self, asn, prefix):
        self.calls.append(("rpki", asn, prefix))
        return {"ok": True, "data": {"status": "valid", "roa_count": 1, "roas": [], "prefix": prefix}}

    def ripestat_network_info(self, ip):
        self.calls.append(("netinfo", ip))
        return {"ok": True, "data": {"asns": [15169], "prefix": "8.8.8.0/24"}}

    def routeviews_prefix(self, prefix):
        self.calls.append(("routeviews", prefix))
        return {
            "ok": True,
            "data": {
                "origin_asns": [15169],
                "rpki_state": "valid",
                "roa_count": 1,
                "peer_count": 3,
                "collectors": ["route-views.linx"],
                "sample_paths": [["64500", "3356", "15169"]],
            },
        }

    def nlnog_prefix(self, prefix):
        self.calls.append(("nlnog", prefix))
        return {
            "ok": True,
            "data": {
                "prefix": prefix,
                "route_count": 1,
                "origins": [15169],
                "routes": [
                    {
                        "peer": "a2b-ip01",
                        "aspath": [["51088", "A2B - A2B IP B.V., NL"], ["15169", "GOOGLE - Google LLC, US"]],
                        "rpki": "valid",
                        "last_update_at": "2026-07-14 07:26:06 UTC",
                    }
                ],
            },
        }

    def radar_events(self, kind="hijacks"):
        self.calls.append(("radar", kind))
        return {"ok": False, "unconfigured": True, "error": "CLOUDFLARE_RADAR_TOKEN not set"}

    def globalping_create(self, target, **kwargs):
        self.calls.append(("gp_create", target))
        return {"ok": True, "data": {"id": "meas123", "probes": 3}}

    def globalping_result(self, measurement_id):
        self.calls.append(("gp_result", measurement_id))
        return {"ok": True, "data": {"status": "finished", "probes": []}}


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "DATABASE": str(tmp_path / "test.db"),
            "TESTING": True,
            "RESOLVER": lambda hostname: ["8.8.8.8"],
        }
    )
    app.config["ROUTELENS_SOURCES"] = FakeSources()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_query_page_for_prefix_renders_shell_with_panels(client):
    response = client.get("/q?query=8.8.8.0/24")
    body = response.data.decode()

    assert response.status_code == 200
    assert "8.8.8.0/24" in body
    # Panels lazy-load through HTMX partial endpoints ("/" is legal unescaped
    # in a query-string value; Jinja's urlencode leaves it as-is).
    assert "/partials/prefix/lg?prefix=8.8.8.0/24" in body
    assert "/partials/prefix/routing?prefix=8.8.8.0/24" in body
    assert "/partials/prefix/routeviews?prefix=8.8.8.0/24" in body
    assert "/partials/prefix/nlnog?prefix=8.8.8.0/24" in body


def test_query_page_for_invalid_input_shows_error(client):
    response = client.get("/q?query=not%20a%20thing!")
    body = response.data.decode()

    assert response.status_code == 200
    assert "recognised" in body or "invalid" in body.lower()


def test_query_page_for_hostname_resolves_and_shows_prefix_panels(client):
    response = client.get("/q?query=dns.google")
    body = response.data.decode()

    assert response.status_code == 200
    assert "dns.google" in body
    assert "8.8.8.8" in body
    assert "8.8.8.0/24" in body
    # Hostname pages also get a Globalping reachability panel.
    assert "globalping" in body.lower()


def test_lg_partial_renders_collector_table(client):
    response = client.get("/partials/prefix/lg?prefix=8.8.8.0/24")
    body = response.data.decode()

    assert response.status_code == 200
    assert "RRC01" in body
    assert "London" in body
    assert "AS15169" in body


def test_routing_partial_renders_visibility_and_rpki(client):
    response = client.get("/partials/prefix/routing?prefix=8.8.8.0/24")
    body = response.data.decode()

    assert response.status_code == 200
    assert "110" in body
    assert "valid" in body.lower()


def test_routing_partial_shows_origin_org_and_registry_link(client, app):
    app.config["ROUTELENS_STORE"].upsert_asn_names([(15169, "Google LLC", "US")])

    body = client.get("/partials/prefix/routing?prefix=8.8.8.0/24").data.decode()

    # Origin org name is shown, and a link to an authoritative registry.
    assert "Google LLC" in body
    assert "https://stat.ripe.net/AS15169" in body
    # The AS also drills into our own profile.
    assert "/q?query=AS15169" in body


def test_asn_summary_has_registry_links(client, app):
    app.config["ROUTELENS_STORE"].upsert_asn_names([(2856, "British Telecommunications PLC", "GB")])

    body = client.get("/partials/asn/summary?asn=2856").data.decode()

    assert "https://stat.ripe.net/AS2856" in body
    assert "bgp.tools/as/2856" in body


def test_routeviews_partial_renders_collectors(client):
    response = client.get("/partials/prefix/routeviews?prefix=8.8.8.0/24")
    body = response.data.decode()

    assert response.status_code == 200
    assert "route-views.linx" in body


def test_nlnog_partial_renders_named_paths(client):
    response = client.get("/partials/prefix/nlnog?prefix=8.8.8.0/24")
    body = response.data.decode()

    assert response.status_code == 200
    assert "GOOGLE" in body
    assert "a2b-ip01" in body


def test_radar_partial_degrades_when_unconfigured(client):
    response = client.get("/partials/radar")
    body = response.data.decode()

    assert response.status_code == 200
    assert "not configured" in body.lower()


def test_globalping_api_create_and_poll(client, app):
    created = client.post("/api/globalping", json={"target": "dns.google"})
    assert created.status_code == 202
    assert created.get_json()["data"]["id"] == "meas123"

    polled = client.get("/api/globalping/meas123")
    assert polled.status_code == 200
    assert polled.get_json()["data"]["status"] == "finished"

    calls = [c[0] for c in app.config["ROUTELENS_SOURCES"].calls]
    assert "gp_create" in calls and "gp_result" in calls


def test_globalping_api_rejects_invalid_target(client):
    response = client.post("/api/globalping", json={"target": "not a target!"})

    assert response.status_code == 400


def test_asn_query_renders_profile_shell(client, app):
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(2856, "British Telecommunications PLC", "GB")])

    response = client.get("/q?query=AS2856")
    body = response.data.decode()

    assert response.status_code == 200
    assert "British Telecommunications PLC" in body
    # Profile panels lazy-load.
    assert "/partials/asn/summary?asn=2856" in body
    assert "/partials/asn/prefixes?asn=2856" in body
    assert "/partials/asn/rpki?asn=2856" in body
    assert "/partials/asn/peeringdb?asn=2856" in body
    # The phase-2 stub is gone.
    assert "coming in phase 2" not in body


def test_asn_summary_partial_uses_local_stats(client, app):
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(2856, "British Telecommunications PLC", "GB")])
    from datetime import datetime, timezone
    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    store.record_asn_bucket(bucket_ts=hour, asn=2856, updates=40, announcements=50, distinct=12)
    store.record_transit_bucket(bucket_ts=hour, asn=2856, paths=900)

    body = client.get("/partials/asn/summary?asn=2856").data.decode()

    assert "50" in body           # announcements in window
    assert "900" in body          # transit paths
    assert "United Kingdom" in body or "GB" in body


def test_asn_prefixes_partial_lists_and_links(client):
    body = client.get("/partials/asn/prefixes?asn=15169").data.decode()

    # FakeSources returns 8.8.8.0/24-style data? No — it has no announced
    # prefixes method; the partial must degrade, not crash.
    assert "unavailable" in body.lower() or "prefixes" in body.lower()


def test_asn_partials_reject_bad_asn(client):
    assert client.get("/partials/asn/summary?asn=abc").status_code == 400
    assert client.get("/partials/asn/prefixes?asn=-1").status_code == 400


def test_prefix_page_includes_linx_panel(client):
    body = client.get("/q?query=8.8.8.0/24").data.decode()

    assert "/partials/prefix/linx?prefix=8.8.8.0/24" in body


def test_linx_prefix_partial_groups_by_exchange(client, app):
    class WithLinx(type(app.config["ROUTELENS_SOURCES"])):
        pass

    def linx_lookup(prefix):
        return {"ok": True, "data": {"exchanges": [
            {"group": "LINX Scotland", "routes": [
                {"network": prefix, "rs": "RS1.SCO1 (IPv4)",
                 "member": "Packet Clearing House (PCH)", "asn": 42, "as_path": [42]},
            ]},
        ]}}

    app.config["ROUTELENS_SOURCES"].linx_lookup = linx_lookup

    body = client.get("/partials/prefix/linx?prefix=8.8.8.0/24").data.decode()

    assert "LINX Scotland" in body
    assert "Packet Clearing House" in body
    assert "AS42" in body


def test_linx_prefix_partial_empty_states_bilateral_caveat(client, app):
    app.config["ROUTELENS_SOURCES"].linx_lookup = lambda prefix: {"ok": True, "data": {"exchanges": []}}

    body = client.get("/partials/prefix/linx?prefix=8.8.8.0/24").data.decode()

    assert "route servers" in body
    assert "bilateral" in body


def test_bare_looking_glass_shows_uk_exchange_strip(client):
    body = client.get("/q").data.decode()

    assert "/partials/linx-uk" in body


def test_linx_uk_strip_lists_exchanges_scotland_first(client, app):
    class StripSources:
        def linx_routeservers(self):
            return {"ok": True, "data": {"exchanges": [
                {"group": "LINX LON1", "routeservers": [{"id": "rs1-lon1-v4", "name": "RS1.LON1 (IPv4)"}]},
                {"group": "LINX Scotland", "routeservers": [{"id": "rs1-sco1-v4", "name": "RS1.SCO1 (IPv4)"}]},
            ]}}

        def linx_neighbors(self, rs_id):
            return {"ok": True, "data": {
                "sessions": 30, "sessions_up": 28, "routes_received": 150000,
                "member_asns": [42, 6939],
            }}

    app.config["ROUTELENS_SOURCES"] = StripSources()

    body = client.get("/partials/linx-uk").data.decode()

    assert body.index("LINX Scotland") < body.index("LINX LON1")
    assert "28" in body and "150,000" in body
    # Honest framing: route-server snapshots, not activity.
    assert "route server" in body.lower()
