import pytest

from routelens.store import RouteLensStore
from routelens import sources
from routelens.sources import SourceClient


@pytest.fixture
def store(tmp_path):
    s = RouteLensStore(tmp_path / "sources.db")
    s.init_schema()
    return s


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sources.requests.HTTPError(f"HTTP {self.status_code}")


ROUTEVIEWS_PAYLOAD = [
    {
        "prefix": "8.8.8.0/24",
        "origin_asn": 15169,
        "rpki_state": "valid",
        "rpki_roas": [{"prefix": "8.8.8.0/24", "ta": "arin", "asn": 15169, "max_length": 24}],
        "reporting_peers": [
            {"peer_asn": 30844, "collector": "route-views.napafrica", "as_path": "30844 15169"},
            {"peer_asn": 37105, "collector": "route-views.napafrica", "as_path": "37105 15169"},
            {"peer_asn": 64500, "collector": "route-views.linx", "as_path": "64500 3356 15169"},
        ],
    }
]


def test_routeviews_prefix_summarises_and_caches(store, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(ROUTEVIEWS_PAYLOAD)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    client = SourceClient(store)

    result = client.routeviews_prefix("8.8.8.0/24")

    assert result["ok"] is True
    assert result["data"]["origin_asns"] == [15169]
    assert result["data"]["rpki_state"] == "valid"
    assert result["data"]["peer_count"] == 3
    assert result["data"]["collectors"] == ["route-views.linx", "route-views.napafrica"]
    assert ["64500", "3356", "15169"] in result["data"]["sample_paths"]

    # Second call is served from cache: no extra HTTP request.
    again = client.routeviews_prefix("8.8.8.0/24")
    assert again["ok"] is True
    assert len(calls) == 1


NLNOG_PAYLOAD = {
    "prefix": "8.8.8.0/24",
    "routes": {
        "8.8.8.0/24": [
            {
                "aspath": [["51088", "A2B - A2B IP B.V., NL"], ["15169", "GOOGLE - Google LLC, US"]],
                "ovs": "valid",
                "peer": "a2b-ip01",
                "last_update_at": "2026-07-14 07:26:06 UTC",
            },
            {
                "aspath": [["1299", "TWELVE99 Arelion, EU"], ["15169", "GOOGLE - Google LLC, US"]],
                "ovs": "valid",
                "peer": "arelion01",
                "last_update_at": "2026-07-14 06:00:00 UTC",
            },
        ]
    },
}


def test_nlnog_prefix_summarises_routes(store, monkeypatch):
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(NLNOG_PAYLOAD))
    client = SourceClient(store)

    result = client.nlnog_prefix("8.8.8.0/24")

    assert result["ok"] is True
    assert result["data"]["route_count"] == 2
    first = result["data"]["routes"][0]
    assert first["aspath"] == [["51088", "A2B - A2B IP B.V., NL"], ["15169", "GOOGLE - Google LLC, US"]]
    assert first["rpki"] == "valid"
    assert result["data"]["origins"] == [15169]


def test_source_error_is_reported_not_raised(store, monkeypatch):
    def boom(url, **kwargs):
        raise sources.requests.ConnectionError("no route to host")

    monkeypatch.setattr(sources.requests, "get", boom)
    client = SourceClient(store)

    result = client.nlnog_prefix("8.8.8.0/24")

    assert result["ok"] is False
    assert "no route to host" in result["error"]


def test_globalping_create_and_result(store, monkeypatch):
    def fake_post(url, **kwargs):
        assert kwargs["json"]["target"] == "nexthop.engineer"
        return FakeResponse({"id": "meas123", "probesCount": 3}, status=202)

    result_payload = {
        "status": "finished",
        "results": [
            {
                "probe": {"city": "Falkenstein", "country": "DE", "asn": 24940,
                          "latitude": 50.48, "longitude": 12.37},
                "result": {"stats": {"avg": 5.2, "loss": 0}},
            }
        ],
    }
    monkeypatch.setattr(sources.requests, "post", fake_post)
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(result_payload))
    client = SourceClient(store)

    created = client.globalping_create("nexthop.engineer")
    assert created["ok"] is True
    assert created["data"]["id"] == "meas123"

    fetched = client.globalping_result("meas123")
    assert fetched["ok"] is True
    assert fetched["data"]["status"] == "finished"
    probe = fetched["data"]["probes"][0]
    assert probe["city"] == "Falkenstein"
    assert probe["lat"] == 50.48
    assert probe["stats"]["avg"] == 5.2


