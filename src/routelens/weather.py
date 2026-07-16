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
