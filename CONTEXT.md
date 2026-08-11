# Context — what exists and why

This document is for anyone picking up the codebase (including future-you).
It explains what's already built, what isn't, and the decisions that shaped
the current code — including several that were made *after* an initial code
review caught real bugs and one case where a reviewer's suggested fix would
have introduced a new crash.

## What's built

### Discovery stage (complete)

Discovery is the first stage of a four-stage pipeline
(discover → dispatch → evaluate → submit).

### Files

| File | Purpose |
|---|---|
| `schema.sql` | Full Postgres data model — covers all four stages, not just discovery |
| `scripts/discover.py` | Scheduled cron job: finds trending repos, checks AI policy, pulls candidate issues |
| `.github/workflows/discover.yml` | Runs `discover.py` every 3 hours via GitHub Actions |
| `webhook_receiver.py` | Flask app: near-real-time issue ingestion for repos already being tracked |
| `scripts/requirements.txt` | Python deps for the cron job (requests, psycopg2-binary) |
| `requirements-webhook.txt` | Python deps for the webhook service (flask, psycopg2-binary, gunicorn) |
| `.env.example` | Template for the three required environment variables |

### Dispatch stage (complete; Multi-Model & Free-Tier Priority)

| File | Purpose |
|---|---|
| `scripts/dispatch.py` | Polls/recovers runs, validates live issue state and policies, dispatches AI agents to fork branches |
| `scripts/github_utils.py` | Rate-limited GitHub API helpers, policy checks, fork creation, and safe branch creation |
| `agents/base.py` | Adapter contract and shared repository/run data classes |
| `agents/gemini_agent.py` | Synchronous Gemini 2.5 Flash / Pro agent (100% Free Tier via Google AI Studio) |
| `agents/openrouter_agent.py` | Synchronous OpenRouter Agent (100% Free Tier: Qwen 2.5 Coder 32B Free, DeepSeek R1 Free) |
| `agents/qwen_agent.py` | Synchronous Qwen 2.5 Coder SOTA Open-Source Coding Agent |
| `agents/groq_agent.py` | Synchronous Groq Cloud Agent (100% Free High-Speed Cloud Tier) |
| `agents/ollama_agent.py` | Synchronous Ollama Agent (100% Free Local Open-Source Models) |
| `agents/openai_agent.py` | Optional OpenAI Agent (GPT-4o, O3-Mini) |
| `agents/claude_agent.py` | Optional Anthropic Claude Agent (Claude 3.7 / 3.5 Sonnet) |
| `agents/deepseek_agent.py` | Optional DeepSeek Agent (DeepSeek-Coder) |
| `agents/jules_adapter.py` | Implemented adapter retained for future validation |
| `.github/workflows/dispatch.yml` | Multi-model scheduled/manual dispatch workflow |

### Why two discovery paths

"Trending" can only be computed periodically — there's no GitHub event for
"this repo just got popular." So `discover.py` runs on a cron to find *new*
candidate repos by snapshotting star counts (the `stars` / `stars_prev`
columns enable delta/trending computation after at least two snapshots).

But once a repo is tracked, polling it every 3 hours for new issues is
wasteful. `webhook_receiver.py` handles that: install a GitHub App on
tracked repos, point its webhook here, and new/labeled issues land in the
DB within seconds.

### What discovery does NOT do

Discovery is strictly read-only. It does not:

- Fork repos
- Dispatch agents
- Open PRs or issues
- Check whether an issue already has a linked PR (see below)

## Key decisions and why they were made

These aren't arbitrary — each one came out of a real bug, a review finding,
or an architectural trade-off.

### `has_linked_pr` is checked at dispatch, not discovery

The initial design checked for linked PRs at discovery time, per issue.
This costs one GitHub Search API call per matching issue. Across a full
scan (60 repos × ~10 matching issues each), that's ~600 search calls
against a 30 requests/minute limit — 20 minutes of rate-limit-throttled
waiting in a job with a 15-minute timeout.

More importantly, the answer goes stale: an issue with no PR at discovery
time might have one by dispatch time (hours later), and vice versa. So
the check was removed from discovery entirely and deferred to the dispatch
stage, where it runs once, right before an agent starts work. This also
eliminated the inconsistency where the cron path checked but the webhook
path didn't.

### `gh_get()` returns 404 instead of raising

