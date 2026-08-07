# Resilient — AI repo-improvement & agent-leaderboard pipeline

## Files

### Discovery stage (built)
- `schema.sql` — full data model (covers all stages)
- `scripts/discover.py` — scheduled discovery job (finds trending repos, checks AI policy, pulls candidate issues)
- `.github/workflows/discover.yml` — runs discovery every 3 hours
- `webhook_receiver.py` — near-real-time issue discovery for repos already being tracked
- `scripts/requirements.txt` — dependencies for the discovery job
- `requirements-webhook.txt` — dependencies for the webhook receiver (separate deployable; use gunicorn in production)
- `.env.example` — all required environment variables

### Dispatch stage (specified, not yet built)
- `agents/base.py` — abstract agent adapter + `RepoContext`/`RunResult` dataclasses
- `agents/jules_adapter.py` — Jules `v1alpha` REST API integration (async, fire-and-poll)
- `agents/gemini_agent.py` — Gemini 2.5 Pro/Flash function-calling coding agent (sync)
- `scripts/dispatch.py` — dispatch orchestrator (polls pending runs, then dispatches new issues)
- `scripts/github_utils.py` — shared GitHub API utilities (extracted from discover.py)
- `scripts/requirements-dispatch.txt` — dispatch dependencies
- `.github/workflows/dispatch.yml` — runs dispatch every 8 hours

### Documentation
- `CONTEXT.md` — what exists, why, and every key design decision
- `ROADMAP.md` — full specification of all four stages + leaderboard

## Setup

Copy `.env.example` to `.env` and fill it in.

**For GitHub Actions**, set these as repo secrets:
- `DISCOVERY_GH_TOKEN` — PAT with `public_repo` scope (discovery)
- `DISPATCH_GH_TOKEN` — PAT with `repo` scope (dispatch — fork + push)
- `JULES_API_KEY` — from `jules.google.com/settings`
- `GEMINI_API_KEY` — from Google AI Studio
- `DATABASE_URL` — Postgres connection string

See `.github/workflows/discover.yml` and `.github/workflows/dispatch.yml`
for which secrets each job uses.

## Why two discovery paths (cron + webhook)

"Trending" is inherently something you compute periodically — there's no
event to subscribe to for "this repo just became popular." So the cron
job in `discover.py` handles finding *new* candidate repos, snapshotting
star counts so a future run can compute delta/trending.

But once a repo is already in the `repos` table, polling it every 3 hours
for new issues is wasteful and slow. `webhook_receiver.py` is what a
GitHub App installed on tracked repos would call — new or newly-labeled
