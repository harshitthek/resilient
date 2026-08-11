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

### Dispatch stage (built; Gemini enabled)
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
issues land in the DB within seconds instead of waiting for the next cron
tick.

## Two things that will bite you if you don't handle them explicitly

**1. GitHub's Search API and the default Actions token don't mix.**
`secrets.GITHUB_TOKEN` that Actions auto-provides is scoped to the
repository the workflow lives in — it cannot search or read issues
across the rest of GitHub. You need a separate PAT (`DISCOVERY_GH_TOKEN`)
with `public_repo` scope. Easy to miss until the workflow fails silently
with a 403.

**2. Agents must only work on your fork.**
Dispatch creates or reuses a personal fork, creates its working branch
there, and gives the fork clone URL to Gemini. It never gives an agent an
upstream write target. Evaluation and submission remain separate, unbuilt
stages; dispatch does not open upstream PRs. Jules is deliberately disabled
until it has its own controlled validation.

## Edge cases this design accounts for

| Case | Risk if unhandled | How it's handled |
|---|---|---|
| Repo is archived | Wasted work on a dead project | Skipped at scan time (`is_archived` check); webhook also deactivates on `repository.archived` |
| Repo's docs forbid AI PRs | Spam complaint, account flagged | `check_ai_policy()` scans CONTRIBUTING.md / PR template; `disallowed` sets `is_active = FALSE`, no further scanning |
| Policy unclear either way | Assuming permission that wasn't given | Default is `unknown`, treated as "don't auto-submit" downstream, not as tacit yes |
| Someone already opened a PR for the issue | Duplicate/redundant bot PR | Deliberately **not** checked at discovery time — a Search API call per matching issue would blow the 30/min search limit across a full scan (600+ calls) and the answer can go stale before dispatch anyway. Checked once, at dispatch, right before an agent starts work |
| Issue closed or already handled while an agent is working on it | PR submitted against a dead issue | Same re-check, same reasoning — belongs in the dispatch/submit scripts (not in this drop yet), not at discovery time |
| GitHub Search API rate limit (30/min) hit | Job crashes or gets your token flagged | `gh_get()` backs off on 403/429 using `X-RateLimit-Reset` |
| Core REST rate limit (5000/hr) | Same | Same backoff path; `MAX_REPOS_PER_RUN` caps volume per run |
| `issues` endpoint also returns PRs | PRs miscounted as issues | Explicitly filtered out (`"pull_request" not in i`) |
| Re-running discovery on the same repo/issue | Duplicate rows | `ON CONFLICT ... DO UPDATE` upserts throughout |
| Repo renamed or transferred | Stale name breaks webhook repo lookups, which match on `full_name` | `github_id` (immutable) is the conflict key; `full_name` is refreshed on every upsert so lookups by name stay current |
| One repo's API call fails mid-scan | Whole run aborts, everything after it in the batch never gets scanned | Each repo is processed and committed independently; a failure rolls back just that repo and the run continues |
| Maintainer asks you to stop | Continued unwanted PRs | Manual `is_active = FALSE` on `repos` is respected everywhere immediately, no re-scan until manually re-enabled |
| Webhook payload spoofed | Fake issues injected into your queue | HMAC signature verified with `hmac.compare_digest` (constant-time) before any DB write |
| No tests in the repo (affects a later stage) | False confidence in a fix | Evaluation stage should treat `tests_passed = NULL` as lower-confidence, not as pass |

## Current status

| Stage | Status |
|---|---|
| Discovery | ✅ Built and reviewed |
| Dispatch | ✅ Built; Gemini-only execution is enabled, Jules is disabled pending validation |
| Evaluation | ✅ Built & Tested (40 unit tests passing) |
| Submission | ✅ Built & Tested (`scripts/submit.py`, GitHub App & PAT auth) |
| Leaderboard | 📋 Specified in `ROADMAP.md` |

See `CONTEXT.md` for design decisions and `ROADMAP.md` for the remaining
leaderboard work.
