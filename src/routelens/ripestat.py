from __future__ import annotations

from collections import Counter
import requests


def summarize_bgplay(payload: dict) -> dict:
    data = payload.get("data", payload)
    initial = data.get("initial_state", []) or []
    resource = data.get("resource")
    collectors = {row.get("source_id") for row in initial if row.get("source_id")}
    paths = []
    origins = Counter()
    transit = Counter()
    for row in initial:
        path = tuple(row.get("path") or [])
        if not path:
            continue
        paths.append(path)
        origins[path[-1]] += 1
        for asn in path[1:-1]:
            transit[asn] += 1
    return {
        "resource": resource,
        "collector_count": len(collectors),
        "unique_path_count": len(set(paths)),
        "origins": sorted(origins),
        "origin_counts": origins.most_common(),
        "top_transit_asns": transit.most_common(10),
        "sample_paths": [list(p) for p in list(dict.fromkeys(paths))[:20]],
    }


def fetch_bgplay(resource: str, timeout: int = 20) -> dict:
    url = "https://stat.ripe.net/data/bgplay/data.json"
    response = requests.get(url, params={"resource": resource}, timeout=timeout)
    response.raise_for_status()
    return response.json()
