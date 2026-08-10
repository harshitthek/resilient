"""
Dispatch stage.

Runs on a schedule (every 8 hours) or manually. Two modes per invocation:

Mode 1 — Poll pending/stale runs (runs first, quick):
    - Poll Jules pending runs via session_id
    - Detect and timeout stale Jules runs (pending > JULES_TIMEOUT_HOURS)
    - Detect and timeout stale Gemini runs (running > GEMINI_STALE_THRESHOLD)

Mode 2 — Dispatch new issues:
    - Select discovered issues from active repos
    - Re-check issue state, linked PRs, AI policy
    - Ensure fork exists, create branches
    - Dispatch agents (one run per configured agent)
    - Update issue status to 'dispatched'

Per-issue isolation: each issue is processed in its own try/except
with rollback, matching the discovery pattern. A single broken issue
does not kill unrelated issues.

IMPORTANT: External side effects (fork creation, branch creation,
agent dispatch) cannot be rolled back by PostgreSQL. A DB rollback
after an external call succeeds creates orphaned external work. This
is explicitly tolerated per the locked contracts.
"""

import os
import sys
import importlib
from datetime import datetime, timezone, timedelta

import psycopg2

# Import from sibling module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from github_utils import (
    GITHUB_API,
    check_ai_policy,
    create_branch,
    create_github_session,
    ensure_fork,
    get_default_branch_sha,
    gh_get,
    has_linked_pr,
)

# Import agent adapters — add parent dir to path for agents package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base import RepoContext, RunResult


# --- Configuration ---
# Read at module level with defaults so the module can be imported for
# testing without all env vars set. main() validates required vars.

DB_URL = os.environ.get("DATABASE_URL", "")
DISPATCH_TOKEN = os.environ.get("GITHUB_DISPATCH_TOKEN", "")

MAX_ISSUES_PER_RUN = int(os.environ.get("MAX_ISSUES_PER_RUN", "5"))
JULES_TIMEOUT_HOURS = int(os.environ.get("JULES_TIMEOUT_HOURS", "2"))
GEMINI_STALE_THRESHOLD_MINUTES = int(os.environ.get("GEMINI_STALE_THRESHOLD_MINUTES", "30"))
POLICY_STALE_DAYS = 7  # re-check policy if older than this

TERMINAL_STATUSES = {"success", "failed", "timeout"}


# --- Agent registry ---

def load_agents():
    """Load configured agent adapters.

    Returns a list of AgentAdapter instances. Currently:
    - Gemini 2.5 Pro (sync)
    - Gemini 2.5 Flash (sync)
    - Jules remains deliberately disabled pending its dedicated validation.

    Agents are loaded lazily to avoid import errors when optional
    dependencies aren't installed."""
    agents = []

    # Gemini agents — always loaded if GEMINI_API_KEY is available
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        from agents.gemini_agent import GeminiAgent
        agents.append(GeminiAgent(model_id="gemini-2.5-pro"))
        agents.append(GeminiAgent(model_id="gemini-2.5-flash"))
    else:
        print("Warning: GEMINI_API_KEY not set, Gemini agents disabled", file=sys.stderr)

    # Jules is intentionally not loaded, even if a key is present. It must
    # receive a separate controlled validation before production enablement.
    print("Info: Jules is disabled pending controlled validation", file=sys.stderr)

    if not agents:
        print("Error: No agents configured. Set GEMINI_API_KEY.",
              file=sys.stderr)

    return agents


# ========================================================================
# MODE 1 — Poll pending runs and detect stale runs
# ========================================================================

