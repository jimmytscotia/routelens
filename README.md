# RouteLens

RouteLens is a Flask/Jinja/SQLite network-health dashboard for the NextHop Lab blog demo. It compares public DNS, private lab DNS, HTTP health, TLS certificate posture, and RIPEstat BGP visibility, then renders a polished dark operations dashboard.

## Current deployed service

| Item | Value |
|---|---|
| URL | `https://routelens.nexthop.engineer/` |
| Runtime VM | `svc-01` |
| App path on VM | `/opt/routelens` |
| SQLite DB on VM | `/var/lib/routelens/routelens.db` |
| Gunicorn bind | `127.0.0.1:8097` |
| systemd service | `routelens.service` |
| collector timer | `routelens-collector.timer`, every 15 minutes |
| Caddy ingress | `routelens.nexthop.engineer -> 127.0.0.1:8097` |
| Split-DNS | `routelens.nexthop.engineer -> 100.94.135.62` via `net-01` |

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

## Important lab access notes

The MacBook Pro is on Tailscale, but it may not use `net-01` as its DNS resolver by default. If `routelens.nexthop.engineer` does not resolve from the MacBook, test with:

```bash
curl --resolve routelens.nexthop.engineer:443:100.94.135.62 https://routelens.nexthop.engineer/healthz
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

1. Improve MacBook/client DNS ergonomics for `routelens.nexthop.engineer`.
2. Add BGP path visualisation on prefix detail pages.
3. Add DNS public/private comparison panels.
4. Add a safe “run checks now” UI button or authenticated admin route.
5. Add deployment automation script from repo to `svc-01`.
6. Polish responsive UI and take blog-ready screenshots.
7. Add GitHub Actions CI once the repo is pushed to GitHub.

## Guardrails

- Do not commit secrets or real `.env` files.
- Do not touch Karen tenancy.
- Do not modify Proxmox host/VM infrastructure unless Jim explicitly asks.
- RouteLens can safely read public APIs and lab service endpoints.
- Keep `nexthop.engineer` public apex pointing at `66.241.124.199`.
