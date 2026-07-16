from datetime import datetime, timedelta, timezone

from routelens.store import RouteLensStore
from routelens.weather import detect_anomalies


def _minute(minutes_ago: int) -> str:
    dt = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _hour(hours_ago: int) -> str:
    dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _seeded_store(tmp_path) -> RouteLensStore:
    store = RouteLensStore(tmp_path / "weather.db")
    store.init_schema()
    return store


def test_collector_spike_detected_against_trailing_baseline(tmp_path):
    store = _seeded_store(tmp_path)
    # Baseline: rrc01 does ~60 updates/hour for 6 prior hours.
    for hours_ago in range(2, 8):
        for m in range(0, 60, 10):
            store.record_activity_bucket(
                bucket_ts=_minute(hours_ago * 60 + m), rrc="rrc01",
                updates=10, announcements=9, withdrawals=1,
            )
    # Last hour: 40x surge.
    for m in range(0, 60, 10):
        store.record_activity_bucket(
            bucket_ts=_minute(m), rrc="rrc01",
            updates=400, announcements=380, withdrawals=20,
        )
    # A steady collector for contrast.
    for hours_ago in range(0, 8):
        store.record_activity_bucket(
            bucket_ts=_minute(hours_ago * 60 + 5), rrc="rrc12",
            updates=50, announcements=45, withdrawals=5,
        )

    anomalies = detect_anomalies(store)

    spikes = anomalies["collector_spikes"]
    assert [s["rrc"] for s in spikes] == ["rrc01"]
    assert spikes[0]["last_hour"] == 2400
    assert spikes[0]["ratio"] >= 10


def test_no_spikes_when_activity_is_flat(tmp_path):
    store = _seeded_store(tmp_path)
    for hours_ago in range(0, 8):
        store.record_activity_bucket(
            bucket_ts=_minute(hours_ago * 60 + 5), rrc="rrc01",
            updates=50, announcements=45, withdrawals=5,
        )

    anomalies = detect_anomalies(store)

    assert anomalies["collector_spikes"] == []


def test_country_hotspots_flag_intensity_outliers(tmp_path):
    store = _seeded_store(tmp_path)
    names = [(i, f"Net {i}", cc) for i, cc in enumerate(["BR"] * 5 + ["US"] * 5 + ["SD"], start=1)]
    store.upsert_asn_names(names)
    # Ordinary churn: BR and US origins do modest announcing.
    for asn in range(1, 11):
        store.record_asn_bucket(bucket_ts=_hour(0), asn=asn, updates=100, announcements=100)
    # Sudan: one origin announcing wildly (intensity outlier).
    store.record_asn_bucket(bucket_ts=_hour(0), asn=11, updates=9000, announcements=9000)

    anomalies = detect_anomalies(store)

    hotspots = anomalies["country_hotspots"]
    assert [h["country"] for h in hotspots] == ["SD"]
    assert hotspots[0]["intensity"] == 9000