The rate-limit-aware wrapper `gh_get()` originally called
`raise_for_status()` on anything outside 403/429. A code review suggested
routing `check_ai_policy()` through `gh_get()` to get rate-limit backoff
on those calls too — but applying that literally would have crashed the
job, because most repos don't have all three candidate policy files
(CONTRIBUTING.md, .github/CONTRIBUTING.md, .github/PULL_REQUEST_TEMPLATE.md),
and a 404 on a missing file is expected, not an error.

Fix: `gh_get()` now treats 404 as a legitimate response (returns it
instead of raising), so `check_ai_policy()` can use it safely.

### Labels: original case stored, lowercase for comparison

The cron path (`discover.py`) stores labels in their original GitHub case.
The webhook path initially lowercased them before storing. This meant the
same label could be stored as `"Help Wanted"` or `"help wanted"` depending
on which path wrote it last.

Fix: both paths now store original case. Lowercasing happens only for the
set-intersection check against `TARGET_LABELS`.

### `full_name` is updated on every upsert

`github_id` is the immutable conflict key (survives renames/transfers),
but the initial upsert's `ON CONFLICT DO UPDATE` clause didn't include
`full_name`. After a repo rename, the DB would be stuck with the old name
— and worse, the webhook receiver looks repos up *by* `full_name`, so a
renamed repo would silently stop matching incoming webhooks.

Fix: `full_name = EXCLUDED.full_name` is now in the update clause.

### Per-repo transaction isolation

The initial `main()` had a single connection with no error handling. If
any repo failed (API hiccup, malformed response), the entire run aborted
and the connection leaked.

Fix: each repo is processed in its own try/except. Success → commit.
Failure → rollback that repo, log it, continue to the next. The
connection is wrapped in try/finally.

### Separate requirements files

The webhook receiver is a persistent service (run under gunicorn), not
something the Actions job installs. It needs flask and gunicorn; the cron
job doesn't. Separate `requirements.txt` files keep the two deployables
independent.

### `unknown` policy ≠ `disallowed`

`check_ai_policy()` returns `'unknown'` when no CONTRIBUTING.md or PR
template mentions AI contributions either way. This is treated as
**"don't auto-submit PRs"** downstream — but it is NOT the same as
`disallowed`:

- `disallowed` → sets `is_active = FALSE`, stops all scanning and agent
  work on that repo
- `unknown` → agents can still run (for leaderboard data), just nothing
  gets submitted upstream

This distinction matters for the leaderboard: you want agents exercised
on as many real issues as possible, even if you can't submit the result.

## Dispatch stage implementation decisions

These decisions were made during dispatch planning, before implementation.

### Agent API research: what's actually available

Before designing the adapter layer, we researched how each target agent
can be invoked programmatically:

- **Jules** has a `v1alpha` REST API at `jules.googleapis.com`. Tasks
  are created via POST `/v1alpha/sessions` and run asynchronously on
  Google Cloud VMs. You poll for completion. Free tier: 15 tasks/day,
  3 concurrent.
- **Gemini 2.5 Pro / Flash** are accessible through the `google-genai`
  SDK with function calling. The agent loop runs synchronously: clone
  repo → read files → reason → edit → test → commit. Free tier: ~5 RPM
  / ~100 RPD for Pro, ~15 RPM / ~1500 RPD for Flash.
- **MCP (Model Context Protocol)** is a tool protocol, not an agent.
  It provides standardized tool servers (filesystem, git, GitHub) that
  an LLM can call. Useful as the tool layer *under* a Gemini agent,
  not a standalone agent.

### Why an adapter abstraction instead of direct API calls

Jules and Gemini have fundamentally different execution models:

- **Jules is async (fire-and-poll):** its adapter is implemented but
  intentionally disabled until a dedicated controlled validation is complete.
- **Gemini is sync (inline agent loop):** `dispatch()` blocks while
  the agent reads code, reasons, and edits. Returns the final status
  when done (typically under 5 minutes).

An abstract `AgentAdapter` base class with `dispatch()` and `poll()`
methods lets the orchestrator handle both without caring which pattern
a given agent uses. Adding a new agent means writing one adapter file,
not touching the orchestrator.

### Fork always, never target upstream

This was called out in the original README as warning #2, and the
dispatch plan enforces it architecturally: `ensure_fork()` runs before
any agent dispatch, and the `RepoContext` passed to agents contains
the fork URL, never the upstream URL. Jules's `sourceContext` and
Gemini's clone target both point at the fork.

