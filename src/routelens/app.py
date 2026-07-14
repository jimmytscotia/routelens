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