def test_flap_leaders_and_origin_changes_included(tmp_path):
    store = _seeded_store(tmp_path)
    store.upsert_asn_names([(15169, "Google LLC", "US")])
    store.record_prefix_bucket(
        bucket_ts=_hour(0), prefix="203.0.113.0/24",
        announcements=500, withdrawals=400, origin_asn=15169,
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    store.record_origin_event(observed_at=now, prefix="198.51.100.0/24", old_asn=64500, new_asn=64666)

    anomalies = detect_anomalies(store)

    assert anomalies["flap_leaders"][0]["prefix"] == "203.0.113.0/24"
    assert anomalies["flap_leaders"][0]["flapping"] is True
    assert anomalies["origin_changes"]["count"] == 1
    assert anomalies["origin_changes"]["recent"][0]["prefix"] == "198.51.100.0/24"


def test_weather_report_store_roundtrip(tmp_path):
    store = _seeded_store(tmp_path)

    report_id = store.save_weather_report(
        period_hours=6,
        headline="Quiet seas with a squall over Sudan",
        severity="minor",
        body_md="## Summary\nMostly calm...",
        evidence={"ioda": 2, "spikes": ["rrc01"]},
        model="mistral-small-latest",
    )
    store.save_weather_report(
        period_hours=6, headline="Second report", severity="calm",
        body_md="calm", evidence={}, model="mistral-small-latest",
    )

    latest = store.latest_weather_report()
    assert latest["headline"] == "Second report"
    assert latest["severity"] == "calm"

    reports = store.list_weather_reports(limit=10)
    assert len(reports) == 2
    first = next(r for r in reports if r["id"] == report_id)
    assert first["evidence"]["spikes"] == ["rrc01"]
    assert first["generated_at"]


class FakeAI:
    model = "mistral-small-latest"

    def __init__(self, result=None):
        self.result = result or {
            "headline": "Calm across the global table",
            "severity": "calm",
            "body_md": "## Summary\nNothing notable in the last six hours.",
        }
        self.last_evidence = None

    def summarize(self, evidence):
        self.last_evidence = evidence
        return self.result


class FakeSources:
    def __init__(self, ioda=None, grip=None, radar=None):
        self._ioda = ioda if ioda is not None else {"ok": True, "data": {"alerts": [
            {"entity_type": "country", "entity_code": "SD", "entity_name": "Sudan",
             "datasource": "merit-nt", "level": "critical", "time": 1784176800,
             "value": 10, "history": 55},
        ]}}
        self._grip = grip if grip is not None else {"ok": True, "data": {"events": [
            {"id": "moas-x", "suspicion": 85, "label": "suspicious", "confidence": 90,
             "attackers": ["64666"], "victims": ["64500"], "explanation": "hijack-y", "time": 1},
            {"id": "moas-y", "suspicion": 5, "label": "legitimate", "confidence": 90,
             "attackers": [], "victims": [], "explanation": "fine", "time": 2},
        ]}}
        self._radar = radar if radar is not None else {"ok": False, "unconfigured": True}

    def ioda_alerts(self):
        return self._ioda

    def grip_events(self):
        return self._grip

    def radar_outages(self):
        return self._radar


def test_build_evidence_merges_internal_and_external(tmp_path):
    from routelens.weather import build_evidence

    store = _seeded_store(tmp_path)
    evidence = build_evidence(store, FakeSources())

    assert "internal" in evidence
    assert evidence["ioda"][0]["entity_code"] == "SD"
    # GRIP is filtered to suspicious events only — the 'legitimate' one drops.
    assert [e["id"] for e in evidence["grip"]] == ["moas-x"]
    # Radar unconfigured degrades to an empty list, not an error.
    assert evidence["radar_outages"] == []


def test_generate_weather_report_saves_and_returns(tmp_path):
    from routelens.weather import generate_weather_report

    store = _seeded_store(tmp_path)
    ai = FakeAI()

    report = generate_weather_report(store, FakeSources(), ai)

    assert report["severity"] == "calm"
    # It was handed the merged evidence.
    assert ai.last_evidence["ioda"][0]["entity_code"] == "SD"
    # And persisted with the model id + evidence.
    saved = store.latest_weather_report()
    assert saved["headline"] == "Calm across the global table"
    assert saved["model"] == "mistral-small-latest"
    assert saved["evidence"]["ioda"][0]["entity_code"] == "SD"


def test_generate_weather_report_without_ai_is_noop(tmp_path):
    from routelens.weather import generate_weather_report

    store = _seeded_store(tmp_path)

    report = generate_weather_report(store, FakeSources(), None)

    assert report is None
    assert store.latest_weather_report() is None


def test_generate_weather_report_clamps_bad_severity(tmp_path):
    from routelens.weather import generate_weather_report

    store = _seeded_store(tmp_path)
    ai = FakeAI({"headline": "H", "severity": "apocalyptic", "body_md": "b"})

    report = generate_weather_report(store, FakeSources(), ai)

    # An out-of-vocabulary severity from the model is clamped to 'notable'.
    assert report["severity"] == "notable"
    assert store.latest_weather_report()["severity"] == "notable"


def test_build_view_shapes_evidence_for_rendering():
    from routelens.weather import build_view

    evidence = {
        "internal": {
            "collector_spikes": [{"rrc": "rrc01", "last_hour": 5000, "hourly_baseline": 500, "ratio": 10.0}],
            "country_hotspots": [
                {"country": "SD", "intensity": 9000, "announcements": 9000, "origins": 1},
                {"country": "BH", "intensity": 3000, "announcements": 6000, "origins": 2},
            ],
            "top_churners": [{"asn": 15169, "name": "Google LLC", "announcements": 800}],
            "flap_leaders": [{"prefix": "203.0.113.0/24", "events": 900, "origin_asn": 15169, "flapping": True}],
            "origin_changes": {"count": 1, "recent": [
                {"prefix": "198.51.100.0/24", "old_asn": 64500, "new_asn": 64666, "flips": 2, "last_seen": "x"}]},
        },
        "ioda": [
            {"entity_type": "country", "entity_code": "AF", "entity_name": "Afghanistan",
             "datasource": "merit-nt", "level": "critical", "value": 10, "history": 55},
        ],
        "grip": [
            {"id": "moas-x", "suspicion": 85, "label": "suspicious", "confidence": 90,
             "attackers": ["64666"], "victims": ["64500"], "explanation": "hijack-y", "time": 1},
        ],
        "radar_outages": [
            {"id": "o1", "locations": ["AF"], "cause": "POWER_OUTAGE", "scope": "NATIONWIDE",
             "description": "outage", "asns": [], "start": "x", "end": None},
        ],
    }

    view = build_view(evidence)

    assert view["stats"]["hotspots"] == 2
    assert view["stats"]["outages"] == 1        # AF from IODA + Radar merged to one country
    assert view["stats"]["hijacks"] == 1
    assert view["stats"]["origin_changes"] == 1
    assert view["stats"]["max_spike"] == 10.0

    # Hotspots: flag + name + a 0-100 bar scaled to the max intensity.
    top = view["hotspots"][0]
    assert top["country"] == "SD" and top["name"] == "Sudan" and top["flag"]
    assert top["bar"] == 100
    assert view["hotspots"][1]["bar"] == 33   # 3000/9000

    # Outages merge IODA + Radar by country with cause + sources.
    af = view["outages"][0]
    assert af["country"] == "AF" and af["name"] == "Afghanistan"
    assert "IODA" in af["sources"] and "Cloudflare Radar" in af["sources"]
    assert "POWER_OUTAGE" in af["causes"]

    # Map payload lists affected countries by kind.
    assert set(view["map"]["hotspots"]) == {"SD", "BH"}
    assert view["map"]["outages"] == ["AF"]


def test_build_view_handles_empty_evidence():
    from routelens.weather import build_view

    view = build_view({"internal": {}, "ioda": [], "grip": [], "radar_outages": []})

    assert view["stats"] == {"hotspots": 0, "outages": 0, "hijacks": 0, "origin_changes": 0, "max_spike": 0}
    assert view["hotspots"] == [] and view["outages"] == [] and view["map"]["hotspots"] == []


def test_linkify_entities_wires_asns_and_prefixes():
    from routelens.weather import linkify_entities

    html = ("<p>Top churner <strong>AS19429</strong> and AS266016; prefix "
            "185.39.51.0/24 flipped; v6 2a00:1450::/32 seen.</p>")

    out = linkify_entities(html)

    assert '<a class="wx-ent" href="/q?query=AS19429">AS19429</a>' in out
    assert '<a class="wx-ent" href="/q?query=AS266016">AS266016</a>' in out
    assert 'href="/q?query=185.39.51.0%2F24">185.39.51.0/24</a>' in out
    assert '2a00:1450::/32</a>' in out
    # Bold wrapper is preserved around the now-linked ASN.
    assert "<strong><a" in out


def test_linkify_leaves_plain_text_and_dates_alone():
    from routelens.weather import linkify_entities

    html = "<p>Observed at 2026-07-16T12:00, version 1.6.0, nothing else.</p>"

    assert linkify_entities(html) == html


def test_render_narrative_combines_markdown_and_links():
    from routelens.weather import render_narrative

    out = render_narrative("Watch **AS15169** and 8.8.8.0/24 closely.")

    assert "<strong><a class=\"wx-ent\" href=\"/q?query=AS15169\">AS15169</a></strong>" in out
    assert 'href="/q?query=8.8.8.0%2F24"' in out
