# CLAUDE.md — RouteLens project handoff

You are developing **RouteLens**, a NextHop Lab network observability demo app.

## Product intent

RouteLens should be a credible network-engineering dashboard, not a toy demo. It watches public DNS, private split-DNS, HTTP reachability, TLS certificates, and RIPEstat BGP visibility, then presents operationally useful insight for a blog/demo.

Visual target: polished Torc/Framer-inspired dark product aesthetic:

- black / near-black canvas
- high-contrast typography
- Inter + mono telemetry labels
- electric blue/cyan accents
- dark glass cards with thin luminous borders
- professional NOC / network operations feel

## Architecture

- Flask app factory: `src/routelens/app.py`
- SQLite repository: `src/routelens/store.py`
- Check runner: `src/routelens/collector.py`
- DNS/HTTP/TLS checks: `src/routelens/checks.py`
- RIPEstat/BGP summariser: `src/routelens/ripestat.py`
- Insight scoring: `src/routelens/insights.py`
- Jinja templates: `src/routelens/templates/`
- Tests: `tests/`

Use stdlib SQLite for the MVP. Do not introduce SQLAlchemy/Postgres unless Jim explicitly asks.

## Commands

Use `uv` locally on macOS:

```bash
uv sync
uv run pytest -q
ROUTELENS_DATABASE=instance/routelens.db uv run python -m routelens.cli --json
ROUTELENS_DATABASE=instance/routelens.db uv run flask --app routelens.app:create_app run --debug --port 8097
```

The current passing test baseline is:

```text
68 passed
```

Local quirk: `uv sync` does not install the package itself (no `[build-system]` in
pyproject), so `flask run` and `python -m routelens.cli` need `PYTHONPATH=src` locally.
pytest works without it (`pythonpath = ["src"]` in pyproject).

## TDD expectations

Follow strict TDD for new behavior:

1. Add or update a test first.
2. Run the specific test and confirm it fails for the expected reason.
3. Implement the smallest working change.
4. Re-run the specific test.
5. Run the full suite with `uv run pytest -q`.

## Deployment (summary — details are PRIVATE)

RouteLens is self-hosted; production tracks `main`, the authenticated dev
instance tracks `dev`, and **publishing = `git push`** (auto-deploy, no manual
steps). ALL operational specifics — hosts, app/volume names, schedules, URLs,
auth, backup posture — live in `docs/private/deployment-vps-01.md`, which is
**gitignored because this repo is PUBLIC**. Read it at session start; never
copy its contents into tracked files. The platform side is owned by the
vps-platform session; infra changes go through Jim.

Contract for this repo: do not rename the Dockerfile targets (`web`,
`aggregator`) or the gunicorn entrypoint (`routelens.app:create_app()`), and
never commit DB files or secrets — deploys build straight from this repo.

## Guardrails

- Never commit secrets, tokens, `.env`, private keys, or live DB files.
- Do not touch Karen tenancy.
- Do not modify Proxmox/VM/DNS/TLS infrastructure unless Jim explicitly asks.
- Keep public `nexthop.engineer` apex resolving to `66.241.124.199`.
- For deployment changes, produce a test plan and rollback notes before applying.

## RouteLens 2.0 direction (agreed with Jim, 2026-07-14)

RouteLens pivoted from a static lab status page to a live "routing observatory":

- `/` is the **Pulse** page: browser connects directly to RIS Live
  (`wss://ris-live.ripe.net`), MapLibre dark map of 23 RIS collectors, live
  ticker + counters. Zero backend load for the live layer.
- `/q?query=` is the **looking glass**: classify prefix/IP/ASN/hostname
  (`query.py`), HTMX shell + panels from RIPEstat, RouteViews, NLNOG Ring,
  Globalping, Cloudflare Radar (`sources.py`, cached in SQLite `api_cache`).
- The Watchlist UI is removed for now; collector/store/resource pages remain.
- Design register: **utilitarian** (bgp.tools-style density, no glow). See
  PRODUCT.md before doing UI work. Design tokens live in base.html.
