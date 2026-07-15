from __future__ import annotations

# RIPE RIS route collectors (active as of 2026-07, verified against
# stat.ripe.net rrc-info on 2026-07-15). RIS Live "host" fields arrive as
# e.g. "rrc01.ripe.net"; keys here are the lowercase short id. Coordinates
# are city centres, nudged apart for the three Amsterdam collectors so map
# markers don't stack. `scope` is RIPE's display string; `ixps` is the
# machine-readable list of host IXPs (empty = multihop, not IXP-hosted).
# NB rrc01 (London) is the only UK and only LINX-hosted collector.
ACTIVE_COLLECTORS = [
    {"rrc": "rrc00", "city": "Amsterdam", "country": "NL", "lat": 52.37, "lon": 4.90, "scope": "multihop", "ixps": []},
    {"rrc": "rrc01", "city": "London", "country": "GB", "lat": 51.51, "lon": -0.13, "scope": "LINX/LONAP", "ixps": ["LINX", "LONAP"]},
    {"rrc": "rrc03", "city": "Amsterdam", "country": "NL", "lat": 52.31, "lon": 4.94, "scope": "AMS-IX/NL-IX", "ixps": ["AMS-IX", "NL-IX"]},
    {"rrc": "rrc04", "city": "Geneva", "country": "CH", "lat": 46.20, "lon": 6.14, "scope": "CIXP", "ixps": ["CIXP"]},
    {"rrc": "rrc05", "city": "Vienna", "country": "AT", "lat": 48.21, "lon": 16.37, "scope": "VIX", "ixps": ["VIX"]},
    {"rrc": "rrc06", "city": "Tokyo", "country": "JP", "lat": 35.68, "lon": 139.69, "scope": "DIX-IE/JPIX", "ixps": ["DIX-IE", "JPIX"]},
    {"rrc": "rrc07", "city": "Stockholm", "country": "SE", "lat": 59.33, "lon": 18.07, "scope": "Netnod", "ixps": ["Netnod"]},
    {"rrc": "rrc10", "city": "Milan", "country": "IT", "lat": 45.46, "lon": 9.19, "scope": "MIX", "ixps": ["MIX"]},
    {"rrc": "rrc11", "city": "New York", "country": "US", "lat": 40.71, "lon": -74.01, "scope": "NYIIX", "ixps": ["NYIIX"]},
    {"rrc": "rrc12", "city": "Frankfurt", "country": "DE", "lat": 50.11, "lon": 8.68, "scope": "DE-CIX", "ixps": ["DE-CIX"]},
    {"rrc": "rrc13", "city": "Moscow", "country": "RU", "lat": 55.76, "lon": 37.62, "scope": "MSK-IX", "ixps": ["MSK-IX"]},
    {"rrc": "rrc14", "city": "Palo Alto", "country": "US", "lat": 37.44, "lon": -122.14, "scope": "PAIX", "ixps": ["PAIX"]},
    {"rrc": "rrc15", "city": "São Paulo", "country": "BR", "lat": -23.55, "lon": -46.63, "scope": "PTTMetro", "ixps": ["PTTMetro"]},
    {"rrc": "rrc16", "city": "Miami", "country": "US", "lat": 25.76, "lon": -80.19, "scope": "NOTA", "ixps": ["NOTA"]},
    {"rrc": "rrc18", "city": "Barcelona", "country": "ES", "lat": 41.39, "lon": 2.17, "scope": "CATNIX", "ixps": ["CATNIX"]},
    {"rrc": "rrc19", "city": "Johannesburg", "country": "ZA", "lat": -26.20, "lon": 28.05, "scope": "NAP Africa", "ixps": ["NAP Africa"]},
    {"rrc": "rrc20", "city": "Zurich", "country": "CH", "lat": 47.37, "lon": 8.54, "scope": "SwissIX", "ixps": ["SwissIX"]},
    {"rrc": "rrc21", "city": "Paris", "country": "FR", "lat": 48.86, "lon": 2.35, "scope": "France-IX", "ixps": ["France-IX"]},
    {"rrc": "rrc22", "city": "Bucharest", "country": "RO", "lat": 44.43, "lon": 26.10, "scope": "InterLAN", "ixps": ["InterLAN"]},
    {"rrc": "rrc23", "city": "Singapore", "country": "SG", "lat": 1.35, "lon": 103.82, "scope": "Equinix SG", "ixps": ["Equinix SG"]},
    {"rrc": "rrc24", "city": "Montevideo", "country": "UY", "lat": -34.90, "lon": -56.19, "scope": "LACNIC multihop", "ixps": []},
    {"rrc": "rrc25", "city": "Amsterdam", "country": "NL", "lat": 52.43, "lon": 4.86, "scope": "multihop", "ixps": []},
    {"rrc": "rrc26", "city": "Dubai", "country": "AE", "lat": 25.20, "lon": 55.27, "scope": "UAE-IX", "ixps": ["UAE-IX"]},
]


def collectors_at(ixp: str) -> list[dict]:
    """Collectors hosted at a given IXP — data query, not template logic."""
    return [c for c in ACTIVE_COLLECTORS if ixp in c["ixps"]]
