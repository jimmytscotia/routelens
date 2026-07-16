from __future__ import annotations

# Major (non-Chinese) Internet/IT service companies for the health board, plus
# a UK section. Each entry:
#   name      display name
#   category  grouping on the board
#   asns      primary origin ASNs (first is the headline one), verified via
#             PeeringDB/RIPE 2026-07-16
#   status    {"type": ..., "url": ...} or None when no machine-readable feed
#             exists yet — those companies still get their live BGP footprint.
#   uk        True for the UK section
#
# status types: "statuspage" (Atlassian/incident.io v2 /api/v2/status.json),
# "gcp" (Google Cloud incidents.json). Others fall through to BGP-only until
# their bespoke adapters are added.
COMPANIES = [
    # ---- Cloud & infrastructure ----
    {"name": "Cloudflare", "category": "Cloud & infrastructure", "asns": [13335],
     "status": {"type": "statuspage", "url": "https://www.cloudflarestatus.com/api/v2/status.json"}},
    {"name": "Google Cloud", "category": "Cloud & infrastructure", "asns": [15169, 396982],
     "status": {"type": "gcp", "url": "https://status.cloud.google.com/incidents.json"}},
    {"name": "Amazon Web Services", "category": "Cloud & infrastructure", "asns": [16509, 14618],
     "status": {"type": "aws", "url": "https://health.aws.amazon.com/public/currentevents"}},
    {"name": "Microsoft", "category": "Cloud & infrastructure", "asns": [8075],
     "status": {"type": "microsoft", "url": "https://status.cloud.microsoft/api/posts/m365Consumer"}},
    {"name": "Apple", "category": "Cloud & infrastructure", "asns": [714, 6185],
     "status": {"type": "apple", "url": "https://www.apple.com/support/systemstatus/data/system_status_en_US.js"}},
    {"name": "NVIDIA", "category": "Cloud & infrastructure", "asns": [11414, 20347],
     "status": {"type": "statuspage", "url": "https://status.ngc.nvidia.com/api/v2/status.json"}},

    # ---- Consumer & social ----
    {"name": "Meta", "category": "Consumer & social", "asns": [32934],
     "status": {"type": "meta", "url": "https://metastatus.com/data/outages/graph-api.json"}},
    {"name": "X (Twitter)", "category": "Consumer & social", "asns": [13414], "status": None},
    {"name": "Netflix", "category": "Consumer & social", "asns": [2906, 40027], "status": None},
    {"name": "Spotify", "category": "Consumer & social", "asns": [8403],
     "status": {"type": "statuspage", "url": "https://spotify.statuspage.io/api/v2/status.json"}},
    {"name": "Reddit", "category": "Consumer & social", "asns": [54113],
     "status": {"type": "statuspage", "url": "https://www.redditstatus.com/api/v2/status.json"}},

    # ---- Developer & SaaS ----
    {"name": "GitHub", "category": "Developer & SaaS", "asns": [36459],
     "status": {"type": "statuspage", "url": "https://www.githubstatus.com/api/v2/status.json"}},
    {"name": "OpenAI", "category": "Developer & SaaS", "asns": [13335],
     "status": {"type": "statuspage", "url": "https://status.openai.com/api/v2/status.json"}},
    {"name": "Zoom", "category": "Developer & SaaS", "asns": [30103],
     "status": {"type": "statuspage", "url": "https://www.zoomstatus.com/api/v2/status.json"}},
    {"name": "Salesforce", "category": "Developer & SaaS", "asns": [14340], "status": None},
    {"name": "Adobe", "category": "Developer & SaaS", "asns": [15224, 1313], "status": None},

    # ---- Finance ----
    {"name": "PayPal", "category": "Finance", "asns": [17012], "status": None},

    # ---- United Kingdom ----
    {"name": "BT / EE", "category": "UK networks", "asns": [2856, 12576], "status": None, "uk": True},
    {"name": "Sky", "category": "UK networks", "asns": [5607], "status": None, "uk": True},
    {"name": "Virgin Media O2", "category": "UK networks", "asns": [5089, 35228], "status": None, "uk": True},
    {"name": "Vodafone UK", "category": "UK networks", "asns": [25135, 1273], "status": None, "uk": True},
    {"name": "Sage", "category": "UK services", "asns": [], "uk": True,
     "status": {"type": "statuspage", "url": "https://status.sage.com/api/v2/status.json"}},
    {"name": "BBC", "category": "UK services", "asns": [2818], "status": None, "uk": True},
    {"name": "Lloyds Banking Group", "category": "UK banks", "asns": [8435], "status": None, "uk": True},
    {"name": "Barclays", "category": "UK banks", "asns": [44022], "status": None, "uk": True},
    {"name": "NatWest", "category": "UK banks", "asns": [21054], "status": None, "uk": True},
]


def build_company_board(store, sources, *, registry=None, since=None):
    """One row per company merging its live status feed with its BGP footprint
    (24h announcements + RPKI coverage of the primary ASN). Status fetches run
    in parallel so a cold page stays responsive. Grouped by category, with UK
    companies split into their own sections."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone

    registry = registry if registry is not None else COMPANIES
    if since is None:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")

    all_asns = sorted({asn for c in registry for asn in c["asns"]})
    announced = store.asn_announcements(all_asns, since=since)
    rpki = {row["asn"]: row for row in store.list_rpki_scores()}

    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(lambda c: sources.company_status(c["status"]), registry))

    rows = []
    for company, status in zip(registry, statuses):
        primary = company["asns"][0] if company["asns"] else None
        score = rpki.get(primary)
        coverage = (round(100 * score["valid"] / score["total"])
                    if score and score["total"] else None)
        data = status.get("data") or {}
        rows.append({
            "name": company["name"],
            "category": company["category"],
            "uk": company.get("uk", False),
            "asns": company["asns"],
            "primary_asn": primary,
            "state": data.get("state", "unknown"),
            "detail": data.get("detail", ""),
            "has_feed": company["status"] is not None,
            "announcements": sum(announced.get(a, 0) for a in company["asns"]),
            "rpki_coverage": coverage,
        })

    def group(items):
        by_cat: dict[str, list] = {}
        for r in items:
            by_cat.setdefault(r["category"], []).append(r)
        return [{"category": cat, "companies": cs} for cat, cs in by_cat.items()]

    return {
        "global": group([r for r in rows if not r["uk"]]),
        "uk": group([r for r in rows if r["uk"]]),
    }


def all_company_asns() -> list[int]:
    """Every company origin ASN, de-duplicated — for RPKI scoring targets."""
    seen: dict[int, None] = {}
    for company in COMPANIES:
        for asn in company["asns"]:
            seen.setdefault(asn, None)
    return list(seen)
