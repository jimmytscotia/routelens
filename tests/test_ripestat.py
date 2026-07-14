from routelens.ripestat import summarize_bgplay


def test_summarize_bgplay_extracts_origin_paths_and_collectors():
    payload = {
        "data": {
            "resource": "8.8.8.0/24",
            "initial_state": [
                {"source_id": "rrc00-peer1", "path": [64500, 3356, 15169]},
                {"source_id": "rrc01-peer2", "path": [64501, 1299, 15169]},
                {"source_id": "rrc02-peer3", "path": [64502, 1299, 15169]},
            ],
            "nodes": [{"as_number": 15169, "owner": "GOOGLE"}],
        }
    }

    summary = summarize_bgplay(payload)

    assert summary["resource"] == "8.8.8.0/24"
    assert summary["collector_count"] == 3
    assert summary["unique_path_count"] == 3
    assert summary["origins"] == [15169]
    assert summary["top_transit_asns"][0][0] == 1299


def _looking_glass_payload():
    return {
        "data": {
            "rrcs": [
                {
                    "rrc": "RRC01",
                    "location": "London, United Kingdom",
                    "scope": "LINX / LONAP",
                    "peers": [
                        {
                            "asn_origin": "15169",
                            "as_path": "15692 15169",
                            "prefix": "8.8.8.0/24",
                            "peer": "5.57.80.113",
                            "last_updated": "2026-06-23T19:50:36.490000",
                        },
                        {
                            "asn_origin": "15169",
                            "as_path": "3356 15169",
                            "prefix": "8.8.8.0/24",
                            "peer": "5.57.80.114",
                            "last_updated": "2026-07-01T00:00:00",
                        },
                    ],
                },
                {
                    "rrc": "RRC03",
                    "location": "Amsterdam, Netherlands",
                    "scope": "AMS-IX / NL-IX",
                    "peers": [
                        {
                            "asn_origin": "64500",
                            "as_path": "1299 64500",
                            "prefix": "8.8.8.0/24",
                            "peer": "80.249.208.1",
                            "last_updated": "2026-07-10T12:00:00",
                        }
                    ],
                },
            ],
            "query_time": "2026-07-14T10:00:00",
        }
    }


def test_summarize_looking_glass_aggregates_per_collector():
    from routelens.ripestat import summarize_looking_glass

    summary = summarize_looking_glass(_looking_glass_payload())

    assert summary["rrc_count"] == 2
    assert summary["peer_count"] == 3
    assert summary["origins"] == [15169, 64500]
    first = summary["rrcs"][0]
    assert first["rrc"] == "RRC01"
    assert first["location"] == "London, United Kingdom"
    assert first["peer_count"] == 2
    assert first["origins"] == [15169]
    assert ["15692", "15169"] in first["sample_paths"]


def test_summarize_routing_status_extracts_visibility_and_origins():
    from routelens.ripestat import summarize_routing_status

    payload = {
        "data": {
            "resource": "8.8.8.0/24",
            "first_seen": {"prefix": "8.8.8.0/24", "origin": "21284", "time": "2002-11-06T16:00:00"},
            "last_seen": {"prefix": "8.8.8.0/24", "origin": "15169", "time": "2026-07-14T08:00:00"},
            "visibility": {
                "v4": {"ris_peers_seeing": 108, "total_ris_peers": 110},
                "v6": {"ris_peers_seeing": 0, "total_ris_peers": 0},
            },
            "origins": [{"origin": 15169, "route_objects": ["RADB"]}],
            "less_specifics": [{"prefix": "8.0.0.0/9", "origin": 3356}],
            "more_specifics": [],
        }
    }

    summary = summarize_routing_status(payload)

    assert summary["visibility_seeing"] == 108
    assert summary["visibility_total"] == 110
    assert summary["visibility_pct"] == 98
    assert summary["origins"] == [15169]
    assert summary["first_seen"]["time"] == "2002-11-06T16:00:00"
    assert summary["less_specific_count"] == 1
    assert summary["more_specific_count"] == 0


def test_summarize_rpki_reports_status_and_roas():
    from routelens.ripestat import summarize_rpki

    payload = {
        "data": {
            "resource": "15169",
            "prefix": "8.8.8.0/24",
            "status": "valid",
            "validator": "routinator",
            "validating_roas": [
                {"origin": "15169", "prefix": "8.8.8.0/24", "validity": "valid", "max_length": 24}
            ],
        }
    }

    summary = summarize_rpki(payload)

    assert summary["status"] == "valid"
    assert summary["roa_count"] == 1
    assert summary["roas"][0]["origin"] == 15169
