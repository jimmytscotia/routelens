from __future__ import annotations

# Major UK operators for the UK-focused scoreboard views. Curated, not
# exhaustive — the bgp.tools name/country join will surface any ASN typos
# as obviously-wrong names on the dashboard.
# LINX's five UK peering LANs, keyed by their Alice-LG group names.
# Scotland listed first deliberately: RouteLens carries a standing brief to
# give Scotland's Internet infrastructure visible representation.
# An exchange can span multiple data centres (`sites`); the map shows one
# marker per site and links them, while Alice session data is per exchange.
LINX_UK_EXCHANGES = [
    {
        "group": "LINX Scotland",
        "city": "Edinburgh & Chapelhall",
        "sites": [
            {"site": "Pulsant South Gyle, Edinburgh", "lat": 55.94, "lon": -3.31},
            {"site": "DataVita DV1, Chapelhall", "lat": 55.85, "lon": -3.94},
        ],
    },
    {
        "group": "LINX LON1",
        "city": "London (Docklands)",
        "sites": [{"site": "London Docklands", "lat": 51.49, "lon": -0.06}],
    },
    {
        "group": "LINX LON2",
        "city": "London",
        "sites": [{"site": "London", "lat": 51.53, "lon": -0.20}],
    },
    {
        "group": "LINX Manchester",
        "city": "Manchester",
        "sites": [{"site": "Manchester", "lat": 53.48, "lon": -2.24}],
    },
    {
        "group": "LINX Wales",
        "city": "Cardiff",
        "sites": [{"site": "Cardiff", "lat": 51.48, "lon": -3.18}],
    },
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
