from __future__ import annotations

# The approved dashboard roadmap (see CLAUDE.md). Slugs double as routes:
# /dashboards/<slug>. status is 'live' or 'planned'; planned entries render
# in the sidebar unlinked with a "soon" tag.
DASHBOARDS = [
    {"slug": "collectors", "title": "Collector activity", "status": "live"},
    {"slug": "asns", "title": "ASN churn", "status": "live"},
    {"slug": "flaps", "title": "Prefix flaps", "status": "planned"},
    {"slug": "origin-changes", "title": "Origin changes", "status": "planned"},
    {"slug": "rpki", "title": "RPKI scoreboard", "status": "planned"},
    {"slug": "address-space", "title": "Address space", "status": "planned"},
    {"slug": "asn-profiles", "title": "ASN profiles", "status": "planned"},
    {"slug": "table-growth", "title": "Table growth", "status": "planned"},
    {"slug": "transit", "title": "Transit centrality", "status": "planned"},
    {"slug": "countries", "title": "Country instability", "status": "planned"},
]


def first_live_slug() -> str:
    return next(d["slug"] for d in DASHBOARDS if d["status"] == "live")
