from __future__ import annotations

import os
from typing import Any

import requests

from .ripestat import summarize_looking_glass, summarize_routing_status, summarize_rpki
from .store import RouteLensStore

RIPESTAT_BASE = "https://stat.ripe.net/data"
ROUTEVIEWS_BASE = "https://api.routeviews.org/guest"
NLNOG_BASE = "https://lg.ring.nlnog.net/api"
PEERINGDB_BASE = "https://www.peeringdb.com/api"
# LINX's public Alice-LG instance for its route servers. The UK LANs
# (LON1, LON2, Manchester, Scotland, Wales) live here; the separate
# alice-collector host carries LINX's global collectors instead.
LINX_RS_BASE = "https://alice-rs.linx.net/api/v1"
# Outage/hijack feeds for the Internet Weather briefing. IODA and GRIP are
# Georgia Tech research services: free with attribution, academic/educational
# AUP — poll politely, cache aggressively, always credit them in the UI.
IODA_BASE = "https://api.ioda.inetintel.cc.gatech.edu/v2"
GRIP_BASE = "https://api.grip.inetintel.cc.gatech.edu/v1"
GLOBALPING_BASE = "https://api.globalping.io/v1"
RADAR_BASE = "https://api.cloudflare.com/client/v4/radar"

# Polite User-Agent for bulk/courtesy data sources (bgp.tools requires a
# reachable contact). The mailbox is monitored by the admin.
USER_AGENT = "RouteLens/1.0 (https://routelens.nexthop.engineer; noc.nexthop@agentmail.to)"
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


POTAROO_V4 = "https://bgp.potaroo.net/as2.0/bgp-active.txt"
POTAROO_V6 = "https://bgp.potaroo.net/v6/as2.0/bgp-active.txt"


def parse_potaroo(text: str) -> list[tuple[int, int]]:
    """Parse potaroo bgp-active.txt: one 'unix_ts count' pair per line."""
    points = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            points.append((int(parts[0]), int(parts[1])))
    return points


