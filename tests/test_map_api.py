import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from routelens.app import create_app


def _bucket(minutes_ago: int) -> str:
    dt = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _hour_bucket(hours_ago: int) -> str:
    dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})


def test_world_geojson_is_packaged_and_valid():
    path = Path("src/routelens/static/world.geojson")
    data = json.loads(path.read_text())

    iso_codes = {f["properties"]["iso2"] for f in data["features"]}
    assert {"GB", "FR", "US", "BR", "JP"} <= iso_codes
    assert len(data["features"]) > 150


def test_map_collectors_joins_activity_onto_locations(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    for ago in (1, 2):
        store.record_activity_bucket(bucket_ts=_bucket(ago), rrc="rrc01", updates=600, announcements=500, withdrawals=100)
    client = app.test_client()

    payload = client.get("/api/map/collectors?window=3600").get_json()

    rrc01 = next(c for c in payload["collectors"] if c["rrc"] == "rrc01")
    assert rrc01["city"] == "London"
    assert rrc01["updates"] == 1200
    assert rrc01["per_minute"] == 600
    # Collectors with no recorded activity still appear, at zero.
    rrc06 = next(c for c in payload["collectors"] if c["rrc"] == "rrc06")
    assert rrc06["updates"] == 0
    assert len(payload["collectors"]) == 23


def test_map_countries_returns_churn_with_intensity(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(1, "BR One", "BR"), (2, "BR Two", "BR"), (3, "GB One", "GB")])
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=1, updates=100, announcements=120)
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=2, updates=200, announcements=240)
    store.record_asn_bucket(bucket_ts=_hour_bucket(0), asn=3, updates=50, announcements=60)
    client = app.test_client()

    payload = client.get("/api/map/countries?window=21600").get_json()

    br = next(c for c in payload["countries"] if c["country"] == "BR")
    assert br["announcements"] == 360
    assert br["origins"] == 2
    assert br["intensity"] == 180


def test_map_events_combines_origin_changes_and_flaps(tmp_path):
    app = _app(tmp_path)
    store = app.config["ROUTELENS_STORE"]
    store.upsert_asn_names([(64666, "New Net", "TR"), (15169, "Google LLC", "US")])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    store.record_origin_event(observed_at=now, prefix="203.0.113.0/24", old_asn=64500, new_asn=64666)
    store.record_prefix_bucket(
        bucket_ts=_hour_bucket(0), prefix="198.51.100.0/24",
        announcements=40, withdrawals=30, origin_asn=15169,
    )
    client = app.test_client()

    payload = client.get("/api/map/events?window=21600").get_json()

    change = payload["origin_changes"][0]
    assert change["prefix"] == "203.0.113.0/24"
    assert change["country"] == "TR"       # located by the NEW origin
    flap = payload["flaps"][0]
    assert flap["prefix"] == "198.51.100.0/24"
    assert flap["country"] == "US"
    assert flap["flapping"] is True


def test_map_apis_reject_bad_window(tmp_path):
    client = _app(tmp_path).test_client()

    for path in ("/api/map/collectors", "/api/map/countries", "/api/map/events"):
        assert client.get(f"{path}?window=59").status_code == 400
        assert client.get(f"{path}?window=nope").status_code == 400


class FakeLinxSources:
    def linx_routeservers(self):
        return {"ok": True, "data": {"exchanges": [
            {"group": "LINX Scotland", "routeservers": [{"id": "rs1-sco1-v4", "name": "RS1.SCO1 (IPv4)"}]},
            {"group": "LINX LON1", "routeservers": [{"id": "rs1-lon1-v4", "name": "RS1.LON1 (IPv4)"}]},
            {"group": "LINX Nairobi", "routeservers": [{"id": "rs1-nai1-v4", "name": "RS1.NAI1 (IPv4)"}]},
        ]}}

    def linx_neighbors(self, rs_id):
        return {"ok": True, "data": {
            "sessions": 30, "sessions_up": 28, "routes_received": 150000,
            "member_asns": [42, 6939],
        }}


def test_map_linx_returns_uk_sites_with_coords_and_alice_summary(tmp_path):
    app = _app(tmp_path)
    app.config["ROUTELENS_SOURCES"] = FakeLinxSources()
    client = app.test_client()

    payload = client.get("/api/map/linx").get_json()

    sites = payload["sites"]
    # UK LANs only on the map: the international exchanges aren't the UK story.
    assert {s["group"] for s in sites} <= {
        "LINX Scotland", "LINX LON1", "LINX LON2", "LINX Manchester", "LINX Wales"
    }
    sco = next(s for s in sites if s["group"] == "LINX Scotland")
    assert sco["city"] == "Edinburgh"
    assert 55 < sco["lat"] < 57 and -4 < sco["lon"] < -2
    assert sco["sessions_up"] == 28
    assert sco["members"] == 2
    assert sco["routes_received"] == 150000


def test_map_linx_omits_unreachable_exchanges(tmp_path):
    app = _app(tmp_path)

    class Down:
        def linx_routeservers(self):
            return {"ok": False, "error": "alice down"}

    app.config["ROUTELENS_SOURCES"] = Down()

    payload = app.test_client().get("/api/map/linx").get_json()

    assert payload["sites"] == []
