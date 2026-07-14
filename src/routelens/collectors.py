from __future__ import annotations

# RIPE RIS route collectors (active as of 2026-07, per stat.ripe.net rrc-info).
# RIS Live "host" fields arrive as e.g. "rrc01.ripe.net"; keys here are the
# lowercase short id. Coordinates are city centres, nudged apart for the three
# Amsterdam collectors so map markers don't stack.
ACTIVE_COLLECTORS = [
    {"rrc": "rrc00", "city": "Amsterdam", "country": "NL", "lat": 52.37, "lon": 4.90, "scope": "multihop"},
    {"rrc": "rrc01", "city": "London", "country": "GB", "lat": 51.51, "lon": -0.13, "scope": "LINX/LONAP"},
    {"rrc": "rrc03", "city": "Amsterdam", "country": "NL", "lat": 52.31, "lon": 4.94, "scope": "AMS-IX/NL-IX"},
    {"rrc": "rrc04", "city": "Geneva", "country": "CH", "lat": 46.20, "lon": 6.14, "scope": "CIXP"},
    {"rrc": "rrc05", "city": "Vienna", "country": "AT", "lat": 48.21, "lon": 16.37, "scope": "VIX"},
    {"rrc": "rrc06", "city": "Tokyo", "country": "JP", "lat": 35.68, "lon": 139.69, "scope": "DIX-IE/JPIX"},
    {"rrc": "rrc07", "city": "Stockholm", "country": "SE", "lat": 59.33, "lon": 18.07, "scope": "Netnod"},
    {"rrc": "rrc10", "city": "Milan", "country": "IT", "lat": 45.46, "lon": 9.19, "scope": "MIX"},
    {"rrc": "rrc11", "city": "New York", "country": "US", "lat": 40.71, "lon": -74.01, "scope": "NYIIX"},
    {"rrc": "rrc12", "city": "Frankfurt", "country": "DE", "lat": 50.11, "lon": 8.68, "scope": "DE-CIX"},
    {"rrc": "rrc13", "city": "Moscow", "country": "RU", "lat": 55.76, "lon": 37.62, "scope": "MSK-IX"},
    {"rrc": "rrc14", "city": "Palo Alto", "country": "US", "lat": 37.44, "lon": -122.14, "scope": "PAIX"},
    {"rrc": "rrc15", "city": "São Paulo", "country": "BR", "lat": -23.55, "lon": -46.63, "scope": "PTTMetro"},
    {"rrc": "rrc16", "city": "Miami", "country": "US", "lat": 25.76, "lon": -80.19, "scope": "NOTA"},
    {"rrc": "rrc18", "city": "Barcelona", "country": "ES", "lat": 41.39, "lon": 2.17, "scope": "CATNIX"},
    {"rrc": "rrc19", "city": "Johannesburg", "country": "ZA", "lat": -26.20, "lon": 28.05, "scope": "NAP Africa"},
    {"rrc": "rrc20", "city": "Zurich", "country": "CH", "lat": 47.37, "lon": 8.54, "scope": "SwissIX"},
    {"rrc": "rrc21", "city": "Paris", "country": "FR", "lat": 48.86, "lon": 2.35, "scope": "France-IX"},
    {"rrc": "rrc22", "city": "Bucharest", "country": "RO", "lat": 44.43, "lon": 26.10, "scope": "InterLAN"},
    {"rrc": "rrc23", "city": "Singapore", "country": "SG", "lat": 1.35, "lon": 103.82, "scope": "Equinix SG"},
    {"rrc": "rrc24", "city": "Montevideo", "country": "UY", "lat": -34.90, "lon": -56.19, "scope": "LACNIC multihop"},
    {"rrc": "rrc25", "city": "Amsterdam", "country": "NL", "lat": 52.43, "lon": 4.86, "scope": "multihop"},
    {"rrc": "rrc26", "city": "Dubai", "country": "AE", "lat": 25.20, "lon": 55.27, "scope": "UAE-IX"},
]
