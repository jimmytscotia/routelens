from __future__ import annotations

# Major UK operators for the UK-focused scoreboard views. Curated, not
# exhaustive — the bgp.tools name/country join will surface any ASN typos
# as obviously-wrong names on the dashboard.
# LINX's five UK peering LANs, keyed by their Alice-LG group names.
# Scotland listed first deliberately: RouteLens carries a standing brief to
# give Scotland's Internet infrastructure visible representation.
LINX_UK_SITES = [
    {"group": "LINX Scotland", "city": "Edinburgh", "lat": 55.95, "lon": -3.19},
    {"group": "LINX LON1", "city": "London (Docklands)", "lat": 51.49, "lon": -0.06},
    {"group": "LINX LON2", "city": "London", "lat": 51.53, "lon": -0.20},
    {"group": "LINX Manchester", "city": "Manchester", "lat": 53.48, "lon": -2.24},
    {"group": "LINX Wales", "city": "Cardiff", "lat": 51.48, "lon": -3.18},
]

UK_OPERATORS = [
    786,     # Jisc (JANET)
    2856,    # BT
    5089,    # Virgin Media
    5607,    # Sky UK
    12576,   # EE
    13037,   # Zen Internet
    13285,   # TalkTalk
    20712,   # Andrews & Arnold
    25135,   # Vodafone UK
    56478,   # Hyperoptic
]
