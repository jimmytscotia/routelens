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
18 passed
```

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

## Recommended next tasks

1. Add BGP path visualisation for prefix resources using stored `sample_paths` from RIPEstat.
2. Add richer DNS comparison panels showing public answers vs private answers.
3. Add an admin-only/manual “run checks now” action, or document why it is deferred.
4. Add a deploy script that rsyncs source to `svc-01`, reinstalls, runs tests, restarts services, and verifies Caddy health.
5. Add screenshots/blog evidence notes under `docs/`.
6. Push to GitHub and add CI.
