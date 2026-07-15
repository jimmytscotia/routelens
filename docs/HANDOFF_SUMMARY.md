> **HISTORICAL (svc-01 era, pre-2026-07-15).** RouteLens now runs on vps-01 via Coolify — see `deployment-vps-01.md`.

# RouteLens development handoff summary

Date: 2026-07-14
Prepared by: Hermes on Mac Mini
Target developer: Claude Code in VS Code on Jim's MacBook Pro

## Current status

RouteLens is an operational Flask/Jinja/SQLite app deployed in the NextHop Lab.

- Deployed URL: `https://routelens.nexthop.engineer/`
- App VM: `svc-01`
- DNS: split-horizon `routelens.nexthop.engineer -> 100.94.135.62`
- TLS: Let's Encrypt cert includes `routelens.nexthop.engineer`
- App service: `routelens.service`, active during latest verification
- Collector timer: `routelens-collector.timer`, active during latest verification
- Current local tests: `18 passed`

## Source path on Mac Mini

```text
/Users/unsx-lab/projects/routelens
```

## Handoff files added

- `README.md` — project overview, local dev, smoke tests, current gaps
- `CLAUDE.md` — Claude Code project memory/instructions
- `docs/deployment_handoff.md` — exact MacBook/VS Code/Claude Code handoff steps
- `.gitignore` — excludes venv, runtime DB, caches, secrets

## Recommended MacBook path

```text
~/Projects/routelens
```

## Fast copy command from MacBook

```bash
mkdir -p ~/Projects
rsync -az --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'instance' \
  --exclude '*.db' \
  unsx-lab@100.83.203.12:/Users/unsx-lab/projects/routelens/ \
  ~/Projects/routelens/
cd ~/Projects/routelens
```

## First Claude Code task

```text
Read README.md, CLAUDE.md, docs/backend_design.md, and docs/deployment_handoff.md. Run `uv run pytest -q`. Then add BGP path visualisation to prefix resource detail pages using strict TDD. Do not touch deployment infrastructure or secrets.
```
