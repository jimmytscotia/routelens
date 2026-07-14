from __future__ import annotations

import os
from pathlib import Path
from flask import Flask, jsonify, render_template, abort

from .store import RouteLensStore


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.environ.get("ROUTELENS_DATABASE", str(Path(app.instance_path) / "routelens.db")),
    )
    if config:
        app.config.update(config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    store = RouteLensStore(app.config["DATABASE"])
    store.init_schema()
    store.seed_defaults()
    app.config["ROUTELENS_STORE"] = store

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "service": "routelens"})

    @app.get("/")
    def dashboard():
        resources = store.list_resources(enabled_only=True)
        cards = []
        counts = {"healthy": 0, "warning": 0, "critical": 0, "unknown": 0}
        total_checks = 0
        for resource in resources:
            latest = store.latest_checks(resource["id"])
            statuses = [check["status"] for check in latest.values()]
            if not statuses:
                rollup = "unknown"
            elif "critical" in statuses:
                rollup = "critical"
            elif "warning" in statuses:
                rollup = "warning"
            else:
                rollup = "healthy"
            counts[rollup] += 1
            total_checks += len(latest)
            cards.append({"resource": resource, "latest": latest, "rollup": rollup})
        return render_template("dashboard.html", cards=cards, counts=counts, total_checks=total_checks)

    @app.get("/resources/<int:resource_id>")
    def resource_detail(resource_id: int):
        resource = store.get_resource(resource_id)
        if not resource:
            abort(404)
        latest = store.latest_checks(resource_id)
        return render_template("resource.html", resource=resource, latest=latest)

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8097)
