from __future__ import annotations

import os
from typing import Any

import requests

from .ripestat import summarize_looking_glass, summarize_routing_status, summarize_rpki
from .store import RouteLensStore

RIPESTAT_BASE = "https://stat.ripe.net/data"
ROUTEVIEWS_BASE = "https://api.routeviews.org/guest"
NLNOG_BASE = "https://lg.ring.nlnog.net/api"
GLOBALPING_BASE = "https://api.globalping.io/v1"
RADAR_BASE = "https://api.cloudflare.com/client/v4/radar"

USER_AGENT = "RouteLens/0.2 (NextHop Lab demo; jim-tobin@outlook.com)"
ASN_CSV_URL = "https://bgp.tools/asns.csv"


def parse_asn_csv(text: str) -> list[tuple[int, str, str]]:
    """Parse bgp.tools asns.csv (asn,name,class,cc) into (asn, name, country) rows."""
    import csv
    import io

    rows: list[tuple[int, str, str]] = []
    for record in csv.reader(io.StringIO(text)):
        if len(record) < 2 or not record[0].upper().startswith("AS"):
            continue
        asn_text = record[0][2:]
        if not asn_text.isdigit():
            continue
        country = record[3].strip() if len(record) > 3 else ""
        rows.append((int(asn_text), record[1].strip(), country))
    return rows


def summarize_rpki_asn(payload: dict, asn: int) -> dict[str, int]:
    """Count validity states in a RouteViews /guest/rpki?asn= response.
    States other than valid/invalid (notfound, unknown) mean no covering ROA."""
    entry = payload.get(str(asn)) or {}
    counts = {"total": 0, "valid": 0, "invalid": 0, "notfound": 0}
    for item in entry.get("prefix") or []:
        for state in item.values():
            counts["total"] += 1
            if state == "valid":
                counts["valid"] += 1
            elif state == "invalid":
                counts["invalid"] += 1
            else:
                counts["notfound"] += 1
    return counts


