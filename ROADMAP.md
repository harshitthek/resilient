# Roadmap — what's next after Gemini dispatch

Discovery and Gemini-only dispatch are built (see `CONTEXT.md`). This
document records the dispatch design and specifies the remaining
evaluation, submission, and leaderboard stages.

Each stage is described in enough detail to implement from.
Decisions marked **[OPEN]** still need resolution; decisions marked
**[RESOLVED]** were answered during planning.

---

## Stage 2: Dispatch

**What it does:** Takes issues with `status = 'discovered'` and hands
them to one or more AI agents to attempt a fix.

**Status:** Implemented and exercised by the local dispatch safety suite.
Gemini Pro and Flash use fork-only synchronous execution. Jules is
intentionally disabled pending a separate controlled validation.

### Agent API research results

Research into available agent APIs found that all target agents are
programmable:

| Agent | API | Execution model | Free tier |
|---|---|---|---|
| **Jules** | REST API (`v1alpha`) at `jules.googleapis.com` | Async: fire task → poll for completion. Runs on Google Cloud VMs. | 15 tasks/day, 3 concurrent |
| **Gemini 2.5 Pro** | `google-genai` SDK, function calling | Synchronous agent loop: read → reason → edit → test, inline. | ~5 RPM, ~100 RPD |
| **Gemini 2.5 Flash** | Same SDK, different model ID | Same as above, faster/cheaper | ~15 RPM, ~1500 RPD |

Jules and Gemini have fundamentally different execution models:
- **Jules** is fire-and-poll. `dispatch()` starts the task and returns
  `status='pending'`. Subsequent dispatch runs call `poll()` to check
  completion.
- **Gemini** is synchronous. `dispatch()` blocks until the agent loop
  finishes (typically under 5 minutes) and returns the final status.

The agent adapter abstraction must handle both patterns.
**[RESOLVED: D1]**

### Script: `scripts/dispatch.py`

Runs on a schedule (every 8 hours) or manually.
**Two modes in every invocation:**

**Mode 1 — Poll pending runs and detect stale runs** (runs first, quick):
```
SELECT runs WHERE status IN ('pending', 'running')
For each:
  If status='pending' AND started_at + JULES_TIMEOUT_HOURS < now():
    Set status='timeout'                         → stale async run
  Elif status='running' AND started_at + GEMINI_STALE_THRESHOLD < now():
    Set status='timeout'                         → stale sync run (crash recovery)
  Elif status='pending':
    Call agent.poll(session_id)
    Update run status if changed (pending → success/failed/timeout)
```

Starting operational values (tune based on observed agent behavior):
- `JULES_TIMEOUT_HOURS = 2`
- `GEMINI_STALE_THRESHOLD_MINUTES = 30`

**Mode 2 — Dispatch new issues:**
```
SELECT issues WHERE status='discovered'
  JOIN repos WHERE is_active=TRUE
  ORDER BY repos.stars DESC
  LIMIT 5 (MAX_ISSUES_PER_RUN)

Per issue:
  1. Re-check issue state (still open?)           → skip if closed
  2. has_linked_pr() search                        → skip if PR exists
  3. Re-check AI policy if stale (>7 days)         → skip if now disallowed
                                                     (also deactivate repo)
  4. Ensure fork exists (create if not)            → record fork_full_name
  5. For each configured agent:
     a. Create branch: resilient/{issue_number}/{agent_name}
     b. Create runs row (status depends on agent type)
     c. Call agent.dispatch(context)
     d. Update runs row with result
  6. Update issues.status = 'dispatched'
  7. COMMIT (per-issue isolation, same pattern as discover.py)
```

Note on readiness semantics: "all agents finished" means "all *created*
runs are terminal," not "every configured agent was dispatched." If
dispatch crashes after creating 1 of 3 intended runs, submission
proceeds with the data available. Intent is not recorded.

### Agent adapter abstraction [RESOLVED: D1]

```
agents/
  __init__.py
  base.py             # AgentAdapter ABC + RepoContext/RunResult dataclasses
  jules_adapter.py    # Jules v1alpha REST API
  gemini_agent.py     # Gemini function-calling agent loop
```

**`base.py` core interface:**

```python
class AgentAdapter(ABC):
    name: str           # 'jules', 'gemini-2.5-pro', 'gemini-2.5-flash'

    def dispatch(self, ctx: RepoContext) -> RunResult:
        """Start work. Returns immediately for async agents (status='pending'),
        blocks until done for sync agents."""

    def poll(self, session_id: str) -> RunResult:
        """Check async task status. No-op for sync agents."""

    @property
    def is_async(self) -> bool: ...
```