def mode1_poll_and_recover(conn, session, agents_by_name):
    """Poll pending runs and detect stale runs.

    Runs FIRST on every invocation. Quick — just API GETs and
    timestamp checks.

    Does NOT overwrite terminal states."""
    print("=== Mode 1: Poll pending/stale runs ===", file=sys.stderr)
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, issue_id, agent_name, status, session_id, started_at
            FROM runs
            WHERE status IN ('pending', 'running')
        """)
        active_runs = cur.fetchall()

    if not active_runs:
        print("  No active runs to poll.", file=sys.stderr)
        return

    for run_id, issue_id, agent_name, status, session_id, started_at in active_runs:
        try:
            elapsed = now - started_at
            new_status = None
            finished_at = None
            error_msg = None
            diff_url = None

            if status == "pending":
                # Check for Jules timeout first
                if elapsed > timedelta(hours=JULES_TIMEOUT_HOURS):
                    new_status = "timeout"
                    finished_at = now
                    error_msg = f"Timed out after {elapsed}"
                    print(f"  Run {run_id} ({agent_name}): pending → timeout "
                          f"(elapsed {elapsed})", file=sys.stderr)
                elif session_id and agent_name in agents_by_name:
                    # Poll the agent
                    agent = agents_by_name[agent_name]
                    result = agent.poll(session_id)
                    if result.status != "pending":
                        new_status = result.status
                        finished_at = now
                        diff_url = result.diff_url
                        error_msg = result.error
                        print(f"  Run {run_id} ({agent_name}): pending → {new_status}",
                              file=sys.stderr)
                    else:
                        print(f"  Run {run_id} ({agent_name}): still pending "
                              f"(elapsed {elapsed})", file=sys.stderr)
                else:
                    print(f"  Run {run_id} ({agent_name}): pending, no session_id "
                          f"or agent not loaded", file=sys.stderr)

            elif status == "running":
                # Check for stale Gemini runs (crash recovery)
                if elapsed > timedelta(minutes=GEMINI_STALE_THRESHOLD_MINUTES):
                    new_status = "timeout"
                    finished_at = now
                    error_msg = f"Stale run detected after {elapsed} (process likely crashed)"
                    print(f"  Run {run_id} ({agent_name}): running → timeout "
                          f"(stale, elapsed {elapsed})", file=sys.stderr)

            # Apply status change if needed
            if new_status and new_status in TERMINAL_STATUSES:
                with conn.cursor() as cur:
                    # Guard: never overwrite a terminal status
                    cur.execute("""
                        UPDATE runs
                        SET status = %s, finished_at = %s, diff_url = COALESCE(%s, diff_url)
                        WHERE id = %s AND status NOT IN ('success', 'failed', 'timeout')
                    """, (new_status, finished_at, diff_url, run_id))
                conn.commit()

        except Exception as exc:
            conn.rollback()
            print(f"  Error polling run {run_id}: {exc}", file=sys.stderr)


# ========================================================================
# MODE 2 — Dispatch new issues
# ========================================================================

def mode2_dispatch_new_issues(conn, session, agents):
    """Select discovered issues and dispatch agents.

    Per-issue isolation: each issue is processed in its own try/except
    with rollback."""
    print(f"\n=== Mode 2: Dispatch new issues (max {MAX_ISSUES_PER_RUN}) ===",
          file=sys.stderr)

    if not agents:
        print("  No agents configured, skipping dispatch.", file=sys.stderr)
        return

    # Select eligible issues
    with conn.cursor() as cur:
        cur.execute("""
            SELECT i.id, i.repo_id, i.github_issue_number, i.title,
                   r.full_name, r.default_branch, r.language, r.fork_full_name
            FROM issues i
            JOIN repos r ON r.id = i.repo_id
            WHERE i.status = 'discovered'
              AND r.is_active = TRUE
            ORDER BY r.stars DESC
            LIMIT %s
        """, (MAX_ISSUES_PER_RUN,))
        candidates = cur.fetchall()

    if not candidates:
        print("  No discovered issues to dispatch.", file=sys.stderr)
        return

    print(f"  Found {len(candidates)} candidate issues.", file=sys.stderr)

    for (issue_id, repo_id, issue_number, title,
         full_name, default_branch, language, existing_fork) in candidates:
        try:
            print(f"\n  Processing: {full_name}#{issue_number} ({title[:60]})",
                  file=sys.stderr)
            dispatch_one_issue(
                conn, session, agents,
                issue_id=issue_id,
                repo_id=repo_id,
                issue_number=issue_number,
                full_name=full_name,
                default_branch=default_branch,
                language=language,
                existing_fork=existing_fork,
            )
        except Exception as exc:
            conn.rollback()
            print(f"  FAILED {full_name}#{issue_number}: {exc}", file=sys.stderr)


def dispatch_one_issue(conn, session, agents, *, issue_id, repo_id,
                       issue_number, full_name, default_branch,
                       language, existing_fork):
    """Process a single issue: pre-checks → fork → branches → dispatch agents.

    Transaction model:
      Phase A (pre-checks): All DB writes are collected in one transaction.
          If any pre-check fails, the caller rolls back.
          Committed at the end of Phase A before any agent work starts.
      Phase B (per-agent): Each agent gets its own commit cycle:
          1. INSERT run row → COMMIT (so Mode 1 can find stale runs)
          2. Call agent.dispatch() (may block for minutes)
          3. UPDATE run row with result → COMMIT

    This ensures that:
      - A `running` Gemini row is visible to Mode 1 even if the
        process crashes during the agent's 5-minute execution.
      - A `pending` Jules row is committed before the next agent
        starts, so it survives a crash during Gemini dispatch.

    External side effects (fork, branch, agent dispatch) survive rollback.
    This is explicitly tolerated per contract #9."""

    # --- Step 1: Re-check issue state (fresh from GitHub) ---
    resp = gh_get(session, f"{GITHUB_API}/repos/{full_name}/issues/{issue_number}")
    if resp.status_code == 404:
        print(f"    Issue not found (deleted?), skipping", file=sys.stderr)
        _set_issue_status(conn, issue_id, "skipped")
        conn.commit()
        return
    if resp.status_code != 200:
        raise RuntimeError(f"Issue re-check failed: status={resp.status_code}")

    issue_data = resp.json()
    if issue_data.get("state") != "open":
        print(f"    Issue is {issue_data.get('state')}, skipping", file=sys.stderr)
        _set_issue_status(conn, issue_id, "skipped")
        conn.commit()
        return

    issue_body = issue_data.get("body") or ""
    issue_title = issue_data.get("title", "")

    # --- Step 2: Linked PR check ---
    if has_linked_pr(session, full_name, issue_number):
        print(f"    Has linked PR, skipping", file=sys.stderr)
        _set_issue_status(conn, issue_id, "skipped")
        conn.commit()
        return

    # --- Step 3: AI policy re-check if stale ---
    if _policy_is_stale(conn, repo_id):
        policy_status, source_file, snippet = check_ai_policy(session, full_name)
        _upsert_policy(conn, repo_id, policy_status, source_file, snippet)
        if policy_status == "disallowed":
            print(f"    Policy now disallowed, deactivating repo", file=sys.stderr)
            _deactivate_repo(conn, repo_id)
            _set_issue_status(conn, issue_id, "skipped")
            conn.commit()
            return

    # --- Step 4: Ensure fork exists ---
    if existing_fork:
        fork_full_name = existing_fork
        print(f"    Using existing fork: {fork_full_name}", file=sys.stderr)
    else:
        fork_full_name = ensure_fork(session, full_name)
        print(f"    Created/found fork: {fork_full_name}", file=sys.stderr)
        with conn.cursor() as cur:
            cur.execute("UPDATE repos SET fork_full_name = %s WHERE id = %s",
                        (fork_full_name, repo_id))

    # Commit Phase A: pre-checks and fork state are now durable.
    conn.commit()

    # Get base SHA for branching
    base_sha = get_default_branch_sha(session, fork_full_name, default_branch)
    clone_url = f"https://x-access-token:{DISPATCH_TOKEN}@github.com/{fork_full_name}.git"

    # --- Phase B: Per-agent dispatch ---
    # Each agent gets its own commit cycle so that run rows are visible
    # to Mode 1 even if the process crashes during agent execution.
    runs_created = 0

    for agent in agents:
        branch_name = f"resilient/{issue_number}/{agent.name}"

        try:
            # Step 5: Create branch (external side effect — survives rollback)
            create_branch(session, fork_full_name, branch_name, base_sha)
            print(f"    Branch ready: {branch_name}", file=sys.stderr)

            # Step 6: Create run row and COMMIT immediately.
            # This makes the row visible to Mode 1 for stale-run detection.
            initial_status = "pending" if agent.is_async else "running"
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO runs (issue_id, agent_name, branch_name, status)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """, (issue_id, agent.name, branch_name, initial_status))
                run_id = cur.fetchone()[0]
            conn.commit()
            # --- From this point, the run row exists in the DB. ---
            # If the process crashes during agent.dispatch(), Mode 1 will
            # find this row as stale and mark it timeout on the next run.

            # Step 7: Dispatch the agent (may block for minutes)
            ctx = RepoContext(
                fork_full_name=fork_full_name,
                branch_name=branch_name,
                clone_url=clone_url,
                upstream_full_name=full_name,
                default_branch=default_branch,
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body,
                language=language,
            )

            print(f"    Dispatching {agent.name}...", file=sys.stderr)
            result = agent.dispatch(ctx)

            # Update run with result and COMMIT
            _update_run_from_result(conn, run_id, result)
            conn.commit()
            runs_created += 1
            print(f"    {agent.name} → {result.status}", file=sys.stderr)

        except Exception as exc:
            conn.rollback()
            # Agent-level failure: log and continue to next agent.
            # If the run row was committed (after the conn.commit() above),
            # it persists with status=running/pending and will be caught by
            # Mode 1 stale-run detection on the next invocation.
            # If the run row was NOT yet committed, it vanishes — but so
            # does the agent work (it wasn't dispatched yet).
            print(f"    {agent.name} dispatch FAILED: {exc}", file=sys.stderr)
            # Try to mark the run as failed if it exists in the DB
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE runs SET status = 'failed', finished_at = now()
                        WHERE id = %s AND status NOT IN ('success', 'failed', 'timeout')
                    """, (run_id,))
                conn.commit()
            except Exception:
                conn.rollback()  # run row may not exist

    # --- Step 8: Update issue status ---
    if runs_created > 0:
        _set_issue_status(conn, issue_id, "dispatched")
        conn.commit()
        print(f"    Issue dispatched ({runs_created} agent(s))", file=sys.stderr)
    else:
        # All agents failed to dispatch — don't leave the issue in 'discovered'
        # forever. Mark it skipped so it doesn't block the queue.
        _set_issue_status(conn, issue_id, "skipped")
        conn.commit()
        print(f"    All agents failed, issue skipped", file=sys.stderr)