def refresh_rpki_scores(store: RouteLensStore, asns: list[int], *, pace_s: float = 1.5, timeout: int = 30) -> int:
    """Score each ASN's ROA coverage via RouteViews, paced for the guest tier
    (1 req/s). Skips ASNs whose fetch fails; returns how many were scored."""
    import time as _time

    scored = 0
    for asn in asns:
        try:
            response = requests.get(
                f"{ROUTEVIEWS_BASE}/rpki?asn={asn}",
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
            response.raise_for_status()
            counts = summarize_rpki_asn(response.json(), asn)
        except Exception:
            continue
        finally:
            if pace_s:
                _time.sleep(pace_s)
        if counts["total"]:
            store.upsert_rpki_score(asn=asn, **counts)
            scored += 1
    return scored


def refresh_asn_names(store: RouteLensStore, timeout: int = 60) -> int:
    """Fetch the bgp.tools ASN name table and upsert it. Returns rows written.
    bgp.tools asks for a descriptive User-Agent and at most daily fetches."""
    response = requests.get(ASN_CSV_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    rows = parse_asn_csv(response.text)
    if rows:
        store.upsert_asn_names(rows)
    return len(rows)


class SourceClient:
    """Clients for external routing-data APIs, with SQLite-backed caching.

    Every method returns {"ok": True, "data": ...} or {"ok": False, "error": ...}
    so callers (Flask routes, templates) never have to handle exceptions.
    """

    def __init__(self, store: RouteLensStore, timeout: int = 15):
        self.store = store
        self.timeout = timeout

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT}
        if extra:
            headers.update(extra)
        return headers

    def _cached_get(
        self,
        cache_key: str,
        url: str,
        *,
        max_age_seconds: int,
        summarize,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        cached = self.store.cache_get(cache_key, max_age_seconds=max_age_seconds)
        if cached is not None:
            return {"ok": True, "data": cached, "cached": True}
        try:
            response = requests.get(
                url, params=params, headers=self._headers(headers), timeout=self.timeout
            )
            response.raise_for_status()
            data = summarize(response.json())
        except Exception as exc:  # network errors, HTTP errors, bad JSON
            return {"ok": False, "error": str(exc)}
        self.store.cache_set(cache_key, data)
        return {"ok": True, "data": data, "cached": False}

    # ---- RIPEstat ---------------------------------------------------------

    def _ripestat(self, call: str, params: dict, *, cache_key: str, summarize, max_age: int = 120):
        return self._cached_get(
            cache_key,
            f"{RIPESTAT_BASE}/{call}/data.json",
            params={**params, "sourceapp": "routelens"},
            max_age_seconds=max_age,
            summarize=summarize,
        )

    def ripestat_looking_glass(self, prefix: str) -> dict[str, Any]:
        return self._ripestat(
            "looking-glass",
            {"resource": prefix},
            cache_key=f"ripestat:lg:{prefix}",
            summarize=summarize_looking_glass,
        )

    def ripestat_routing_status(self, prefix: str) -> dict[str, Any]:
        return self._ripestat(
            "routing-status",
            {"resource": prefix},
            cache_key=f"ripestat:routing:{prefix}",
            summarize=summarize_routing_status,
        )

    def ripestat_rpki(self, asn: int, prefix: str) -> dict[str, Any]:
        return self._ripestat(
            "rpki-validation",
            {"resource": asn, "prefix": prefix},
            cache_key=f"ripestat:rpki:{asn}:{prefix}",
            summarize=summarize_rpki,
        )

    def ripestat_network_info(self, ip: str) -> dict[str, Any]:
        def summarize(payload: dict) -> dict[str, Any]:
            data = payload.get("data", payload)
            return {
                "asns": [int(a) for a in data.get("asns") or [] if str(a).isdigit()],
                "prefix": data.get("prefix"),
            }

        return self._ripestat(
            "network-info",
            {"resource": ip},
            cache_key=f"ripestat:netinfo:{ip}",
            summarize=summarize,
            max_age=600,
        )

    # ---- RouteViews -----------------------------------------------------

    def routeviews_prefix(self, prefix: str) -> dict[str, Any]:
        return self._cached_get(
            f"routeviews:prefix:{prefix}",
            f"{ROUTEVIEWS_BASE}/prefix/{prefix}",
            max_age_seconds=300,
            summarize=self._summarize_routeviews,
        )

    @staticmethod
    def _summarize_routeviews(payload: list | dict) -> dict[str, Any]:
        entries = payload if isinstance(payload, list) else [payload]
        origins = set()
        collectors = set()
        paths = []
        rpki_state = None
        roa_count = 0
        peer_count = 0
        for entry in entries:
            if entry.get("origin_asn"):
                origins.add(int(entry["origin_asn"]))
            rpki_state = rpki_state or entry.get("rpki_state")
            roa_count += len(entry.get("rpki_roas") or [])
            for peer in entry.get("reporting_peers") or []:
                peer_count += 1
                if peer.get("collector"):
                    collectors.add(peer["collector"])
                path = (peer.get("as_path") or "").split()
                if path and path not in paths:
                    paths.append(path)
        return {
            "origin_asns": sorted(origins),
            "rpki_state": rpki_state,
            "roa_count": roa_count,
            "peer_count": peer_count,
            "collectors": sorted(collectors),
            "sample_paths": paths[:10],
        }

    # ---- NLNOG Ring looking glass ---------------------------------------

    def nlnog_prefix(self, prefix: str) -> dict[str, Any]:
        return self._cached_get(
            f"nlnog:prefix:{prefix}",
            f"{NLNOG_BASE}/prefix",
            params={"q": prefix},
            max_age_seconds=300,
            summarize=self._summarize_nlnog,
        )

    @staticmethod
    def _summarize_nlnog(payload: dict) -> dict[str, Any]:
        routes = []
        origins = set()
        for prefix_routes in (payload.get("routes") or {}).values():
            for route in prefix_routes:
                aspath = route.get("aspath") or []
                if aspath and str(aspath[-1][0]).isdigit():
                    origins.add(int(aspath[-1][0]))
                routes.append(
                    {
                        "peer": route.get("peer"),
                        "aspath": aspath,
                        "rpki": route.get("ovs"),
                        "last_update_at": route.get("last_update_at"),
                    }
                )
        return {
            "prefix": payload.get("prefix"),
            "route_count": len(routes),
            "routes": routes[:25],
            "origins": sorted(origins),
        }

    # ---- Globalping ------------------------------------------------------

    def globalping_create(self, target: str, *, limit: int = 10) -> dict[str, Any]:
        try:
            response = requests.post(
                f"{GLOBALPING_BASE}/measurements",
                json={
                    "type": "ping",
                    "target": target,
                    "limit": limit,
                    "locations": [{"magic": "world"}],
                },
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "data": {"id": payload.get("id"), "probes": payload.get("probesCount")}}

    def globalping_result(self, measurement_id: str) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{GLOBALPING_BASE}/measurements/{measurement_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        probes = []
        for item in payload.get("results") or []:
            probe = item.get("probe") or {}
            probes.append(
                {
                    "city": probe.get("city"),
                    "country": probe.get("country"),
                    "asn": probe.get("asn"),
                    "lat": probe.get("latitude"),
                    "lon": probe.get("longitude"),
                    "stats": (item.get("result") or {}).get("stats") or {},
                }
            )
        return {"ok": True, "data": {"status": payload.get("status"), "probes": probes}}

    # ---- Cloudflare Radar -------------------------------------------------

    def radar_route_stats(self) -> dict[str, Any]:
        """Global routing-table RPKI stats from Cloudflare Radar."""
        token = os.environ.get("CLOUDFLARE_RADAR_TOKEN")
        if not token:
            return {"ok": False, "unconfigured": True, "error": "CLOUDFLARE_RADAR_TOKEN not set"}
        return self._cached_get(
            "radar:route-stats",
            f"{RADAR_BASE}/bgp/routes/stats",
            headers={"Authorization": f"Bearer {token}"},
            max_age_seconds=3600,
            summarize=lambda payload: (payload.get("result") or {}).get("stats") or {},
        )

    def radar_events(self, kind: str = "hijacks") -> dict[str, Any]:
        token = os.environ.get("CLOUDFLARE_RADAR_TOKEN")
        if not token:
            return {"ok": False, "unconfigured": True, "error": "CLOUDFLARE_RADAR_TOKEN not set"}
        return self._cached_get(
            f"radar:{kind}",
            f"{RADAR_BASE}/bgp/{kind}/events",
            params={"per_page": 20, "sortOrder": "DESC"},
            headers={"Authorization": f"Bearer {token}"},
            max_age_seconds=300,
            summarize=lambda payload: {"events": (payload.get("result") or {}).get("events") or []},
        )
