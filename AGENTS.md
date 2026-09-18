# AGENTS.md — working on RouteLens

Guidance for humans and coding agents working in this repository. It describes
how the code is put together and the conventions to follow; it deliberately
contains nothing about any particular deployment.

RouteLens is a Flask/Jinja/SQLite **routing observatory**: it streams live BGP
activity from RIPE RIS, aggregates it into per-minute buckets, and presents
dashboards plus a multi-source looking glass for any prefix, IP, ASN or
hostname.

## Product intent

A credible network-engineering tool, not a toy demo. The audience is technical —
network engineers, NOC and infrastructure people, researchers — and they judge
in the first thirty seconds whether this is a real operator's tool. Density and
accuracy beat decoration.

Read **PRODUCT.md** before doing UI work: it holds the design register, brand
personality, anti-references and accessibility rules. Design tokens live in
`src/routelens/templates/base.html`; the site is dark-first with an Auto / Dark /
Light switch.

## Architecture

Flask app factory, stdlib `sqlite3`, no ORM. Two long-running processes share
one SQLite database: the **web** app and the **aggregator**.

| Path | Role |
|---|---|
| `src/routelens/app.py` | App factory, routes, config, context processors |
| `src/routelens/store.py` | SQLite repository — all SQL lives here |
| `src/routelens/aggregator.py` | RIS Live websocket consumer → per-minute buckets |
| `src/routelens/collector.py`, `checks.py`, `checkers.py` | Scheduled DNS/HTTP/TLS checks |
| `src/routelens/sources.py` | Upstream API clients, cached in the `api_cache` table |
| `src/routelens/query.py` | Classifies a looking-glass query (prefix/IP/ASN/hostname) |
| `src/routelens/dashboards.py` | Dashboard registry + sidebar navigation |
| `src/routelens/weather.py`, `ai.py` | Anomaly pre-filter → AI briefing generation |
| `src/routelens/ripestat.py`, `spacescan.py`, `companies.py`, `countries.py`, `uk.py`, `collectors.py` | Data sources and reference data |
| `src/routelens/templates/` | Jinja templates |
| `tests/` | pytest suite |

Keep stdlib SQLite. Do not introduce SQLAlchemy or a client/server database
without a deliberate decision — the schema and access patterns are built around
a single file with short-lived connections.

### Design notes worth knowing

- **The live layer costs the backend nothing.** The Pulse page connects the
  browser straight to `wss://ris-live.ripe.net`. The aggregator is a separate
  consumer that exists to build history, not to serve the live view.
- **Maps use Leaflet, not MapLibre**, because MapLibre needs WebGL, which is
  unavailable with GPU acceleration off or over some remote desktops.
- **Every upstream source degrades gracefully.** A slow or dead source must
  render as a labelled gap, never a broken page, and an unset API key must mean
  "not configured", never a crash.
- **Cache upstream calls** in the `api_cache` table and poll politely: these are
  public goods (RIPEstat, RouteViews, NLNOG Ring, Globalping, bgp.tools,
  PeeringDB, IODA, GRIP, potaroo) and several are academic or volunteer-run.

## Commands

Uses [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync
uv run pytest -q
ROUTELENS_DATABASE=instance/routelens.db uv run python -m routelens.cli --json
ROUTELENS_DATABASE=instance/routelens.db uv run flask --app routelens.app:create_app run --debug --port 8097
```

Current passing baseline: **254 passed**.

Local quirk: `uv sync` does not install the package itself (no `[build-system]`
in `pyproject.toml`), so `flask run` and `python -m routelens.cli` need
`PYTHONPATH=src`. pytest works without it (`pythonpath = ["src"]`).

## TDD expectations

Strict TDD for new behaviour:

1. Add or update a test first.
2. Run that test and confirm it fails **for the expected reason**.
3. Implement the smallest change that works.
4. Re-run that test.
5. Run the full suite with `uv run pytest -q`.

## Configuration

All configuration is environment variables; every one is optional and the app
runs without them. See the table in README.md for what each does when unset.
Attribution obligations ride along with two of them: Cloudflare Radar data is
CC BY-NC, and IODA/GRIP are academic services — keep their credits visible.

## Deployment contract

The repo builds and deploys straight from source, so:

- Do not rename the Dockerfile targets (`web`, `aggregator`).
- Do not change the gunicorn entrypoint (`routelens.app:create_app()`).
- Never commit database files, secrets, tokens, `.env` files or private keys.
- `/healthz` must stay cheap and dependency-free — it is a container probe.

## A note for the maintainer's own tooling

This repository is public and the documentation above is written for anyone
reusing the code. Operator-specific material — hosts, URLs, credentials,
roadmap decisions, incident history — belongs in `docs/private/`, which is
gitignored. If `docs/private/operations.md` exists in your working copy, read it
at session start; if it does not, you are not missing anything needed to build,
test or run RouteLens.
