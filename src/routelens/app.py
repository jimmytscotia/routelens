from __future__ import annotations

import os
from pathlib import Path
from flask import Flask, jsonify, render_template, abort, request

from .query import classify_query
from .sources import SourceClient
from .store import RouteLensStore


def _sparkline_points(values: list[int], width: int = 120, height: int = 24) -> str:
    """SVG polyline points for a compact activity sparkline."""
    if len(values) < 2:
        return ""
    peak = max(max(values), 1)
    step = width / (len(values) - 1)
    return " ".join(
        f"{i * step:.1f},{height - (v / peak) * (height - 2) - 1:.1f}" for i, v in enumerate(values)
    )


def _line_chart(series: list, width: int = 560, height: int = 150) -> dict | None:
    """Scaled polyline + axis labels for a server-rendered SVG line chart."""
    if len(series) < 2:
        return None
    values = [v for _, v in series]
    lo, hi = min(values), max(values)
    span = max(hi - lo, 1)
    step = width / (len(series) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - (v - lo) / span * (height - 6) - 3:.1f}"
        for i, (_, v) in enumerate(series)
    )
    return {
        "points": points, "width": width, "height": height,
        "y_min": lo, "y_max": hi,
        "x_first": series[0][0], "x_last": series[-1][0],
    }


