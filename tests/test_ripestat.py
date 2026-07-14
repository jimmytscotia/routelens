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