**`RepoContext` dataclass:**
- `fork_full_name`, `upstream_full_name`, `branch_name`
- `default_branch`, `clone_url`
- `issue_number`, `issue_title`, `issue_body`
- `language`

**`RunResult` dataclass:**
- `status`: `'success'` | `'failed'` | `'timeout'` | `'pending'`
- `diff_url`, `error`, `session_id` (for async polling)

**Jules adapter** (`jules_adapter.py`):
- `dispatch()`: POST `/v1alpha/sessions` with fork context and issue
  prompt. `requirePlanApproval = False`. Returns `status='pending'`
  with the Jules `session_id`.
- `poll()`: GET `/v1alpha/sessions/{id}`, map Jules states
  (`COMPLETED` → `success`, `FAILED` → `failed`, else → `pending`).
- Critical: `sourceContext` targets the **fork**, never upstream.

**Gemini agent** (`gemini_agent.py`):
- `dispatch()` (synchronous, blocks):
  1. Clone fork, checkout dispatch branch
  2. Gather issue context + relevant file contents
  3. Agent loop with `google-genai` function calling:
     - Tools: `read_file`, `write_file`, `list_directory`, `run_command`
     - Max 15 iterations, 5-minute timeout
  4. Commit + push to fork branch
  5. Return `status='success'` or `'failed'`
- `poll()`: no-op (sync agent)

### Rate limiting / budget [RESOLVED: D2]

- `MAX_ISSUES_PER_RUN = 5` (conservative starting point)
- Jules: max 3 concurrent sessions (free tier hard limit), 15/day
- Gemini 2.5 Pro: ~5 RPM, agent loop uses ~5-10 calls per issue →
  ~10-20 issues/day practical max
- Gemini 2.5 Flash: ~15 RPM → more headroom, good for comparison

### Shared GitHub utilities: `scripts/github_utils.py`

Common functions extracted from `discover.py` for reuse:
- `gh_get()`, `gh_post()` (new) — rate-limited HTTP
- `has_linked_pr()` — moved from discover.py (was removed, now lives
  here for dispatch to call)
- `check_ai_policy()` — moved from discover.py
- `ensure_fork()` — POST `/repos/{owner}/{repo}/forks`
- `create_branch()` — POST `/repos/.../git/refs`
- `get_default_branch_sha()` — GET `/repos/.../git/ref/heads/{branch}`

`discover.py` will import from `github_utils` instead of defining
these inline. No behavioral change.

### Schema changes (applied to schema.sql)

All Phase 0 schema changes have been applied directly to `schema.sql`:
- `runs.session_id TEXT` — async agent tracking
- `runs.status` — no DEFAULT, `pending` added
- `runs.agent_name` comment — current agent names
- `evaluations.run_id` — `UNIQUE` (one evaluation per run)
- `pr_submissions.issue_id` — `UNIQUE` (one PR per issue)
- `issues.status` comment — actual lifecycle
- `idx_runs_status` index — Mode 1 poll query

### Workflow: `.github/workflows/dispatch.yml`

```yaml
schedule:
  - cron: '0 */8 * * *'   # every 8 hours
workflow_dispatch: {}       # manual trigger

env:
  GITHUB_DISPATCH_TOKEN    # PAT with repo scope (fork + push)
  GEMINI_API_KEY           # from Google AI Studio
  DATABASE_URL
```

Timeout: 30 minutes (longer than discovery — agent runs take time).

### Failure modes

| Case | Handling |
|---|---|
| Fork creation fails (quota, API error) | Skip repo for this run, retry next time |
| Jules task times out | Mode 1 detects `pending` + elapsed > `JULES_TIMEOUT_HOURS`; set `runs.status = 'timeout'` |
| Jules task fails | `poll()` maps `FAILED` state; set `runs.status = 'failed'` |
| Gemini agent loop exceeds iteration limit | Return `status='failed'`, log partial work |
| Gemini agent loop exceeds time limit | Kill and return `status='timeout'` |
| Gemini process crashes mid-dispatch | Row stays `running`; Mode 1 detects `running` + elapsed > `GEMINI_STALE_THRESHOLD`; set `timeout` |
| Agent produces no diff (empty changeset) | Set `runs.status = 'failed'`, log "no changes produced" |
| Issue closed mid-work | Caught at submission time (stage 4), not here — agent may still produce useful leaderboard data |
| GitHub API rate limit during fork/branch ops | `gh_post()` uses same backoff as `gh_get()` |
| Transaction rollback after external dispatch | Orphaned external work (see below) |

### External side effects and idempotency

Dispatch makes non-reversible API calls (fork creation, branch
creation, agent dispatch) inside a per-issue database transaction.
If the transaction rolls back after an external call succeeds, the
external side effect persists. **A rollback after an external side
effect is explicitly considered an orphaned external operation. The
system must never assume rollback means the external operation was
undone.**

