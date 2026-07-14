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

## Current deployment facts

RouteLens is deployed on `svc-01`:

- App path: `/opt/routelens`
- DB: `/var/lib/routelens/routelens.db`
- systemd app service: `routelens.service`
- systemd collector timer: `routelens-collector.timer`
- Gunicorn: `127.0.0.1:8097`
- Caddy host: `https://routelens.nexthop.engineer/`
- Split-DNS A record: `routelens.nexthop.engineer -> 100.94.135.62`
- Let’s Encrypt SAN includes `routelens.nexthop.engineer`

SSH for deployment checks, if Jim has provided keys on the MacBook:

```bash
ssh lab@svc-01
ssh lab@net-01
```

The working SSH identity from Hermes is named `nexthop_vm_admin`, but do not assume it exists on the MacBook unless Jim copied it there.

## DNS note

The MacBook is on Tailscale, but may not use `net-01` as DNS. If normal DNS fails, test RouteLens with explicit resolution:

```bash
curl --resolve routelens.nexthop.engineer:443:100.94.135.62 https://routelens.nexthop.engineer/healthz
```

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

1. Collector activity league (busiest parts of the global Internet)
2. ASN churn league (most active operators, named — Zayo/Vodafone/Sky/Google)
3. Prefix flap leaderboard
4. Origin-change monitor (block movements, hijack/migration candidates)
5. RPKI scoreboard
6. Address-space league (who owns the Internet, bgp.tools table dump)
7. ASN profile pages
8. Routing table growth tracker (RIPEstat historical, cheap win)
9. Transit centrality (who carries the Internet)
10. Country instability map

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

## Publishing intent

Once Jim is happy with the lab build, RouteLens will be published publicly on
https://nexthop.engineer (that site lives at ~/Developer/personal/nexthop-engineer,
Flask on Fly.io). Get explicit sign-off before any public deploy; mind API
rate limits and the Radar CC BY-NC attribution when the audience becomes public.
