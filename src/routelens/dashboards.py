from __future__ import annotations

# The approved dashboard roadmap (see CLAUDE.md). Slugs double as routes:
# /dashboards/<slug>. status is 'live' or 'planned'; planned entries render
# in the sidebar unlinked with a "soon" tag.
DASHBOARDS = [
    {"slug": "collectors", "title": "Collector activity", "status": "live"},
    {"slug": "asns", "title": "ASN churn", "status": "live"},
    {"slug": "flaps", "title": "Prefix flaps", "status": "live"},
    {"slug": "origin-changes", "title": "Origin changes", "status": "live"},
    {"slug": "rpki", "title": "RPKI scoreboard", "status": "live"},
    {"slug": "address-space", "title": "Address space", "status": "planned"},
    {"slug": "asn-profiles", "title": "ASN profiles", "status": "planned"},
    {"slug": "table-growth", "title": "Table growth", "status": "live"},
    {"slug": "transit", "title": "Transit centrality", "status": "planned"},
    {"slug": "countries", "title": "Country instability", "status": "planned"},
]


def first_live_slug() -> str:
    return next(d["slug"] for d in DASHBOARDS if d["status"] == "live")


def _dash(slug: str) -> dict:
    d = next(x for x in DASHBOARDS if x["slug"] == slug)
    return {"title": d["title"], "url": f"/dashboards/{d['slug']}", "status": d["status"]}


def nav() -> list[dict]:
    """Sidebar structure: categorized destinations across the whole app."""
    return [
        {
            "category": "Live",
            "items": [
                {"title": "Pulse", "url": "/", "status": "live"},
                {"title": "Looking glass", "url": "/q", "status": "live"},
            ],
        },
        {
            "category": "BGP activity",
            "items": [
                _dash("collectors"), _dash("asns"), _dash("flaps"),
                _dash("origin-changes"), _dash("transit"), _dash("countries"),
            ],
        },
        {
            "category": "Routing table",
            "items": [
                _dash("rpki"), _dash("address-space"),
                _dash("asn-profiles"), _dash("table-growth"),
            ],
        },
    ]
