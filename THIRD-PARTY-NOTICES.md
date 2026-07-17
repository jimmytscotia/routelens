# Third-party notices

The RouteLens **source code** is released under the MIT License (see `LICENSE`).
This file records the parts that are **not** covered by that licence, or that
carry their own terms. The MIT licence applies to the code only — it does not
grant rights to the items below.

## Name and logo

"RouteLens", the RouteLens name, and the mark in `src/routelens/static/logo.svg`
are **not** covered by the MIT licence. All rights reserved. If you fork or
redistribute this project, please use your own name and mark.

## Bundled assets

| Asset | Source | Terms |
|---|---|---|
| `src/routelens/static/fonts/ClashDisplay-Variable.woff2` | Fontshare / Indian Type Foundry | ITF Free Font Licence — free to use and embed; redistribution governed by that licence, **not** MIT. |
| `src/routelens/static/fonts/Satoshi-Variable.woff2` | Fontshare / Indian Type Foundry | ITF Free Font Licence — as above. |
| `src/routelens/static/world.geojson` | Natural Earth (`naturalearthdata.com`) | Public domain. |

## Live data sources

RouteLens fetches data at runtime from third-party services, each with its own
terms of use. The MIT code licence does **not** grant any rights to this data;
running the application is subject to the providers' terms. Notably:

| Source | Used for | Terms |
|---|---|---|
| Cloudflare Radar | RPKI stats, outage & hijack annotations | **CC BY-NC 4.0 — non-commercial**, attribution required. |
| IODA (Georgia Tech) | Internet outage detection | **Academic / educational use**, attribution required. |
| GRIP (Georgia Tech) | BGP hijack detection | **Academic / educational use**, attribution required. |
| RIPE NCC — RIS & RIPEstat | Live BGP stream, routing/looking-glass data | RIPE NCC terms; send a `sourceapp` identifier. |
| RouteViews | Prefix/ASN routing & RPKI | RouteViews terms; guest rate limits. |
| NLNOG Ring looking glass | Cross-network prefix lookups | NLNOG Ring terms. |
| bgp.tools | ASN names, address-space table | Requires a descriptive User-Agent; non-commercial hobby use. |
| PeeringDB | Network/IX metadata | PeeringDB terms. |
| Globalping (jsDelivr) | Worldwide reachability probes | Globalping terms; free-tier rate limits. |
| bgp.potaroo.net | Routing-table growth history | Geoff Huston / APNIC, attribution. |
| LINX Alice-LG | UK exchange route-server data | LINX public looking glass. |

If you intend to run RouteLens **commercially**, review each provider's terms
first — several (Cloudflare Radar's non-commercial licence, IODA/GRIP's academic
use) are incompatible with commercial use as configured here.
