# RouteLens

RouteLens is a Flask/Jinja/SQLite live network observability tool for a technical audience interested in investigating the live status of core parts of the Internet. It streams real-time BGP activity, offers a multi-source looking glass for any prefix/IP/ASN/hostname, and renders a dense, dark operations dashboard.

## Deployment

RouteLens runs self-hosted on a UK VPS behind a reverse proxy with automatic
TLS. Production tracks `main`; a separate authenticated dev instance tracks
`dev`. Deploys are automatic on push (no manual steps). Operational details
live outside this public repo (`docs/private/`, untracked).

## Development workflow (branch → dev → main)

1. Branch from `dev` (or commit small changes to `dev` directly).
2. Push to `dev` → the dev instance redeploys automatically.
3. Verify on the dev instance (it has its own scratch database).
4. Merge `dev` → `main` → production redeploys automatically.

## Stack

- Python 3.11+
- Flask + Jinja2
- SQLite via stdlib `sqlite3`
- `requests`
- `dnspython`
- `gunicorn`
- `pytest`
- `uv` for local development dependency management

## Local development

```bash
uv sync
uv run pytest -q
ROUTELENS_DATABASE=instance/routelens.db uv run python -m routelens.cli --json
ROUTELENS_DATABASE=instance/routelens.db uv run flask --app routelens.app:create_app run --debug --port 8097
```

Open:

```text
http://127.0.0.1:8097/
```

## Smoke tests

```bash
uv run pytest -q
ROUTELENS_DATABASE=instance/routelens.db uv run python -m routelens.cli
curl -fsS http://127.0.0.1:8097/healthz
```

Expected current test result at handoff:

```text
18 passed
```

## Health check

```bash
curl -fsS https://routelens.nexthop.engineer/healthz
```

Expected:

```json
{"service":"routelens","status":"ok"}
```

## Main source files

| Path | Purpose |
|---|---|
| `src/routelens/app.py` | Flask app factory and routes |
| `src/routelens/store.py` | SQLite schema/repository |
| `src/routelens/collector.py` | Runs relevant checks per resource |
| `src/routelens/checks.py` | DNS, HTTP, TLS checks |
| `src/routelens/ripestat.py` | RIPEstat BGPlay fetch/summarise |
| `src/routelens/insights.py` | Health classification logic |
| `src/routelens/templates/` | Dashboard/detail Jinja templates |
| `tests/` | pytest suite |
| `docs/` | Design/deployment handoff docs |

## Current gaps / next development targets

1. ~~MacBook/client DNS ergonomics~~ — resolved by the 2026-07-15 VPS cutover.
2. Add BGP path visualisation on prefix detail pages.
3. Add DNS public/private comparison panels.
4. Add a safe “run checks now” UI button or authenticated admin route.
5. ~~Deployment automation to svc-01~~ — obsolete; Coolify push-to-deploy replaced it.
6. Polish responsive UI and take product screenshots.
7. Add GitHub Actions CI (repo is on GitHub; run `pytest` on PRs before merge to `dev`/`main`).

## Guardrails

- Do not commit secrets or real `.env` files.
- Do not touch Karen tenancy.
- Do not modify Proxmox host/VM infrastructure unless the admin explicitly asks.
- RouteLens can safely read public APIs and lab service endpoints.
- Keep `nexthop.engineer` public apex pointing at `66.241.124.199`.
