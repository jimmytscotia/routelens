"""Internet Weather: anomaly pre-filter for the AI briefing.

Statistical screening over RouteLens' own aggregated telemetry. Runs before
any AI call — the model only ever sees things this filter judged interesting,
which keeps the briefing grounded and the token spend near zero. Pure reads;
no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .store import RouteLensStore

SEVERITIES = ("calm", "minor", "notable", "severe")
# GRIP events below this suspicion score are routine multihoming, not weather.
GRIP_SUSPICION_MIN = 40

# A collector counts as spiking when its last hour exceeds SPIKE_RATIO x its
# trailing per-hour baseline and clears an absolute floor (tiny collectors
# tripling from 3 to 9 updates is noise, not weather).
SPIKE_RATIO = 5.0
SPIKE_MIN_UPDATES = 1000
# A country is a hotspot when its churn intensity exceeds HOTSPOT_RATIO x the
# median intensity across active countries.
HOTSPOT_RATIO = 5.0
HOTSPOT_MIN_INTENSITY = 500


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def render_markdown(md: str) -> str:
    """Minimal, safe markdown → HTML for AI-generated briefing bodies.
    HTML is escaped FIRST, so the only tags in the output are ones we add —
    a model emitting <script> renders as inert text. Supports ##/### headings,
    **bold**, *italic*, `code`, and - bullet lists."""
    import html
    import re

    def inline(text: str) -> str:
        text = html.escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
        return text

    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    bullets: list[str] = []

    def flush_para():
        if para:
            out.append("<p>" + " ".join(para) + "</p>")
            para.clear()

    def flush_bullets():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_para(); flush_bullets(); continue
        if stripped.startswith("### "):
            flush_para(); flush_bullets(); out.append(f"<h4>{inline(stripped[4:])}</h4>")
        elif stripped.startswith("## "):
            flush_para(); flush_bullets(); out.append(f"<h3>{inline(stripped[3:])}</h3>")
        elif stripped[:2] in ("- ", "* "):
            flush_para(); bullets.append(inline(stripped[2:]))
        else:
            flush_bullets(); para.append(inline(stripped))
    flush_para(); flush_bullets()
    return "\n".join(out)


def detect_anomalies(store: RouteLensStore, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    hour_ago = _iso(now - timedelta(hours=1))
    baseline_start = _iso(now - timedelta(hours=7))
    six_hours_ago = _iso(now - timedelta(hours=6))

    # Collector spikes: last hour vs the previous six hours' hourly average.
    recent = {row["rrc"]: row for row in store.activity_league(since=hour_ago)}
    full = {row["rrc"]: row for row in store.activity_league(since=baseline_start)}
    spikes = []
    for rrc, row in recent.items():
        last_hour = row["updates"]
        baseline_total = full.get(rrc, {}).get("updates", 0) - last_hour
        baseline_hourly = baseline_total / 6 if baseline_total > 0 else 0
        if baseline_hourly <= 0 or last_hour < SPIKE_MIN_UPDATES:
            continue
        ratio = last_hour / baseline_hourly
        if ratio >= SPIKE_RATIO:
            spikes.append({"rrc": rrc, "last_hour": last_hour,
                           "hourly_baseline": round(baseline_hourly), "ratio": round(ratio, 1)})
    spikes.sort(key=lambda s: -s["ratio"])

    # Country hotspots: intensity outliers vs the median active country.
    countries = store.country_league(since=six_hours_ago, limit=250)
    for row in countries:
        row["intensity"] = round(row["announcements"] / row["origins"]) if row["origins"] else 0
    intensities = sorted(row["intensity"] for row in countries if row["intensity"])
    hotspots = []
    if intensities:
        median = intensities[len(intensities) // 2]
        floor = max(HOTSPOT_MIN_INTENSITY, median * HOTSPOT_RATIO)
        hotspots = [
            {"country": row["country"], "intensity": row["intensity"],
             "announcements": row["announcements"], "origins": row["origins"]}
            for row in countries if row["intensity"] >= floor
        ]
        hotspots.sort(key=lambda h: -h["intensity"])

    # Churn surges: the noisiest origins right now, for context.
    churners = store.asn_league(since=hour_ago, limit=5)

    # Flap leaders and confirmed origin changes over the report window.
    flaps = [
        {"prefix": row["prefix"], "events": row["events"],
         "origin_asn": row["origin_asn"],
         "flapping": bool(row["announcements"] and row["withdrawals"])}
        for row in store.prefix_flap_league(since=six_hours_ago, limit=5)
    ]
    events = store.recent_origin_events(since=six_hours_ago, limit=10)
    origin_changes = {
        "count": len(events),
        "recent": [
            {"prefix": e["prefix"], "old_asn": e["old_asn"], "new_asn": e["new_asn"],
             "flips": e["flips"], "last_seen": e["last_seen"]}
            for e in events[:5]
        ],
    }

    return {
        "window_hours": 6,
        "generated_at": _iso(now),
        "collector_spikes": spikes,
        "country_hotspots": hotspots,
        "top_churners": [
            {"asn": row["asn"], "name": row["name"], "announcements": row["announcements"]}
            for row in churners
        ],
        "flap_leaders": flaps,
        "origin_changes": origin_changes,
    }


def build_evidence(store: RouteLensStore, sources: Any) -> dict[str, Any]:
    """Assemble everything the briefing model sees: our own anomalies plus
    the external outage/hijack feeds, each degrading to empty on failure."""
    ioda = sources.ioda_alerts()
    grip = sources.grip_events()
    radar = sources.radar_outages()
    grip_events = grip["data"]["events"] if grip.get("ok") else []
    return {
        "internal": detect_anomalies(store),
        "ioda": ioda["data"]["alerts"] if ioda.get("ok") else [],
        "grip": [e for e in grip_events if (e.get("suspicion") or 0) >= GRIP_SUSPICION_MIN],
        "radar_outages": radar["data"]["outages"] if radar.get("ok") else [],
    }


def generate_weather_report(store: RouteLensStore, sources: Any, ai: Any) -> dict[str, Any] | None:
    """Build evidence, ask the model for a briefing, persist it. Returns None
    (a no-op) when no AI client is configured, so the app degrades gracefully."""
    if ai is None:
        return None
    evidence = build_evidence(store, sources)
    result = ai.summarize(evidence)
    severity = result.get("severity")
    if severity not in SEVERITIES:
        severity = "notable"  # unknown severity from the model: don't trust "calm"
    report = {
        "headline": (result.get("headline") or "Internet weather").strip(),
        "severity": severity,
        "body_md": result.get("body_md") or "",
    }
    store.save_weather_report(
        period_hours=6, evidence=evidence,
        model=getattr(ai, "model", ""), **report,
    )
    return report


def build_view(evidence: dict[str, Any]) -> dict[str, Any]:
    """Turn a stored report's evidence JSON into render-ready structures for
    the visual Weather page: stat tiles, scaled bars, merged outages, and a
    map payload. Pure — all numbers come straight from the evidence."""
    from .countries import country_name, flag_emoji

    internal = evidence.get("internal") or {}
    hotspots_raw = internal.get("country_hotspots") or []
    churners_raw = internal.get("top_churners") or []
    flaps_raw = internal.get("flap_leaders") or []
    spikes = internal.get("collector_spikes") or []
    origin = internal.get("origin_changes") or {"count": 0, "recent": []}
    grip = evidence.get("grip") or []

    # Merge IODA country alerts + Radar outages into one per-country list.
    outages: dict[str, dict] = {}
    asn_alerts = 0
    for alert in evidence.get("ioda") or []:
        if alert.get("entity_type") == "country" and alert.get("entity_code"):
            cc = alert["entity_code"]
            entry = outages.setdefault(cc, {"country": cc, "name": country_name(cc),
                                            "flag": flag_emoji(cc), "sources": [], "causes": []})
            if "IODA" not in entry["sources"]:
                entry["sources"].append("IODA")
        elif alert.get("entity_type") == "asn":
            asn_alerts += 1
    for out in evidence.get("radar_outages") or []:
        for cc in out.get("locations") or []:
            entry = outages.setdefault(cc, {"country": cc, "name": country_name(cc),
                                            "flag": flag_emoji(cc), "sources": [], "causes": []})
            if "Cloudflare Radar" not in entry["sources"]:
                entry["sources"].append("Cloudflare Radar")
            if out.get("cause") and out["cause"] not in entry["causes"]:
                entry["causes"].append(out["cause"])

    peak_intensity = max((h.get("intensity", 0) for h in hotspots_raw), default=0)
    hotspots = [
        {"country": h["country"], "name": country_name(h["country"]), "flag": flag_emoji(h["country"]),
         "intensity": h.get("intensity", 0), "announcements": h.get("announcements", 0),
         "origins": h.get("origins", 0),
         "bar": round(100 * h.get("intensity", 0) / peak_intensity) if peak_intensity else 0}
        for h in hotspots_raw
    ]

    peak_churn = max((c.get("announcements", 0) for c in churners_raw), default=0)
    churners = [
        {**c, "bar": round(100 * c.get("announcements", 0) / peak_churn) if peak_churn else 0}
        for c in churners_raw
    ]

    return {
        "stats": {
            "hotspots": len(hotspots_raw),
            "outages": len(outages),
            "hijacks": len(grip),
            "origin_changes": origin.get("count", 0),
            "max_spike": max((s.get("ratio", 0) for s in spikes), default=0),
        },
        "hotspots": hotspots,
        "outages": list(outages.values()),
        "asn_alerts": asn_alerts,
        "hijacks": grip,
        "origin_changes": origin.get("recent") or [],
        "churners": churners,
        "flaps": flaps_raw,
        "spikes": spikes,
        "map": {"hotspots": [h["country"] for h in hotspots_raw],
                "outages": list(outages.keys())},
    }


def main() -> int:
    """Generate one briefing now. For on-demand runs / verification:
    `ROUTELENS_DATABASE=... python -m routelens.weather`."""
    import logging
    import os

    from .ai import WeatherAI
    from .sources import SourceClient

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = os.environ.get("ROUTELENS_DATABASE", "/var/lib/routelens/routelens.db")
    store = RouteLensStore(db)
    store.init_schema()
    ai = WeatherAI.from_env()
    if ai is None:
        print("MISTRAL_API_KEY not set — cannot generate a briefing.")
        return 1
    report = generate_weather_report(store, SourceClient(store), ai)
    print(f"[{report['severity']}] {report['headline']}\n\n{report['body_md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