This is tolerated at this scale:
- `ensure_fork()` is idempotent (GitHub returns the existing fork)
- `create_branch()` must handle "ref already exists" (409) carefully:
  verify the existing ref points to the expected base commit, not
  just silently ignore the 409
- Orphaned Jules tasks run on Google infrastructure and are bounded
  by the free-tier daily cap (15/day)
- Orphaned Gemini commits on fork branches are inert

Implication for the leaderboard: the system evaluates every **tracked
successful run**, not every external agent attempt. Orphaned external
work is not guaranteed to appear in the leaderboard.

### New files for dispatch

| File | Purpose |
|---|---|
| `agents/__init__.py` | Package init |
| `agents/base.py` | Abstract adapter + dataclasses |
| `agents/jules_adapter.py` | Jules v1alpha REST API |
| `agents/gemini_agent.py` | Gemini function-calling agent |
| `scripts/dispatch.py` | Dispatch orchestrator |
| `scripts/github_utils.py` | Shared GitHub API utilities |
| `scripts/requirements-dispatch.txt` | `requests`, `psycopg2-binary`, `google-genai` |
| `.github/workflows/dispatch.yml` | Actions workflow |

---

## Stage 3: Evaluation

**What it does:** Scores each completed agent run so the best attempt
can be selected for submission.

### Script: `scripts/evaluate.py`

Runs after agents finish (polled, or triggered by agent completion
callback if the agent supports one).

### Per-run evaluation

1. **Check run status.** Only evaluate runs with `status = 'success'`
   (agent reported completion and produced a diff/branch).

2. **Run the repo's test suite** against the agent's branch.
   - Clone the fork, checkout the agent's branch
   - Detect test runner (look for `pytest.ini`, `package.json` scripts,
     `Makefile` test target, etc.)
   - Run tests with a timeout
   - Record `tests_passed` (boolean) and `test_summary` (output snippet)
   - **If no test suite is detected:** `tests_passed = NULL`. This is
     treated as lower-confidence downstream, NOT as a pass.

3. **Automated code review.** Run a reviewer (e.g., CodeRabbit's API,
   or a custom LLM-based review) against the diff.
   - Record `reviewer_score` (numeric) and `reviewer_notes` (JSONB —
     structured findings, not just a number)

4. **Compute composite score.**
   ```
   composite = w1 * (tests_passed ? 1 : 0)
             + w2 * reviewer_score
             + w3 * (tests_passed IS NOT NULL ? 1 : 0)  -- bonus for repos with tests
   ```
   - **[OPEN: D3]** Exact weights. Start with something reasonable
     (e.g., 0.5 / 0.4 / 0.1), tune based on merge-rate feedback.

5. **Write the `evaluations` row.**

### Failure modes

| Case | Handling |
|---|---|
| Tests fail | `tests_passed = FALSE`, still scored (reviewer might rate the code well enough for leaderboard) |
| Test suite hangs | Kill after timeout, `tests_passed = FALSE`, `test_summary = 'timeout'` |
| No test suite | `tests_passed = NULL`, composite score penalized but not zeroed |
| Reviewer API down | Retry with backoff; if still failing, `reviewer_score = NULL`, score from tests only |

---

## Stage 4: Submission

**What it does:** For each issue where at least one agent produced a
good-enough fix, opens exactly one PR upstream from the winning
agent's branch.

### Script: `scripts/submit.py`

Runs after evaluation. Can be manual-trigger-only initially for safety.

### Steps per issue

1. **Select the winning run.** Across all evaluated runs for this
   issue, pick the one with the highest `composite_score`. Ties broken
   by `tests_passed = TRUE` first, then `reviewer_score`.

