# RouteLens MacBook + Claude Code handoff

This document is for continuing RouteLens development from Claude Code inside Visual Studio Code on Jim's MacBook Pro.

## 1. Get the source onto the MacBook

Preferred long-term path: push this project to GitHub and clone it on the MacBook.

Fast lab handoff path from the MacBook, assuming SSH access to the Mac Mini:

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

If the MacBook has an SSH alias for the Mini, replace `unsx-lab@100.83.203.12` with that alias.

Alternative: copy the archive prepared by Hermes:

```bash
scp unsx-lab@100.83.203.12:/Users/unsx-lab/.hermes/artifacts/routelens-handoff.tar.gz ~/Downloads/
mkdir -p ~/Projects/routelens
cd ~/Projects/routelens
tar -xzf ~/Downloads/routelens-handoff.tar.gz --strip-components=1
```

## 2. Open in VS Code

```bash
cd ~/Projects/routelens
code .
```

Recommended VS Code extensions:

- Python
- Pylance
- Ruff, optional later
- Claude Code extension / Claude Code terminal integration

## 3. Install tools on the MacBook

Check/install `uv`:

```bash
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
```

Check Claude Code:

```bash
claude --version
claude auth status --text || claude auth login
claude doctor
```

If Claude Code is missing:

```bash
npm install -g @anthropic-ai/claude-code
claude auth login
```

## 4. Bootstrap project locally

```bash
cd ~/Projects/routelens
uv sync
uv run pytest -q
```

Expected baseline:

```text
18 passed
```

Populate a local dev DB:

```bash
ROUTELENS_DATABASE=instance/routelens.db uv run python -m routelens.cli --json
```

Run the app locally:

```bash
ROUTELENS_DATABASE=instance/routelens.db uv run flask --app routelens.app:create_app run --debug --port 8097
```

Open:

```text
http://127.0.0.1:8097/
```

## 5. Verify the deployed lab app from the MacBook

Try normal DNS first:

```bash
dig routelens.nexthop.engineer +short
curl -fsS https://routelens.nexthop.engineer/healthz
```

If normal DNS does not resolve because the MacBook is not using lab split-DNS, test with explicit Tailscale ingress resolution:

```bash
curl --resolve routelens.nexthop.engineer:443:100.94.135.62 \
  https://routelens.nexthop.engineer/healthz
```

Expected:

```json
{"service":"routelens","status":"ok"}
```

## 6. Recommended first Claude Code prompt

Paste this into Claude Code from the project root:

```text
You are taking over development of RouteLens. First read README.md, CLAUDE.md, docs/backend_design.md, and docs/deployment_handoff.md. Then inspect the code and run `uv run pytest -q`.

Goal for this session:
1. Confirm the current baseline and summarize architecture.
2. Add a BGP path visualisation section to prefix resource detail pages using the latest stored BGP check `details.sample_paths` data.
3. Follow strict TDD: write a failing test first, run it, implement, then run the full suite.
4. Keep the Flask/Jinja/SQLite stack. Do not introduce new frameworks.
5. Do not modify deployment infrastructure or secrets.
6. At the end, report changed files, tests run, and any follow-up tasks.
```

## 7. Deployment workflow for later

Current manual deployment shape from a machine with SSH to `svc-01` as `lab`:

```bash
rsync -az --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'instance' \
  --exclude '*.db' \
  ./ lab@svc-01:/opt/routelens/

ssh lab@svc-01 '
  set -e
  cd /opt/routelens
  .venv/bin/pip install .
  ROUTELENS_DATABASE=/var/lib/routelens/routelens.db .venv/bin/python -m routelens.cli --json >/tmp/routelens-check.json
  sudo systemctl restart routelens.service
  curl -fsS http://127.0.0.1:8097/healthz
'
```

Before turning this into a one-command deploy script, add safety checks and rollback notes.

## 8. Current deployment inventory

| Item | Value |
|---|---|
| Runtime VM | `svc-01` |
| Runtime user | `lab` |
| App path | `/opt/routelens` |
| DB path | `/var/lib/routelens/routelens.db` |
| App systemd unit | `routelens.service` |
| Collector systemd timer | `routelens-collector.timer` |
| Caddy host | `routelens.nexthop.engineer` |
| Caddy upstream | `127.0.0.1:8097` |
| Tailscale ingress IP | `100.94.135.62` |
| DNS server | `net-01` / `100.88.168.126` |
| Split-DNS record | `routelens.nexthop.engineer A 100.94.135.62` |

## 9. Known issues / pitfalls

- The MacBook may not resolve split-DNS names unless Tailscale DNS is configured to use `net-01`; use `curl --resolve` for validation if needed.
- Do not commit `instance/routelens.db`; it is a runtime artifact.
- The current CSS lives inline in `templates/base.html`; refactor only if tests and visual QA are preserved.
- Certbot DNS-01 needed `--dns-cloudflare-propagation-seconds 60`; shorter propagation failed during deployment.
- Flask package data must include `templates/*.html`; otherwise installed Gunicorn deployment throws `TemplateNotFound`.