# ========================================================================
# Database helpers
# ========================================================================

def _set_issue_status(conn, issue_id, status):
    """Set the issue status. Follows the locked contract:
    discovered → dispatched → submitted | skipped"""
    with conn.cursor() as cur:
        cur.execute("UPDATE issues SET status = %s WHERE id = %s", (status, issue_id))


def _update_run_from_result(conn, run_id, result):
    """Update a run row from a RunResult.

    For async agents (pending): records the session_id.
    For sync agents (terminal): records finished_at and diff_url.

    Never overwrites terminal statuses."""
    with conn.cursor() as cur:
        if result.status == "pending":
            # Async agent — record session_id for polling
            cur.execute("""
                UPDATE runs SET session_id = %s
                WHERE id = %s AND status = 'pending'
            """, (result.session_id, run_id))
        elif result.status in TERMINAL_STATUSES:
            # Terminal — record completion
            cur.execute("""
                UPDATE runs
                SET status = %s, finished_at = now(),
                    diff_url = %s, session_id = COALESCE(%s, session_id)
                WHERE id = %s AND status NOT IN ('success', 'failed', 'timeout')
            """, (result.status, result.diff_url, result.session_id, run_id))


def _policy_is_stale(conn, repo_id):
    """Check if the repo's AI policy is older than POLICY_STALE_DAYS."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT checked_at FROM repo_policies WHERE repo_id = %s
        """, (repo_id,))
        row = cur.fetchone()
        if not row:
            return True  # no policy — definitely stale
        checked_at = row[0]
        return (datetime.now(timezone.utc) - checked_at) > timedelta(days=POLICY_STALE_DAYS)


