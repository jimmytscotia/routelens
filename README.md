# RouteLens

RouteLens is a Flask/Jinja/SQLite network-health dashboard for the NextHop Lab blog demo. It compares public DNS, private lab DNS, HTTP health, TLS certificate posture, and RIPEstat BGP visibility, then renders a polished dark operations dashboard.

## Current deployed service (vps-01 / Coolify — since 2026-07-15)

| Item | Value |
|---|---|
| Production URL | `https://routelens.nexthop.engineer/` — **public**, branch `main` |
| Dev URL | `https://routelens-dev.nexthop.engineer/` — basic auth (`jim` / password manager), branch `dev` |
| Host | `vps-01.nexthop.engineer` (OVH VPS, London), managed by Coolify v4 |
| Build | `Dockerfile` (multi-target: `web`, `aggregator`), built by Coolify on push |
| Web (prod) | Coolify app `routelens-web`, gunicorn `:8080`, 1g memory limit |
| Aggregator (prod) | Coolify app `routelens-aggregator` (RIS Live daemon), 384m limit |
| SQLite DB | Docker volume `routelens-data` → `/var/lib/routelens/routelens.db` (dev: `routelens-dev-data`) |
| Collector | Coolify scheduled task `python -m routelens.cli`, every 15 min (prod + dev) |
| Spacescan | Coolify scheduled task `python -m routelens.spacescan`, daily 04:40 UTC (prod only) |
| TLS | automatic — wildcard `*.nexthop.engineer` cert via Traefik/Let's Encrypt |
| DNS | public wildcard AND lab DNS both resolve to vps-01 (split-DNS record retired 2026-07-15) |

Full deployment detail: `docs/deployment-vps-01.md`. The old svc-01/systemd
deployment is retired-in-place (see Legacy note in that doc).

## Development workflow (branch → dev → main)

1. Branch from `dev` (or commit small changes to `dev` directly).
2. Push to `dev` → auto-deploys to the dev URL in under a minute.
3. Verify at `https://routelens-dev.nexthop.engineer/` (basic auth; own scratch DB).
4. Merge `dev` → `main` → production auto-deploys. No other release steps exist.
5. PR preview deployments are enabled via the GitHub App for feature-branch PRs.

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

(DNS quirks are gone: public and lab DNS now both resolve this hostname to vps-01.)

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
6. Polish responsive UI and take blog-ready screenshots.
7. Add GitHub Actions CI (repo is on GitHub; run `pytest` on PRs before merge to `dev`/`main`).

## Guardrails

- Do not commit secrets or real `.env` files.
- Do not touch Karen tenancy.
- Do not modify Proxmox host/VM infrastructure unless Jim explicitly asks.
- RouteLens can safely read public APIs and lab service endpoints.
- Keep `nexthop.engineer` public apex pointing at `66.241.124.199`.