- `CLOUDFLARE_RADAR_TOKEN` env var enables the Radar panel (degrades gracefully).

## Approved dashboard roadmap (build one at a time, in order)

All ten approved by Jim 2026-07-14. Most need the **RIS Live aggregator**
(server-side stream consumer writing per-minute buckets to SQLite) — build it
with #1 and reuse it everywhere:

1. Collector activity league (busiest parts of the global Internet) — LIVE 2026-07-14.
   Refinement noted: subscribe to RIS_PEER_STATE and flag windows where a
   collector's peer session reset (table re-dump masquerades as an activity
   spike). Also consider normalising by peer count per collector.
2. ASN churn league (most active operators, named) — LIVE 2026-07-14, with
   distinct-prefix analysis (flappy/estate-wide patterns)
3. Prefix flap leaderboard — LIVE 2026-07-14 (>=8 events/hour flush threshold)
4. Origin-change monitor — LIVE 2026-07-14 (stability+confirmation heuristics,
   hourly dedupe, flip-flop vs moved classification; aggregator MemoryMax
   raised to 384M for the 400k-entry origin map)
5. RPKI scoreboard — LIVE 2026-07-14 (RouteViews-scored UK operators +
   top churners, hourly; Radar global panel token-gated)
6. Address-space league — LIVE 2026-07-14 (routelens-spacescan.timer, daily
   oneshot ingest of bgp.tools table.jsonl, per-ASN overlap-merged totals)
7. ASN profile pages — LIVE 2026-07-14 (/q ASN view: aggregator stats +
   RIPEstat prefixes + RouteViews RPKI + PeeringDB; index at
   /dashboards/asn-profiles)
8. Routing table growth tracker — LIVE 2026-07-14 (potaroo daily, cached)
9. Transit centrality — LIVE 2026-07-14 (middle-hop counts, prepend-dedup,
   share of observed paths, avg path length)
10. Country instability — LIVE 2026-07-14 (rollup of origin buckets by
    bgp.tools registration country, intensity = announcements/origin)

ALL TEN DASHBOARDS SHIPPED 2026-07-14. svc-01 now runs three units:
routelens.service (web), routelens-aggregator.service (RIS Live stream),
routelens-spacescan.timer (daily bgp.tools table ingest) — plus the original
routelens-collector.timer.

## UK / LINX focus (Jim, 2026-07-14)

Add a UK lens using LINX's public Alice-LG looking glasses (standard Alice REST
API, no auth — `/api/v1/status`, `/api/v1/routeservers`,
`/api/v1/lookup/prefix?q=<prefix>`):

- `https://alice-collector.linx.net/` — LINX collectors (LON1, LON2, regional;
  ~7M routes; route servers named e.g. COLLECTOR.LON1, COLLECTOR.MOM1)
- `https://alice-rs.linx.net/` — LINX route servers (RS1/RS2 per LAN)
- `https://alice-collector-center3.linx.net/` and
  `https://alice-rs-center3.linx.net/` — NOTE: these are LINX's Middle East
  exchanges (JED1/RIY1), not UK; verified 2026-07-14.

Planned use: a "UK view" panel on prefix pages (how LON1/LON2/Manchester/Wales
route servers see a prefix) and UK-specific activity dashboards.

## Publishing status

RouteLens is live and public at https://routelens.nexthop.engineer
(since 2026-07-15). Now that the audience is public:

- Mind upstream API rate limits (RIPEstat, RouteViews, bgp.tools, PeeringDB,
  Globalping) — the dashboard is no longer lab-only traffic.
- Cloudflare Radar data is CC BY-NC — keep the attribution visible.
- **This repo is PUBLIC**: operational/infra details belong in `docs/private/`
  (gitignored), never in tracked files. A security review (2026-07-15) found
  no leaked secrets but flagged infra detail leakage — keep it that way.