This is critical because Jules (and potentially other agents) auto-create
PRs against whatever repo they work on. If that's upstream, unreviewed
code lands directly on the real project.

### Shared GitHub utilities (`github_utils.py`)

`discover.py` and `dispatch.py` both need `gh_get()`, `check_ai_policy()`,
and related GitHub API helpers. Rather than duplicating or making
`discover.py` importable (it's a script, not a library), the common
functions are extracted into `scripts/github_utils.py`. Both scripts
import from it.

### Dispatch polls first, then dispatches new

Every invocation of `dispatch.py` does two things in order:
1. **Poll and detect stale runs.** Check all `status IN ('pending',
   'running')` rows. Poll `pending` Jules runs via API. Time out any
   run that exceeds its threshold (`JULES_TIMEOUT_HOURS` for pending,
   `GEMINI_STALE_THRESHOLD_MINUTES` for running). Quick — just API
   GETs and timestamp checks.
2. **Dispatch** new issues (up to `MAX_ISSUES_PER_RUN=5`).

This means a single cron schedule handles async-completion, crash
recovery, and new-issue dispatch without needing a separate job.

### External side effects are non-reversible

Dispatch makes external API calls (fork creation, branch creation,
agent dispatch) inside a per-issue database transaction. If the
transaction rolls back after an external call succeeds, the external
side effect persists. A rollback after an external side effect is
explicitly considered an orphaned external operation — the system
never assumes rollback means the external operation was undone.

This is tolerated at free-tier scale. The implementation must ensure
`ensure_fork()` and `create_branch()` are idempotent, and that a 409
(ref already exists) on branch creation verifies the existing ref
points to the expected base commit rather than silently ignoring it.

### `issues.status` is a coarse pipeline stage

With multiple agents per issue, the issue status cannot represent the
lifecycle of individual runs. The contract is:

- `discovered` → found, waiting for dispatch
- `dispatched` → at least one agent has been sent to work
- `submitted` → a PR has been opened upstream
- `skipped` → explicitly bypassed (issue closed, all runs failed,
  policy forbids, linked PR exists)

There is no `evaluated` status. Readiness for submission is derived
from the `runs` and `evaluations` tables directly: all created runs
must be terminal, at least one must have succeeded, and every
successful run must have an evaluation row.

### `session_id` column on `runs`

Added to track external task IDs (Jules session IDs) so the poller
can resume tracking across dispatch runs. Sync agents (Gemini) leave
this NULL.

## Schema overview

The schema covers all four stages, not just discovery:

```
repos → repo_policies    (1:1, AI contribution policy cache)
repos → issues           (1:many)
issues → runs            (1:many, one per agent attempt)
runs → evaluations       (1:1, enforced by UNIQUE(run_id))
issues → pr_submissions  (1:1, enforced by UNIQUE(issue_id))
```

`pr_submissions.disclosure_text NOT NULL` enforces that every submitted
PR includes AI-involvement disclosure.

The `runs` table includes a `session_id TEXT` column for async agent
tracking (e.g., Jules task IDs). `runs.status` has no DEFAULT —
dispatch must explicitly set `'pending'` (async) or `'running'`
(sync). Statuses: `pending | running | success | failed | timeout`.

## Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `GITHUB_SCAN_TOKEN` | discover.py | PAT with `public_repo` scope. NOT the default Actions `GITHUB_TOKEN` (that one can't search across repos). Set as `DISCOVERY_GH_TOKEN` in repo secrets. |
| `DATABASE_URL` | all scripts | Postgres connection string |
| `GITHUB_WEBHOOK_SECRET` | webhook_receiver.py | HMAC secret for verifying incoming webhook payloads |
| `PORT` | webhook_receiver.py | Only used when running directly (`python webhook_receiver.py`), ignored under gunicorn |
| `GITHUB_DISPATCH_TOKEN` | dispatch.py | PAT with `repo` scope (needs to fork + push). Can be same as scan token if it has sufficient scope. |
| `GEMINI_API_KEY` | dispatch.py | From Google AI Studio. Used for the Gemini function-calling agent. |

## What's next

Discovery and Gemini-only dispatch are built, tested, and verified live on GitHub Actions (`discover.yml` and `dispatch.yml`). Live execution was verified against `harshitthek/resilient-test#1` with `gemini-2.5-flash` producing code changes on a fork branch.

See `ROADMAP.md` for the next stage: Stage 3 (Evaluation). Jules remains disabled pending separate controlled validation.