def _upsert_policy(conn, repo_id, status, source_file, snippet):
    """Upsert the repo's AI policy. Same logic as discover.py."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO repo_policies (repo_id, allows_ai_prs, source_file, matched_snippet, checked_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (repo_id) DO UPDATE SET
                allows_ai_prs = EXCLUDED.allows_ai_prs,
                source_file = EXCLUDED.source_file,
                matched_snippet = EXCLUDED.matched_snippet,
                checked_at = now()
        """, (repo_id, status, source_file, snippet))


def _deactivate_repo(conn, repo_id):
    """Deactivate a repo (policy disallowed or other reason)."""
    with conn.cursor() as cur:
        cur.execute("UPDATE repos SET is_active = FALSE WHERE id = %s", (repo_id,))


# ========================================================================
# Main
# ========================================================================

def main():
    global DB_URL, DISPATCH_TOKEN
    # Validate required env vars (module-level uses .get for testability)
    DB_URL = os.environ.get("DATABASE_URL", "")
    DISPATCH_TOKEN = os.environ.get("GITHUB_DISPATCH_TOKEN", "")
    if not DB_URL:
        print("Error: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    if not DISPATCH_TOKEN:
        print("Error: GITHUB_DISPATCH_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    session = create_github_session(DISPATCH_TOKEN)
    agents = load_agents()
    agents_by_name = {a.name: a for a in agents}

    conn = psycopg2.connect(DB_URL)
    try:
        # Mode 1 always runs first
        mode1_poll_and_recover(conn, session, agents_by_name)

        # Mode 2: dispatch new issues
        mode2_dispatch_new_issues(conn, session, agents)

        print("\n=== Dispatch complete ===", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