def test_radar_events_without_token_reports_unconfigured(store, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_RADAR_TOKEN", raising=False)
    client = SourceClient(store)

    result = client.radar_events()

    assert result["ok"] is False
    assert result["unconfigured"] is True


def test_radar_events_with_token_summarises(store, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_RADAR_TOKEN", "test-token")
    payload = {
        "success": True,
        "result": {
            "events": [
                {
                    "id": 1001,
                    "event_type": 1,
                    "prefixes": ["203.0.113.0/24"],
                    "detected_origin_as_descriptions": ["EVIL-AS"],
                    "expected_origin_as_numbers": [64500],
                    "detected_origin_as_numbers": [64666],
                    "max_hijack_ts": "2026-07-14T09:00:00Z",
                    "confidence_score": 8,
                }
            ]
        },
    }
    seen = {}

    def fake_get(url, **kwargs):
        seen["auth"] = kwargs["headers"]["Authorization"]
        return FakeResponse(payload)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    client = SourceClient(store)

    result = client.radar_events()

    assert result["ok"] is True
    assert seen["auth"] == "Bearer test-token"
    assert result["data"]["events"][0]["prefixes"] == ["203.0.113.0/24"]


def test_ripestat_looking_glass_summarises_and_caches(store, monkeypatch):
    payload = {
        "data": {
            "rrcs": [
                {
                    "rrc": "RRC01",
                    "location": "London, United Kingdom",
                    "peers": [{"asn_origin": "15169", "as_path": "3356 15169", "last_updated": "2026-07-14T09:00:00"}],
                }
            ],
            "query_time": "2026-07-14T10:00:00",
        }
    }
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        return FakeResponse(payload)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    client = SourceClient(store)

    result = client.ripestat_looking_glass("8.8.8.0/24")

    assert result["ok"] is True
    assert result["data"]["rrc_count"] == 1
    assert result["data"]["rrcs"][0]["rrc"] == "RRC01"
    # sourceapp identifier is sent, per RIPEstat usage policy.
    assert calls[0][1]["sourceapp"] == "routelens"

    client.ripestat_looking_glass("8.8.8.0/24")
    assert len(calls) == 1


def test_ripestat_routing_status_and_rpki(store, monkeypatch):
    routing_payload = {
        "data": {
            "resource": "8.8.8.0/24",
            "visibility": {"v4": {"ris_peers_seeing": 110, "total_ris_peers": 110}, "v6": {}},
            "origins": [{"origin": 15169}],
        }
    }
    rpki_payload = {"data": {"status": "valid", "validating_roas": [], "prefix": "8.8.8.0/24"}}

    def fake_get(url, **kwargs):
        return FakeResponse(rpki_payload if "rpki-validation" in url else routing_payload)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    client = SourceClient(store)

    routing = client.ripestat_routing_status("8.8.8.0/24")
    rpki = client.ripestat_rpki(15169, "8.8.8.0/24")

    assert routing["data"]["visibility_pct"] == 100
    assert routing["data"]["origins"] == [15169]
    assert rpki["data"]["status"] == "valid"


def test_ripestat_network_info(store, monkeypatch):
    payload = {"data": {"asns": ["15169"], "prefix": "8.8.8.0/24"}}
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(payload))
    client = SourceClient(store)

    result = client.ripestat_network_info("8.8.8.8")

    assert result["data"]["asns"] == [15169]
    assert result["data"]["prefix"] == "8.8.8.0/24"


def test_parse_asn_csv_handles_quoting_and_as_prefix():
    from routelens.sources import parse_asn_csv

    csv_text = (
        "asn,name,class,cc\n"
        "AS2856,British Telecommunications PLC,Transit,GB\n"
        'AS10003,"Ogaki Cable Television Co.,Inc.",Eyeball,JP\n'
        "junk-line-without-asn\n"
    )

    rows = parse_asn_csv(csv_text)

    assert (2856, "British Telecommunications PLC", "GB") in rows
    assert (10003, "Ogaki Cable Television Co.,Inc.", "JP") in rows
    assert len(rows) == 2


def test_summarize_routeviews_rpki_asn_counts_states():
    from routelens.sources import summarize_rpki_asn

    payload = {
        "2856": {
            "timestamp": "2026-07-14T19:00:13.434+00:00",
            "prefix": [
                {"5.35.192.0/21": "valid"},
                {"5.80.0.0/15": "valid"},
                {"192.0.2.0/24": "invalid"},
                {"198.51.100.0/24": "notfound"},
                {"203.0.113.0/24": "unknown"},
            ],
        }
    }

    counts = summarize_rpki_asn(payload, 2856)

    assert counts == {"total": 5, "valid": 2, "invalid": 1, "notfound": 2}


def test_refresh_rpki_scores_fetches_paced_and_upserts(store, monkeypatch):
    from routelens.sources import refresh_rpki_scores

    def fake_get(url, **kwargs):
        assert "rpki" in url
        asn = url.rsplit("=", 1)[-1]
        return FakeResponse({asn: {"prefix": [{"192.0.2.0/24": "valid"}, {"198.51.100.0/24": "invalid"}]}})

    monkeypatch.setattr(sources.requests, "get", fake_get)

    scored = refresh_rpki_scores(store, [2856, 5607], pace_s=0)

    assert scored == 2
    rows = {s["asn"]: s for s in store.list_rpki_scores()}
    assert rows[2856]["valid"] == 1
    assert rows[2856]["invalid"] == 1
    assert rows[5607]["total"] == 2


def test_radar_route_stats_summarises_with_token(store, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_RADAR_TOKEN", "test-token")
    payload = {
        "success": True,
        "result": {
            "stats": {
                "routes_total": 1000000,
                "routes_valid": 540000,
                "routes_invalid": 4000,
                "routes_unknown": 456000,
            }
        },
    }
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(payload))
    client = SourceClient(store)

    result = client.radar_route_stats()

    assert result["ok"] is True
    assert result["data"]["routes_valid"] == 540000


def test_radar_route_stats_unconfigured_without_token(store, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_RADAR_TOKEN", raising=False)
    client = SourceClient(store)

    result = client.radar_route_stats()

    assert result["ok"] is False and result["unconfigured"] is True


def test_parse_potaroo_series():
    from routelens.sources import parse_potaroo

    text = "583682400 173\n586360800 217\nnot a line\n1784048471 1064513\n"

    points = parse_potaroo(text)

    assert points[0] == (583682400, 173)
    assert points[-1] == (1784048471, 1064513)
    assert len(points) == 3


def test_downsample_series_daily_recent_monthly_history():
    from routelens.sources import downsample_series

    day = 86400
    now = 1784048471
    points = []
    # Two years of hourly-ish samples.
    t = now - 2 * 365 * day
    while t <= now:
        points.append((t, (t // 3600) % 100000))
        t += 6 * 3600

    series = downsample_series(points, now_ts=now)

    dates = [d for d, _ in series]
    # Ordered, unique dates.
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
    # Recent dates are daily; older dates are month-starts only.
    assert sum(1 for d in dates if d >= "2026-07-01") >= 10
    old = [d for d in dates if d < "2025-07-01"]
    assert old and all(d.endswith("-01") for d in old)


def test_table_growth_fetches_both_families_and_caches(store, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        base = 1784048471
        if "/v6/" in url:
            return FakeResponse(None) if False else type("R", (), {
                "status_code": 200, "text": f"{base - 86400} 250000\n{base} 256115\n",
                "raise_for_status": lambda self: None, "json": lambda self: None,
            })()
        return type("R", (), {
            "status_code": 200, "text": f"{base - 86400} 1060000\n{base} 1064633\n",
            "raise_for_status": lambda self: None, "json": lambda self: None,
        })()

    monkeypatch.setattr(sources.requests, "get", fake_get)
    client = SourceClient(store)

    result = client.table_growth(now_ts=1784048471)

    assert result["ok"] is True
    assert result["data"]["current_v4"] == 1064633
    assert result["data"]["current_v6"] == 256115
    assert result["data"]["v4"][-1][1] == 1064633
    assert len(calls) == 2

    again = client.table_growth(now_ts=1784048471)
    assert again["ok"] is True
    assert len(calls) == 2  # served from cache


def test_ripestat_announced_prefixes_summarises_and_caches(store, monkeypatch):
    payload = {"data": {"prefixes": [{"prefix": "5.80.0.0/15"}, {"prefix": "2a00:2380::/25"}]}}
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(payload)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    client = SourceClient(store)

    result = client.ripestat_announced_prefixes(2856)

    assert result["ok"] is True
    assert result["data"]["count"] == 2
    assert "5.80.0.0/15" in result["data"]["prefixes"]

    client.ripestat_announced_prefixes(2856)
    assert len(calls) == 1


def test_routeviews_rpki_asn_client_summarises(store, monkeypatch):
    payload = {"2856": {"prefix": [{"5.80.0.0/15": "valid"}, {"192.0.2.0/24": "notfound"}]}}
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(payload))
    client = SourceClient(store)

    result = client.routeviews_rpki_asn(2856)

    assert result["ok"] is True
    assert result["data"] == {"total": 2, "valid": 1, "invalid": 0, "notfound": 1}


def test_peeringdb_net_summarises(store, monkeypatch):
    payload = {
        "data": [
            {
                "name": "BT",
                "aka": "British Telecom",
                "website": "https://www.bt.com",
                "info_traffic": "1-5Tbps",
                "info_type": "NSP",
                "netixlan_set": [{"ix_id": 18}, {"ix_id": 31}, {"ix_id": 18}],
            }
        ]
    }
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(payload))
    client = SourceClient(store)

    result = client.peeringdb_net(2856)

    assert result["ok"] is True
    assert result["data"]["name"] == "BT"
    assert result["data"]["traffic"] == "1-5Tbps"
    assert result["data"]["ix_count"] == 3


def test_peeringdb_net_absent_network(store, monkeypatch):
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse({"data": []}))
    client = SourceClient(store)

    result = client.peeringdb_net(64500)

    assert result["ok"] is True
    assert result["data"] is None


LINX_ROUTESERVERS = {
    "routeservers": [
        {"id": "rs1-sco1-v4", "name": "RS1.SCO1 (IPv4)", "group": "LINX Scotland"},
        {"id": "rs2-sco1-v4", "name": "RS2.SCO1 (IPv4)", "group": "LINX Scotland"},
        {"id": "rs1-lon1-v4", "name": "RS1.LON1 (IPv4)", "group": "LINX LON1"},
    ]
}


def test_linx_routeservers_groups_by_exchange(store, monkeypatch):
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(LINX_ROUTESERVERS))
    client = SourceClient(store)

    result = client.linx_routeservers()

    assert result["ok"] is True
    exchanges = result["data"]["exchanges"]
    sco = next(e for e in exchanges if e["group"] == "LINX Scotland")
    assert [rs["id"] for rs in sco["routeservers"]] == ["rs1-sco1-v4", "rs2-sco1-v4"]


def test_linx_neighbors_summarises_sessions(store, monkeypatch):
    payload = {
        "neighbors": [
            {"asn": 42, "description": "Packet Clearing House (PCH)", "state": "up", "routes_received": 33},
            {"asn": 6939, "description": "Hurricane Electric", "state": "up", "routes_received": 100479},
            {"asn": 64500, "description": "Down Member", "state": "down", "routes_received": 0},
        ]
    }
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(payload))
    client = SourceClient(store)

    result = client.linx_neighbors("rs1-sco1-v4")

    assert result["ok"] is True
    assert result["data"]["sessions"] == 3
    assert result["data"]["sessions_up"] == 2
    assert result["data"]["routes_received"] == 100512
    assert 6939 in result["data"]["member_asns"]
    assert 64500 not in result["data"]["member_asns"]  # down sessions aren't members present


def test_linx_lookup_groups_routes_by_exchange(store, monkeypatch):
    def fake_get(url, **kwargs):
        if url.endswith("/routeservers"):
            return FakeResponse(LINX_ROUTESERVERS)
        return FakeResponse({
            "imported": {
                "routes": [
                    {
                        "network": "114.69.222.0/24",
                        "routeserver": {"id": "rs1-sco1-v4", "name": "RS1.SCO1 (IPv4)"},
                        "neighbor": {"asn": 42, "description": "Packet Clearing House (PCH)"},
                        "bgp": {"as_path": [42]},
                    },
                    {
                        "network": "114.69.222.0/24",
                        "routeserver": {"id": "rs1-lon1-v4", "name": "RS1.LON1 (IPv4)"},
                        "neighbor": {"asn": 42, "description": "Packet Clearing House (PCH)"},
                        "bgp": {"as_path": [42]},
                    },
                ]
            }
        })

    monkeypatch.setattr(sources.requests, "get", fake_get)
    client = SourceClient(store)

    result = client.linx_lookup("114.69.222.0/24")

    assert result["ok"] is True
    groups = result["data"]["exchanges"]
    assert [g["group"] for g in groups] == ["LINX Scotland", "LINX LON1"]
    sco = groups[0]
    assert sco["routes"][0]["member"] == "Packet Clearing House (PCH)"
    assert sco["routes"][0]["asn"] == 42
    assert sco["routes"][0]["as_path"] == [42]


def test_linx_lookup_empty_is_ok_not_error(store, monkeypatch):
    def fake_get(url, **kwargs):
        if url.endswith("/routeservers"):
            return FakeResponse(LINX_ROUTESERVERS)
        return FakeResponse({"imported": {"routes": []}})

    monkeypatch.setattr(sources.requests, "get", fake_get)
    client = SourceClient(store)

    result = client.linx_lookup("8.8.8.0/24")

    assert result["ok"] is True
    assert result["data"]["exchanges"] == []


IODA_PAYLOAD = {
    "data": [
        {
            "datasource": "bgp",
            "entity": {"code": "200899", "name": "AS200899 (INTERSPACE-EUROPE)", "type": "asn",
                       "attrs": {"org": "INTERSPACE DOOEL Skopje", "ip_count": "7168"}},
            "time": 1784176200, "level": "critical", "condition": "< 0.99",
            "value": 28, "historyValue": 36, "method": "median",
        },
        {
            "datasource": "merit-nt",
            "entity": {"code": "SD", "name": "Sudan", "type": "country", "attrs": {}},
            "time": 1784176800, "level": "critical", "condition": "< 0.99",
            "value": 10, "historyValue": 55, "method": "median",
        },
        {
            "datasource": "bgp",
            "entity": {"code": "GB", "name": "United Kingdom", "type": "country", "attrs": {}},
            "time": 1784176900, "level": "normal", "condition": ">= 0.99",
            "value": 100, "historyValue": 100, "method": "median",
        },
    ]
}


def test_ioda_alerts_keeps_critical_only_and_caches(store, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(IODA_PAYLOAD)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    client = SourceClient(store)

    result = client.ioda_alerts()

    assert result["ok"] is True
    alerts = result["data"]["alerts"]
    # 'normal' level alerts are recovery signals, not outages: dropped.
    assert len(alerts) == 2
    sudan = next(a for a in alerts if a["entity_code"] == "SD")
    assert sudan["entity_type"] == "country"
    assert sudan["entity_name"] == "Sudan"
    assert sudan["datasource"] == "merit-nt"
    assert sudan["level"] == "critical"
    # Drop ratio conveys severity: value vs historical baseline.
    assert sudan["value"] == 10 and sudan["history"] == 55

    client.ioda_alerts()
    assert len(calls) == 1  # cached


GRIP_PAYLOAD = {
    "data": [
        {
            "id": "moas-1784195700-393636_394233",
            "event_type": "moas",
            "view_ts": 1784195700,
            "summary": {
                "ases": ["393636", "394233"],
                "attackers": ["394233"],
                "victims": ["393636"],
                "inference_result": {
                    "primary_inference": {
                        "confidence": 92,
                        "explanation": "all newcomers are providers",
                        "labels": ["legitimate"],
                        "suspicion_level": 10,
                    }
                },
            },
        },
        {
            "id": "moas-1784195800-64500_64666",
            "event_type": "moas",
            "view_ts": 1784195800,
            "summary": {
                "ases": ["64500", "64666"],
                "attackers": ["64666"],
                "victims": ["64500"],
                "inference_result": {
                    "primary_inference": {
                        "confidence": 80,
                        "explanation": "newcomer announces victim prefix",
                        "labels": ["suspicious"],
                        "suspicion_level": 80,
                    }
                },
            },
        },
    ]
}


def test_grip_events_summarises_with_suspicion(store, monkeypatch):
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(GRIP_PAYLOAD))
    client = SourceClient(store)

    result = client.grip_events()

    assert result["ok"] is True
    events = result["data"]["events"]
    assert len(events) == 2
    sus = events[1]
    assert sus["id"] == "moas-1784195800-64500_64666"
    assert sus["suspicion"] == 80
    assert sus["label"] == "suspicious"
    assert sus["attackers"] == ["64666"]
    assert sus["victims"] == ["64500"]
    assert "newcomer" in sus["explanation"]


def test_radar_outages_token_gated(store, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_RADAR_TOKEN", raising=False)
    client = SourceClient(store)
    assert client.radar_outages()["unconfigured"] is True

    monkeypatch.setenv("CLOUDFLARE_RADAR_TOKEN", "test-token")
    payload = {
        "success": True,
        "result": {
            "annotations": [
                {
                    "id": "out-1", "dataSource": "ALL", "eventType": "OUTAGE",
                    "startDate": "2026-07-16T08:00:00Z", "endDate": None,
                    "description": "Nationwide outage in Sudan",
                    "locations": ["SD"], "asns": [36998],
                    "outage": {"outageCause": "POWER_OUTAGE", "outageType": "NATIONWIDE"},
                }
            ]
        },
    }
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: FakeResponse(payload))

    result = client.radar_outages()

    assert result["ok"] is True
    out = result["data"]["outages"][0]
    assert out["locations"] == ["SD"]
    assert out["cause"] == "POWER_OUTAGE"
    assert out["scope"] == "NATIONWIDE"
