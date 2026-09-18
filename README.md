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

### Optional environment variables

| Variable | Effect when unset |
|---|---|
| `CARTO_BASEMAP_KEY` | Map tiles are watermarked "API KEY REQUIRED" — CARTO began requiring a key for their basemaps in 2026. A free key (5M tiles/month) comes from <https://carto.com/basemaps/apikey>; it is public and browser-visible by design, so restrict it to your own domain rather than treating it as a secret. |
| `CLOUDFLARE_RADAR_TOKEN` | Cloudflare Radar panels are hidden. |
| `MISTRAL_API_KEY` | Internet Weather briefings are not generated. |
| `ROUTELENS_CANONICAL_ORIGIN` | No canonical-host redirect; the app serves whatever hostname it receives. |

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
curl -fsS https://routelens.net/healthz
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

1. Add BGP path visualisation on prefix detail pages.
2. Add DNS public/private comparison panels.
3. Add a safe “run checks now” UI button or authenticated admin route.
4. Polish responsive UI and take product screenshots.
5. Add CI to run `pytest` on pull requests before merge.

## Guardrails

- Do not commit secrets, tokens, real `.env` files, private keys or database files.
- Do not rename the Dockerfile targets (`web`, `aggregator`) or the gunicorn
  entrypoint (`routelens.app:create_app()`) — deployments build from this repo.
- Be a good citizen of the upstream APIs: cache responses, poll politely, and
  keep the attribution that Cloudflare Radar (CC BY-NC) and the academic
  services (IODA, GRIP) require.

## License

RouteLens source code is released under the **MIT License** — see [`LICENSE`](LICENSE).

Two caveats, detailed in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md):

- The **"RouteLens" name and logo are not covered** by the MIT licence (all
  rights reserved). Fork the code freely; use your own name and mark.
- The app relies on **third-party data sources with their own terms**. The code
  licence does not grant rights to that data. In particular, **Cloudflare Radar
  data is CC BY-NC (non-commercial)** and **IODA/GRIP are for academic/
  educational use** — review the notices before any commercial deployment.