2. **Gate checks — all must pass:**
   - `composite_score >= SUBMISSION_THRESHOLD` (configurable)
     **[OPEN: D4]**
   - `repo_policies.allows_ai_prs != 'disallowed'`
   - For `unknown` policy: **do not submit** (agents ran for
     leaderboard data, but nothing goes upstream)
   - Issue is still open (re-fetch from GitHub)
   - No PR has been submitted for this issue already
     (`pr_submissions` row doesn't exist)
   - Daily cap not exceeded (per-repo and global) **[OPEN: D5]**

3. **Prepare the PR.**
   - Source: the winning agent's branch on the fork
   - Target: upstream repo's default branch
   - Title: descriptive, references the issue (`Fixes #123`)
   - Body must include:
     - `disclosure_text`: clear statement that this is AI-assisted,
       which agent produced it, and that it was scored/reviewed
       before submission
     - Link back to the leaderboard entry for this issue
     - Opt-out instructions for the maintainer
   - **[OPEN: D6]** Exact PR body template.

4. **Open the PR** via GitHub API. Record `pr_url` in `pr_submissions`.

5. **Update statuses:**
   - `issues.status = 'submitted'`
   - `pr_submissions.maintainer_status = 'pending'`

6. **Handle dead-end issues.** After evaluating all ready issues,
   scan for `dispatched` issues that can never be submitted and
   transition them to `skipped`:

   **Non-retryable conditions (→ `skipped`):**
   - All runs terminal, none succeeded (all failed/timeout)
   - Issue permanently closed on GitHub
   - `repo_policies.allows_ai_prs = 'disallowed'`
   - PR already exists for the issue (linked by someone else)

   **Retryable conditions (leave `dispatched`, try again next run):**
   - GitHub API unavailable (transient)
   - Reviewer unavailable (transient)
   - Daily cap exceeded (wait for tomorrow)

   If all tiebreakers are exhausted when selecting a winner (identical
   `composite_score`, `tests_passed`, `reviewer_score`), any of the
   tied runs may be selected — equally-scored runs are interchangeable.

### Daily caps [OPEN: D5]

- Starting suggestion:
  - Max 2 PRs per repo per day
  - Max 10 PRs total per day
- Enforced by counting `pr_submissions` rows with
  `submitted_at > now() - interval '24 hours'`.
- Non-negotiable guardrails — even if 50 great fixes are ready,
  submitting them all at once looks like a bot flood.

### Failure modes

| Case | Handling |
|---|---|
| PR creation fails (permissions, branch conflict) | Log error, don't update status, retry next run |
| Maintainer closes/rejects the PR | Track via webhook or polling; update `maintainer_status` |
| Maintainer merges the PR | Update `maintainer_status = 'merged'` — this is the primary success signal |
| Maintainer asks to stop | Set `repos.is_active = FALSE` immediately |
| All runs failed for an issue | `submit.py` sets `issues.status = 'skipped'` |

---

## Leaderboard

**What it does:** Public-facing view of agent performance across all
evaluated issues.

### Data source

Derived from existing tables — no new schema required:

```sql
-- Agent win rate
SELECT agent_name,
       COUNT(*) AS total_runs,
       COUNT(*) FILTER (WHERE r.id = ps.winning_run_id) AS wins,
       AVG(e.composite_score) AS avg_score
FROM runs r
JOIN evaluations e ON e.run_id = r.id
LEFT JOIN pr_submissions ps ON ps.winning_run_id = r.id
GROUP BY agent_name;

-- Merge rate (the real quality signal)
SELECT agent_name,
       COUNT(*) FILTER (WHERE ps.maintainer_status = 'merged') AS merged,
       COUNT(*) FILTER (WHERE ps.maintainer_status IS NOT NULL) AS submitted
FROM runs r
JOIN pr_submissions ps ON ps.winning_run_id = r.id
GROUP BY agent_name;
```

### Presentation

- **[OPEN: D7]** Static site (GitHub Pages) vs. dynamic app. At small
  scale, a scheduled job that writes a JSON file + a static HTML page
  is simpler and free.
- Metrics per agent: total runs, win rate, merge rate, average
  composite score, average reviewer score
- Drill-down: per-issue view showing all agents' scores side by side
- Transparency: link to the PR (if submitted) and the issue

---

## Implementation order

| Order | Stage | Status |
|---|---|---|
| 1 | ~~Discovery~~ | ✅ Done |
| 2 | Dispatch | ✅ Built & Live Verified; Gemini 2.5 Flash enabled, Jules deliberately disabled |
| 3 | Evaluation | ✅ Built & Tested |
| 4 | Submission | ✅ Built & Tested |
| 5 | Leaderboard | 📋 Specified |

---

## Open decisions summary

| ID | Status | Question | Stage |
|---|---|---|---|
| D1 | ✅ Resolved | Agent adapter abstraction: abstract base + Jules (async/REST) + Gemini (sync/function-calling) | Dispatch |
| D2 | ✅ Resolved | Budget caps: MAX_ISSUES_PER_RUN=5, respect Jules 15/day and 3-concurrent, Gemini RPM limits | Dispatch |
| D3 | ⬜ Open | Composite score weights (tests vs. reviewer vs. test-suite-exists bonus) | Evaluation |
| D4 | ⬜ Open | Submission threshold — minimum composite score to submit a PR | Submission |
| D5 | ⬜ Open | Daily PR caps — per-repo and global | Submission |
| D6 | ⬜ Open | PR body template — disclosure text, opt-out instructions | Submission |
| D7 | ⬜ Open | Leaderboard format — static site vs. dynamic app | Leaderboard |
