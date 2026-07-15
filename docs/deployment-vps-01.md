# Deployment: vps-01 (Coolify) — the CURRENT production home

> Written 2026-07-15 by the vps-platform Claude session after migrating
> RouteLens from svc-01 to the OVH VPS. README.md and CLAUDE.md were updated
> the same day; this file is the canonical deployment reference.

## Where RouteLens runs now

| Item | Value |
|---|---|
| Production URL | https://routelens.nexthop.engineer/ — **public** (Jim approved) |
| Dev URL | https://routelens-dev.nexthop.engineer/ — basic auth (user `jim`, password in Jim's password manager) |
| Host | vps-01.nexthop.engineer (OVH VPS, London) — Coolify v4 manages everything |
| Build | `Dockerfile` in this repo (multi-target; `uv sync`; `PYTHONPATH=/app/src`) |
| Web (prod) | Coolify app `routelens-web`, target `web`, branch `main`, gunicorn :8080, 1g mem limit |
| Aggregator (prod) | Coolify app `routelens-aggregator`, target `aggregator`, branch `main`, 384m mem limit, no domain |
| Dev | Coolify app `routelens-dev`, target `web`, branch **`dev`**, 512m; own volume; aggregator NOT run in dev |
| SQLite | named Docker volume `routelens-data` → `/var/lib/routelens/routelens.db` (dev: `routelens-dev-data`). Historic DB from svc-01 imported 2026-07-15 (integrity-checked; 1.67M ris_asn_activity rows) |
| Collector | Coolify Scheduled Task in the web container: `python -m routelens.cli`, `*/15 * * * *` (same on dev) |
| Spacescan | Coolify Scheduled Task (prod only): `python -m routelens.spacescan`, `40 4 * * *` |
| Env | `ROUTELENS_RETENTION_DAYS=7`; `ROUTELENS_DATABASE` baked into the image env |
| TLS | wildcard `*.nexthop.engineer` Let's Encrypt via Traefik (automatic, nothing to manage) |
| Backups | nightly whole-VPS restore point (OVH) + the SQLite file lives on the `routelens-data` volume — app-level dump-to-S3 for SQLite apps is on the platform's open-items list |

## The development workflow (NEW — this replaces deploy-to-svc-01)

1. Work on a feature branch (or directly on `dev` for small things).
2. Push/merge to **`dev`** → auto-deploys to https://routelens-dev.nexthop.engineer in ~15-60s.
3. Verify there (basic auth). Dev has its own SQLite DB — safe to break.
4. Merge `dev` → **`main`** → production auto-deploys. That's the whole release process.
5. PR preview deployments are also enabled on the GitHub App if you open PRs.

## Split-DNS checks

Still work: the VPS is on Jim's tailnet, and containers can reach the lab DNS
(`net-01`, 100.88.168.126) — verified with a live query during migration.

## Legacy (svc-01) — DO NOT build on this

The old systemd deployment on svc-01 (`/opt/routelens`, Caddy, the units in
`deploy/`) is retired-in-place: the lab split-DNS record was removed on
2026-07-15 (Hermes), so ALL clients — lab and public — now reach vps-01.
svc-01's routelens services still run but serve nobody; stopping/removing them
is a pending lab housekeeping task (Hermes). Treat `deploy/*.service|timer` as historical
artefacts of that setup; their resource limits informed the Coolify limits.
README gap "deployment automation to svc-01" is obsolete — Coolify replaced it.
