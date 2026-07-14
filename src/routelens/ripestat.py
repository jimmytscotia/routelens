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


def summarize_looking_glass(payload: dict) -> dict:
    """Aggregate the RIPEstat looking-glass response into per-RRC rows."""
    data = payload.get("data", payload)
    rrcs = []
    all_origins = set()
    peer_total = 0
    for rrc in data.get("rrcs") or []:
        peers = rrc.get("peers") or []
        peer_total += len(peers)
        origins = set()
        paths = []
        for peer in peers:
            origin = peer.get("asn_origin")
            if origin and str(origin).isdigit():
                origins.add(int(origin))
            path = (peer.get("as_path") or "").split()
            if path and path not in paths:
                paths.append(path)
        all_origins.update(origins)
        rrcs.append(
            {
                "rrc": rrc.get("rrc"),
                "location": rrc.get("location"),
                "scope": rrc.get("scope"),
                "peer_count": len(peers),
                "origins": sorted(origins),
                "sample_paths": paths[:5],
                "last_updated": max((p.get("last_updated") or "" for p in peers), default=None),
            }
        )
    return {
        "rrc_count": len(rrcs),
        "peer_count": peer_total,
        "origins": sorted(all_origins),
        "rrcs": rrcs,
        "query_time": data.get("query_time"),
    }


def summarize_routing_status(payload: dict) -> dict:
    data = payload.get("data", payload)
    v4 = (data.get("visibility") or {}).get("v4") or {}
    v6 = (data.get("visibility") or {}).get("v6") or {}
    seeing = int(v4.get("ris_peers_seeing") or 0) + int(v6.get("ris_peers_seeing") or 0)
    total = int(v4.get("total_ris_peers") or 0) + int(v6.get("total_ris_peers") or 0)
    return {
        "resource": data.get("resource"),
        "visibility_seeing": seeing,
        "visibility_total": total,
        "visibility_pct": round(100 * seeing / total) if total else 0,
        "origins": [int(o["origin"]) for o in data.get("origins") or [] if str(o.get("origin", "")).isdigit()],
        "first_seen": data.get("first_seen"),
        "last_seen": data.get("last_seen"),
        "less_specific_count": len(data.get("less_specifics") or []),
        "more_specific_count": len(data.get("more_specifics") or []),
    }


def summarize_rpki(payload: dict) -> dict:
    data = payload.get("data", payload)
    roas = []
    for roa in data.get("validating_roas") or []:
        item = dict(roa)
        if str(item.get("origin", "")).isdigit():
            item["origin"] = int(item["origin"])
        roas.append(item)
    return {
        "resource": data.get("resource"),
        "prefix": data.get("prefix"),
        "status": data.get("status"),
        "validator": data.get("validator"),
        "roa_count": len(roas),
        "roas": roas,
    }


RIPESTAT_BASE = "https://stat.ripe.net/data"
SOURCEAPP = "routelens"


def fetch_data_call(call: str, params: dict, timeout: int = 20) -> dict:
    """Fetch any RIPEstat data call with the sourceapp identifier attached."""
    url = f"{RIPESTAT_BASE}/{call}/data.json"
    response = requests.get(url, params={**params, "sourceapp": SOURCEAPP}, timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_bgplay(resource: str, timeout: int = 20) -> dict:
    return fetch_data_call("bgplay", {"resource": resource}, timeout=timeout)