def downsample_series(points: list[tuple[int, int]], *, now_ts: float) -> list[tuple[str, int]]:
    """Compact a decades-long series for charting: daily samples for the last
    year (last value per day), month-start samples before that."""
    from datetime import datetime, timezone

    year_ago = now_ts - 365 * 86400
    daily: dict[str, int] = {}
    monthly: dict[str, int] = {}
    for ts, count in points:
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if ts >= year_ago:
            daily[date] = count
        else:
            monthly.setdefault(date[:8] + "01", count)
    merged = {**monthly, **daily}
    return sorted(merged.items())


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

    def ripestat_announced_prefixes(self, asn: int) -> dict[str, Any]:
        def summarize(payload: dict) -> dict[str, Any]:
            prefixes = [
                p.get("prefix") for p in (payload.get("data", payload).get("prefixes") or [])
                if p.get("prefix")
            ]
            return {"count": len(prefixes), "prefixes": prefixes[:500]}

        return self._ripestat(
            "announced-prefixes",
            {"resource": asn},
            cache_key=f"ripestat:announced:{asn}",
            summarize=summarize,
            max_age=3600,
        )

    def routeviews_rpki_asn(self, asn: int) -> dict[str, Any]:
        return self._cached_get(
            f"routeviews:rpki:{asn}",
            f"{ROUTEVIEWS_BASE}/rpki?asn={asn}",
            max_age_seconds=3600,
            summarize=lambda payload: summarize_rpki_asn(payload, asn),
        )

    def peeringdb_net(self, asn: int) -> dict[str, Any]:
        def summarize(payload: dict) -> dict[str, Any] | None:
            nets = payload.get("data") or []
            if not nets:
                return None
            net = nets[0]
            ix = net.get("netixlan_set") or []
            return {
                "name": net.get("name"),
                "aka": net.get("aka"),
                "website": net.get("website"),
                "traffic": net.get("info_traffic"),
                "type": net.get("info_type"),
                "ix_count": len(ix),
            }

        return self._cached_get(
            f"peeringdb:net:{asn}",
            f"{PEERINGDB_BASE}/net",
            params={"asn": asn, "depth": 2},
            max_age_seconds=86400,
            summarize=summarize,
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

    # ---- LINX Alice-LG ------------------------------------------------------

    def linx_routeservers(self) -> dict[str, Any]:
        """LINX route servers grouped by exchange, UK-first ordering
        preserved from the API's own order."""

        def summarize(payload: dict) -> dict[str, Any]:
            exchanges: dict[str, list] = {}
            for rs in payload.get("routeservers") or []:
                exchanges.setdefault(rs.get("group") or "?", []).append(
                    {"id": rs.get("id"), "name": rs.get("name")}
                )
            return {"exchanges": [{"group": g, "routeservers": rss} for g, rss in exchanges.items()]}

        return self._cached_get(
            "linx:routeservers",
            f"{LINX_RS_BASE}/routeservers",
            max_age_seconds=86400,
            summarize=summarize,
        )

    def linx_neighbors(self, rs_id: str) -> dict[str, Any]:
        """Session summary for one route server: members, state, routes."""

        def summarize(payload: dict) -> dict[str, Any]:
            neighbors = payload.get("neighbors") or payload.get("neighbours") or []
            up = [n for n in neighbors if (n.get("state") or "").startswith("up")]
            return {
                "sessions": len(neighbors),
                "sessions_up": len(up),
                "routes_received": sum(n.get("routes_received") or 0 for n in up),
                "member_asns": sorted({n["asn"] for n in up if n.get("asn")}),
            }

        return self._cached_get(
            f"linx:neighbors:{rs_id}",
            f"{LINX_RS_BASE}/routeservers/{rs_id}/neighbors",
            max_age_seconds=900,
            summarize=summarize,
        )

    def linx_lookup(self, prefix: str) -> dict[str, Any]:
        """How LINX's route servers see a prefix, grouped by exchange.
        Only routes learned via the route servers appear: members peering
        bilaterally are invisible here, so absence is not 'not at LINX'."""
        rs_map: dict[str, str] = {}
        rs_meta = self.linx_routeservers()
        if rs_meta.get("ok"):
            for exchange in rs_meta["data"]["exchanges"]:
                for rs in exchange["routeservers"]:
                    rs_map[rs["id"]] = exchange["group"]

        def summarize(payload: dict) -> dict[str, Any]:
            imported = payload.get("imported") or {}
            routes = imported.get("routes") if isinstance(imported, dict) else imported
            grouped: dict[str, list] = {}
            for route in routes or []:
                rs = route.get("routeserver") or {}
                rs_id = rs.get("id") or route.get("routeserver_id") or ""
                group = rs_map.get(rs_id, rs.get("group") or "LINX")
                neighbor = route.get("neighbor") or route.get("neighbour") or {}
                grouped.setdefault(group, []).append(
                    {
                        "network": route.get("network"),
                        "rs": rs.get("name") or rs_id,
                        "member": neighbor.get("description") or "",
                        "asn": neighbor.get("asn"),
                        "as_path": (route.get("bgp") or {}).get("as_path") or [],
                    }
                )
            return {"exchanges": [{"group": g, "routes": r} for g, r in grouped.items()]}

        return self._cached_get(
            f"linx:lookup:{prefix}",
            f"{LINX_RS_BASE}/lookup/prefix",
            params={"q": prefix},
            max_age_seconds=600,
            summarize=summarize,
        )

    # ---- Company status feeds (health board) --------------------------------

    def company_status(self, feed: dict | None) -> dict[str, Any]:
        """Normalise a company's status feed to a common state vocabulary:
        operational | degraded | outage | unknown. Cached and graceful."""
        if not feed:
            return {"ok": True, "data": {"state": "unknown", "detail": "no public status feed"}}
        ftype, url = feed.get("type"), feed.get("url")

        def summarize_statuspage(payload: dict) -> dict[str, Any]:
            status = payload.get("status") or {}
            indicator = status.get("indicator")
            state = {"none": "operational", "minor": "degraded",
                     "major": "outage", "critical": "outage"}.get(indicator, "unknown")
            return {"state": state, "detail": status.get("description") or ""}

        def summarize_gcp(payload: Any) -> dict[str, Any]:
            incidents = payload if isinstance(payload, list) else []
            ongoing = [i for i in incidents if not i.get("end")]
            if not ongoing:
                return {"state": "operational", "detail": "No active incidents"}
            desc = ongoing[0].get("external_desc") or "Active incident"
            return {"state": "outage", "detail": desc}

        summarizer = {"statuspage": summarize_statuspage, "gcp": summarize_gcp}.get(ftype)
        if summarizer is None:
            return {"ok": True, "data": {"state": "unknown", "detail": "feed not yet supported"}}

        result = self._cached_get(
            f"status:{ftype}:{url}", url, max_age_seconds=600, summarize=summarizer,
        )
        if not result.get("ok"):
            result.setdefault("data", {"state": "unknown", "detail": result.get("error", "unavailable")})
            result["data"].setdefault("state", "unknown")
        return result

    # ---- Outage & hijack feeds (Internet Weather) ---------------------------

    def ioda_alerts(self, *, window_s: int = 21600) -> dict[str, Any]:
        """IODA outage alerts for the trailing window. Keeps 'critical' level
        only — 'normal' alerts are recovery/return-to-baseline signals."""
        import time as _time

        now = int(_time.time())

        def summarize(payload: dict) -> dict[str, Any]:
            alerts = []
            for alert in payload.get("data") or []:
                if alert.get("level") != "critical":
                    continue
                entity = alert.get("entity") or {}
                alerts.append(
                    {
                        "entity_type": entity.get("type"),
                        "entity_code": entity.get("code"),
                        "entity_name": entity.get("name"),
                        "datasource": alert.get("datasource"),
                        "level": alert.get("level"),
                        "time": alert.get("time"),
                        "value": alert.get("value"),
                        "history": alert.get("historyValue"),
                    }
                )
            return {"alerts": alerts}

        # Cache key rounds to 10 minutes so repeat renders share one fetch.
        bucket = now // 600
        return self._cached_get(
            f"ioda:alerts:{window_s}:{bucket}",
            f"{IODA_BASE}/outages/alerts",
            params={"from": now - window_s, "until": now},
            max_age_seconds=600,
            summarize=summarize,
        )

    def grip_events(self, *, event_type: str = "moas", limit: int = 20) -> dict[str, Any]:
        """Recent GRIP BGP-hijack-candidate events with their built-in
        suspicion inference."""

        def summarize(payload: dict) -> dict[str, Any]:
            events = []
            for event in payload.get("data") or []:
                summary = event.get("summary") or {}
                inference = ((summary.get("inference_result") or {}).get("primary_inference")) or {}
                events.append(
                    {
                        "id": event.get("id"),
                        "event_type": event.get("event_type"),
                        "time": event.get("view_ts"),
                        "ases": summary.get("ases") or [],
                        "attackers": summary.get("attackers") or [],
                        "victims": summary.get("victims") or [],
                        "suspicion": inference.get("suspicion_level"),
                        "confidence": inference.get("confidence"),
                        "label": (inference.get("labels") or [None])[0],
                        "explanation": inference.get("explanation") or "",
                    }
                )
            return {"events": events}

        return self._cached_get(
            f"grip:events:{event_type}",
            f"{GRIP_BASE}/json/events",
            params={"length": limit, "event_type": event_type},
            max_age_seconds=600,
            summarize=summarize,
        )

    def radar_outages(self) -> dict[str, Any]:
        """Cloudflare Radar Outage Center annotations (token-gated)."""
        token = os.environ.get("CLOUDFLARE_RADAR_TOKEN")
        if not token:
            return {"ok": False, "unconfigured": True, "error": "CLOUDFLARE_RADAR_TOKEN not set"}

        def summarize(payload: dict) -> dict[str, Any]:
            outages = []
            for ann in (payload.get("result") or {}).get("annotations") or []:
                outage = ann.get("outage") or {}
                outages.append(
                    {
                        "id": ann.get("id"),
                        "description": ann.get("description"),
                        "start": ann.get("startDate"),
                        "end": ann.get("endDate"),
                        "locations": ann.get("locations") or [],
                        "asns": ann.get("asns") or [],
                        "cause": outage.get("outageCause"),
                        "scope": outage.get("outageType"),
                    }
                )
            return {"outages": outages}

        return self._cached_get(
            "radar:outages",
            f"{RADAR_BASE}/annotations/outages",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 25},
            max_age_seconds=900,
            summarize=summarize,
        )

    # ---- Global table growth (potaroo) -------------------------------------

    def table_growth(self, *, now_ts: float | None = None) -> dict[str, Any]:
        """Global routing-table size history, v4 + v6, cached for a day.
        Sourced from Geoff Huston's bgp.potaroo.net (updated daily)."""
        import time as _time

        now = now_ts if now_ts is not None else _time.time()
        cached = self.store.cache_get("table-growth", max_age_seconds=86400)
        if cached is not None:
            return {"ok": True, "data": cached, "cached": True}

        def fetch(url: str) -> list[tuple[int, int]]:
            response = requests.get(url, headers=self._headers(), timeout=90)
            response.raise_for_status()
            return parse_potaroo(response.text)

        try:
            v4_raw = fetch(POTAROO_V4)
            v6_raw = fetch(POTAROO_V6)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not v4_raw or not v6_raw:
            return {"ok": False, "error": "empty series from potaroo"}

        def delta(points: list[tuple[int, int]], seconds: int) -> int:
            cutoff = now - seconds
            past = [c for ts, c in points if ts <= cutoff]
            return points[-1][1] - past[-1] if past else 0

        data = {
            "current_v4": v4_raw[-1][1],
            "current_v6": v6_raw[-1][1],
            "week_delta_v4": delta(v4_raw, 7 * 86400),
            "year_delta_v4": delta(v4_raw, 365 * 86400),
            "week_delta_v6": delta(v6_raw, 7 * 86400),
            "year_delta_v6": delta(v6_raw, 365 * 86400),
            "v4": downsample_series(v4_raw, now_ts=now),
            "v6": downsample_series(v6_raw, now_ts=now),
        }
        self.store.cache_set("table-growth", data)
        return {"ok": True, "data": data, "cached": False}

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