def _default_resolver(hostname: str) -> list[str]:
    import dns.resolver

    try:
        answers = dns.resolver.resolve(hostname, "A", lifetime=5)
        return sorted(str(rr) for rr in answers)
    except Exception:
        return []


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.environ.get("ROUTELENS_DATABASE", str(Path(app.instance_path) / "routelens.db")),
        RESOLVER=_default_resolver,
    )
    if config:
        app.config.update(config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    store = RouteLensStore(app.config["DATABASE"])
    store.init_schema()
    store.seed_defaults()
    app.config["ROUTELENS_STORE"] = store
    app.config.setdefault("ROUTELENS_SOURCES", SourceClient(store))

    def sources() -> SourceClient:
        return app.config["ROUTELENS_SOURCES"]

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "service": "routelens"})

    @app.get("/")
    def pulse():
        return render_template("pulse.html")

    @app.get("/api/collectors")
    def api_collectors():
        from .collectors import ACTIVE_COLLECTORS

        return jsonify({"collectors": ACTIVE_COLLECTORS})

    # Watchlist UI removed for now (2026-07-14, Jim's call). The collector,
    # store and resource-detail pages stay; only the listing page is gone.
    @app.get("/resources/<int:resource_id>")
    def resource_detail(resource_id: int):
        resource = store.get_resource(resource_id)
        if not resource:
            abort(404)
        latest = store.latest_checks(resource_id)
        return render_template("resource.html", resource=resource, latest=latest)

    @app.get("/q")
    def query_page():
        raw = request.args.get("query", "")
        result = classify_query(raw)
        context = {"raw": raw, "kind": result["kind"], "value": result["value"]}

        if result["kind"] == "invalid":
            return render_template("query.html", **context)

        if result["kind"] == "asn":
            with_names = store.asn_profile_stats(asn=result["value"], since="1970-01-01T00:00:00")
            context["asn_name"] = with_names["name"]
            context["asn_country"] = with_names["country"]

        if result["kind"] == "hostname":
            ips = app.config["RESOLVER"](result["value"])
            context["resolved_ips"] = ips
            if ips:
                netinfo = sources().ripestat_network_info(ips[0])
                if netinfo["ok"]:
                    context["prefix"] = netinfo["data"].get("prefix")
                    context["asns"] = netinfo["data"].get("asns") or []
        elif result["kind"] == "ip":
            netinfo = sources().ripestat_network_info(result["value"])
            if netinfo["ok"]:
                context["prefix"] = netinfo["data"].get("prefix")
                context["asns"] = netinfo["data"].get("asns") or []
        elif result["kind"] == "prefix":
            context["prefix"] = result["value"]

        return render_template("query.html", **context)

    @app.get("/partials/prefix/lg")
    def partial_prefix_lg():
        prefix = request.args.get("prefix", "")
        return render_template("partials/lg_panel.html", result=sources().ripestat_looking_glass(prefix))

    @app.get("/partials/prefix/routing")
    def partial_prefix_routing():
        prefix = request.args.get("prefix", "")
        routing = sources().ripestat_routing_status(prefix)
        rpki = None
        if routing["ok"] and routing["data"]["origins"]:
            rpki = sources().ripestat_rpki(routing["data"]["origins"][0], prefix)
        return render_template("partials/routing_panel.html", routing=routing, rpki=rpki)

    @app.get("/partials/prefix/routeviews")
    def partial_prefix_routeviews():
        prefix = request.args.get("prefix", "")
        return render_template("partials/routeviews_panel.html", result=sources().routeviews_prefix(prefix))

    @app.get("/partials/prefix/nlnog")
    def partial_prefix_nlnog():
        prefix = request.args.get("prefix", "")
        return render_template("partials/nlnog_panel.html", result=sources().nlnog_prefix(prefix))

    @app.get("/partials/radar")
    def partial_radar():
        return render_template("partials/radar_panel.html", result=sources().radar_events())

    ALLOWED_WINDOWS = {900: "15 min", 3600: "1 hour", 21600: "6 hours", 86400: "24 hours"}

    @app.context_processor
    def inject_dashboards():
        from .dashboards import DASHBOARDS, nav

        return {"dashboards": DASHBOARDS, "sitenav": nav()}

    @app.get("/dashboards/")
    def dashboards_index():
        from flask import redirect

        from .dashboards import first_live_slug

        return redirect(f"/dashboards/{first_live_slug()}")

    @app.get("/dashboards/collectors")
    def dashboard_collectors():
        return render_template("dashboards/collectors.html", windows=ALLOWED_WINDOWS)

    @app.get("/partials/dashboards/collectors")
    def partial_dashboard_collectors():
        from datetime import datetime, timedelta, timezone

        from .collectors import ACTIVE_COLLECTORS

        try:
            window = int(request.args.get("window", "3600"))
        except ValueError:
            abort(400)
        if window not in ALLOWED_WINDOWS:
            abort(400)

        now = datetime.now(timezone.utc)
        since = (now - timedelta(seconds=window)).strftime("%Y-%m-%dT%H:%M:%S")
        league = store.activity_league(since=since)
        meta = {c["rrc"]: c for c in ACTIVE_COLLECTORS}
        spark_since = (now - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = []
        for rank, entry in enumerate(league, start=1):
            info = meta.get(entry["rrc"], {})
            series = store.activity_series(rrc=entry["rrc"], since=spark_since)
            rows.append(
                {
                    **entry,
                    "rank": rank,
                    "city": info.get("city", "?"),
                    "country": info.get("country", ""),
                    "scope": info.get("scope", ""),
                    "per_minute": round(entry["updates"] / max(entry["minutes"], 1)),
                    "spark": _sparkline_points([v for _, v in series]),
                }
            )
        return render_template(
            "partials/collector_league.html",
            rows=rows,
            window=window,
            window_label=ALLOWED_WINDOWS[window],
        )

    ASN_WINDOWS = {3600: "1 hour", 21600: "6 hours", 86400: "24 hours", 604800: "7 days"}

    @app.get("/dashboards/asns")
    def dashboard_asns():
        return render_template("dashboards/asns.html", windows=ASN_WINDOWS)

    @app.get("/partials/dashboards/asns")
    def partial_dashboard_asns():
        from datetime import datetime, timedelta, timezone

        try:
            window = int(request.args.get("window", "21600"))
        except ValueError:
            abort(400)
        if window not in ASN_WINDOWS:
            abort(400)
        since = (datetime.now(timezone.utc) - timedelta(seconds=window)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = store.asn_league(since=since, limit=50)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return render_template(
            "partials/asn_league.html", rows=rows, window_label=ASN_WINDOWS[window]
        )

    FLAP_WINDOWS = {3600: "1 hour", 21600: "6 hours", 86400: "24 hours"}

    @app.get("/dashboards/flaps")
    def dashboard_flaps():
        return render_template("dashboards/flaps.html", windows=FLAP_WINDOWS)

    @app.get("/partials/dashboards/flaps")
    def partial_dashboard_flaps():
        from datetime import datetime, timedelta, timezone

        try:
            window = int(request.args.get("window", "21600"))
        except ValueError:
            abort(400)
        if window not in FLAP_WINDOWS:
            abort(400)
        since = (datetime.now(timezone.utc) - timedelta(seconds=window)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = store.prefix_flap_league(since=since, limit=50)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return render_template(
            "partials/flap_league.html", rows=rows, window_label=FLAP_WINDOWS[window]
        )

    ORIGIN_WINDOWS = {3600: "1 hour", 21600: "6 hours", 86400: "24 hours", 604800: "7 days"}

    @app.get("/dashboards/origin-changes")
    def dashboard_origin_changes():
        return render_template("dashboards/origin_changes.html", windows=ORIGIN_WINDOWS)

    @app.get("/partials/dashboards/origin-changes")
    def partial_dashboard_origin_changes():
        from datetime import datetime, timedelta, timezone

        try:
            window = int(request.args.get("window", "21600"))
        except ValueError:
            abort(400)
        if window not in ORIGIN_WINDOWS:
            abort(400)
        since = (datetime.now(timezone.utc) - timedelta(seconds=window)).strftime("%Y-%m-%dT%H:%M:%S")
        events = store.recent_origin_events(since=since, limit=100)
        # A transition whose reverse pair also appears in the window is a
        # flip-flop (typical MOAS/multihoming), not a one-way move.
        pairs = {(e["prefix"], e["old_asn"], e["new_asn"]) for e in events}
        for e in events:
            e["flipflop"] = e["flips"] > 2 or (e["prefix"], e["new_asn"], e["old_asn"]) in pairs
        return render_template(
            "partials/origin_events.html", events=events, window_label=ORIGIN_WINDOWS[window]
        )

    TRANSIT_WINDOWS = {3600: "1 hour", 21600: "6 hours", 86400: "24 hours"}

    @app.get("/dashboards/transit")
    def dashboard_transit():
        return render_template("dashboards/transit.html", windows=TRANSIT_WINDOWS)

    @app.get("/partials/dashboards/transit")
    def partial_dashboard_transit():
        from datetime import datetime, timedelta, timezone

        try:
            window = int(request.args.get("window", "21600"))
        except ValueError:
            abort(400)
        if window not in TRANSIT_WINDOWS:
            abort(400)
        since = (datetime.now(timezone.utc) - timedelta(seconds=window)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = store.transit_league(since=since, limit=50)
        stats = store.path_stats(since=since)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
            row["share"] = round(100 * row["paths"] / stats["paths"], 1) if stats["paths"] else 0
        return render_template(
            "partials/transit_league.html", rows=rows, stats=stats,
            window_label=TRANSIT_WINDOWS[window],
        )

    COUNTRY_WINDOWS = {3600: "1 hour", 21600: "6 hours", 86400: "24 hours", 604800: "7 days"}

    @app.get("/dashboards/countries")
    def dashboard_countries():
        return render_template("dashboards/countries.html", windows=COUNTRY_WINDOWS)

    @app.get("/partials/dashboards/countries")
    def partial_dashboard_countries():
        from datetime import datetime, timedelta, timezone

        from .countries import country_name, flag_emoji

        try:
            window = int(request.args.get("window", "21600"))
        except ValueError:
            abort(400)
        if window not in COUNTRY_WINDOWS:
            abort(400)
        since = (datetime.now(timezone.utc) - timedelta(seconds=window)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = store.country_league(since=since, limit=50)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
            row["name"] = country_name(row["country"])
            row["flag"] = flag_emoji(row["country"])
            row["intensity"] = round(row["announcements"] / row["origins"]) if row["origins"] else 0
        return render_template(
            "partials/country_league.html", rows=rows, window_label=COUNTRY_WINDOWS[window]
        )

    @app.get("/dashboards/rpki")
    def dashboard_rpki():
        return render_template("dashboards/rpki.html")

    @app.get("/partials/dashboards/rpki")
    def partial_dashboard_rpki():
        from .uk import UK_OPERATORS

        rows = store.list_rpki_scores()
        for row in rows:
            row["coverage"] = round(100 * row["valid"] / row["total"]) if row["total"] else 0
            row["is_uk_set"] = row["asn"] in UK_OPERATORS
        rows.sort(key=lambda r: (-r["coverage"], -r["total"]))
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return render_template("partials/rpki_scoreboard.html", rows=rows)

    @app.get("/partials/dashboards/rpki-global")
    def partial_dashboard_rpki_global():
        return render_template("partials/rpki_global.html", result=sources().radar_route_stats())

    @app.get("/dashboards/table-growth")
    def dashboard_table_growth():
        return render_template("dashboards/table_growth.html")

    @app.get("/partials/dashboards/table-growth")
    def partial_dashboard_table_growth():
        result = sources().table_growth()
        charts = None
        if result["ok"]:
            charts = {
                "v4": _line_chart(result["data"]["v4"]),
                "v6": _line_chart(result["data"]["v6"]),
            }
        return render_template("partials/table_growth.html", result=result, charts=charts)

    @app.get("/dashboards/address-space")
    def dashboard_address_space():
        return render_template("dashboards/address_space.html")

    @app.get("/partials/dashboards/address-space")
    def partial_dashboard_address_space():
        rows = store.address_space_league(limit=50)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return render_template("partials/address_space.html", rows=rows)

    MAP_WINDOWS = {3600, 21600, 86400}

    def _map_since_or_400() -> str:
        from datetime import datetime, timedelta, timezone

        try:
            window = int(request.args.get("window", "21600"))
        except ValueError:
            abort(400)
        if window not in MAP_WINDOWS:
            abort(400)
        return (datetime.now(timezone.utc) - timedelta(seconds=window)).strftime("%Y-%m-%dT%H:%M:%S")

    @app.get("/api/map/collectors")
    def api_map_collectors():
        from .collectors import ACTIVE_COLLECTORS

        since = _map_since_or_400()
        activity = {row["rrc"]: row for row in store.activity_league(since=since)}
        collectors = []
        for c in ACTIVE_COLLECTORS:
            row = activity.get(c["rrc"])
            updates = row["updates"] if row else 0
            minutes = row["minutes"] if row else 0
            collectors.append(
                {**c, "updates": updates, "per_minute": round(updates / minutes) if minutes else 0}
            )
        return jsonify({"collectors": collectors})

    @app.get("/api/map/countries")
    def api_map_countries():
        since = _map_since_or_400()
        countries = store.country_league(since=since, limit=250)
        for row in countries:
            row["intensity"] = round(row["announcements"] / row["origins"]) if row["origins"] else 0
        return jsonify({"countries": countries})

    @app.get("/api/map/events")
    def api_map_events():
        since = _map_since_or_400()
        origin_changes = [
            {
                "prefix": e["prefix"],
                "old_asn": e["old_asn"],
                "new_asn": e["new_asn"],
                "country": e["new_country"],   # locate by where the prefix went
                "flips": e["flips"],
                "last_seen": e["last_seen"],
            }
            for e in store.recent_origin_events(since=since, limit=50)
        ]
        flaps = [
            {
                "prefix": f["prefix"],
                "origin_asn": f["origin_asn"],
                "country": f["origin_country"],
                "events": f["events"],
                "flapping": bool(f["announcements"] and f["withdrawals"]),
            }
            for f in store.prefix_flap_league(since=since, limit=30)
        ]
        return jsonify({"origin_changes": origin_changes, "flaps": flaps})

    def _valid_asn_or_400() -> int:
        raw = request.args.get("asn", "")
        if not raw.isdigit() or not (0 < int(raw) <= 4_294_967_295):
            abort(400)
        return int(raw)

    def _safe(call):
        """Partials must degrade to a labelled gap, never 500."""
        try:
            return call()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/dashboards/asn-profiles")
    def dashboard_asn_profiles():
        from datetime import datetime, timedelta, timezone

        from .uk import UK_OPERATORS

        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        churners = store.asn_league(since=day_ago, limit=10)
        uk = []
        for asn in UK_OPERATORS:
            profile = store.asn_profile_stats(asn=asn, since=day_ago)
            uk.append({"asn": asn, "name": profile["name"]})
        return render_template("dashboards/asn_profiles.html", uk=uk, churners=churners)

    @app.get("/partials/asn/summary")
    def partial_asn_summary():
        from datetime import datetime, timedelta, timezone

        from .countries import country_name

        asn = _valid_asn_or_400()
        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        profile = store.asn_profile_stats(asn=asn, since=day_ago)
        profile["country_name"] = country_name(profile["country"]) if profile["country"] else ""
        profile["spark"] = _sparkline_points([v for _, v in profile["churn_series"]])
        return render_template("partials/asn_summary.html", p=profile)

    @app.get("/partials/asn/prefixes")
    def partial_asn_prefixes():
        asn = _valid_asn_or_400()
        result = _safe(lambda: sources().ripestat_announced_prefixes(asn))
        return render_template("partials/asn_prefixes.html", result=result, asn=asn)

    @app.get("/partials/asn/rpki")
    def partial_asn_rpki():
        asn = _valid_asn_or_400()
        result = _safe(lambda: sources().routeviews_rpki_asn(asn))
        return render_template("partials/asn_rpki.html", result=result, asn=asn)

    @app.get("/partials/asn/peeringdb")
    def partial_asn_peeringdb():
        asn = _valid_asn_or_400()
        result = _safe(lambda: sources().peeringdb_net(asn))
        return render_template("partials/asn_peeringdb.html", result=result, asn=asn)

    @app.post("/api/globalping")
    def api_globalping_create():
        payload = request.get_json(silent=True) or {}
        target = classify_query(payload.get("target", ""))
        if target["kind"] not in ("hostname", "ip"):
            return jsonify({"ok": False, "error": "target must be a hostname or IP"}), 400
        result = sources().globalping_create(str(target["value"]))
        return jsonify(result), 202 if result["ok"] else 502

    @app.get("/api/globalping/<measurement_id>")
    def api_globalping_result(measurement_id: str):
        result = sources().globalping_result(measurement_id)
        return jsonify(result), 200 if result["ok"] else 502

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8097)
