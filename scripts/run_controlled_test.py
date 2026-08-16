"""
Controlled single-issue integration test and audit runner for Resilient Dispatch.

Executes dispatch for one specific issue using Gemini-only, then performs
an automated 10-point audit verifying that:
1. Correct fork was used.
2. Correct branch exists on fork.
3. Upstream has NO new branch/commit.
4. Fork contains the branch and commits.
5. runs.status is set correctly.
6. runs.branch_name is correct.
7. issues.status = 'dispatched'.
8. No unexpected PR was created.
9. Temporary clone directory was cleaned up.
10. PostgreSQL contains exact expected run row.
"""

import os
import sys
import tempfile
import psycopg2
import requests

# Add scripts directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from github_utils import create_github_session, GITHUB_API, gh_get
from agents.gemini_agent import GeminiAgent
from dispatch import dispatch_one_issue


def load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v


def run_controlled_test(issue_id_to_test=None):
    load_env()
    db_url = os.environ["DATABASE_URL"]
    token = os.environ["GITHUB_DISPATCH_TOKEN"]
    session = create_github_session(token)

    # 1. Fetch user identity
    user_resp = gh_get(session, f"{GITHUB_API}/user")
    bot_username = user_resp.json()["login"]
    print(f"Authenticated bot user: {bot_username}")

    # 2. Select test issue from DB
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            if issue_id_to_test:
                cur.execute("""
                    SELECT i.id, i.repo_id, i.github_issue_number, i.title,
                           r.full_name, r.default_branch, r.language, r.fork_full_name
                    FROM issues i
                    JOIN repos r ON r.id = i.repo_id
                    WHERE i.id = %s
                """, (issue_id_to_test,))
            else:
                # Default: pick a small fast repo if possible, e.g. awesome-go or ECC
                cur.execute("""
                    SELECT i.id, i.repo_id, i.github_issue_number, i.title,
                           r.full_name, r.default_branch, r.language, r.fork_full_name
                    FROM issues i
                    JOIN repos r ON r.id = i.repo_id
                    WHERE i.status = 'discovered' AND r.is_active = TRUE
                    ORDER BY r.stars ASC
                    LIMIT 1
                """)
            row = cur.fetchone()

        if not row:
            print("No suitable test issue found in database!")
            return

        issue_id, repo_id, issue_number, title, full_name, default_branch, language, existing_fork = row
        print(f"\n--- TARGET ISSUE ---")
        print(f"Issue ID: {issue_id}")
        print(f"Repo: {full_name}")
        print(f"Issue #{issue_number}: {title}")
        print(f"Default branch: {default_branch}")
        print(f"Existing fork in DB: {existing_fork}")
        print("---------------------\n")

        # 3. Fetch upstream ref SHA before dispatch (for verification step 3)
        upstream_ref_before = gh_get(session, f"{GITHUB_API}/repos/{full_name}/git/ref/heads/{default_branch}").json()["object"]["sha"]

        # 4. Instantiate Gemini agent only
        agent = GeminiAgent(model_id="gemini-2.5-pro")

        # 5. Run dispatch_one_issue
        print("Executing dispatch_one_issue()...")
        dispatch_one_issue(
            conn, session, [agent],
            issue_id=issue_id,
            repo_id=repo_id,
            issue_number=issue_number,
            full_name=full_name,
            default_branch=default_branch,
            language=language,
            existing_fork=existing_fork,
        )

        # 6. Perform 10-Point Audit
        print("\n==================================================")
        print("         CONTROLLED DISPATCH AUDIT REPORT         ")
        print("==================================================")

        # Verification 1: Correct fork was used
        with conn.cursor() as cur:
            cur.execute("SELECT fork_full_name FROM repos WHERE id = %s", (repo_id,))
            repo_row = cur.fetchone()
            db_fork = repo_row[0] if repo_row else None
        v1_pass = db_fork and db_fork.startswith(f"{bot_username}/")
        print(f"1. Fork used: {db_fork} -> {'PASS' if v1_pass else 'FAIL'}")

        # Verification 2 & 6: Branch exists on fork & runs.branch_name matches
        branch_name = f"resilient/{issue_number}/{agent.name}"
        fork_ref_resp = gh_get(session, f"{GITHUB_API}/repos/{db_fork}/git/ref/heads/{branch_name}")
        v2_pass = (fork_ref_resp.status_code == 200)
        print(f"2. Branch '{branch_name}' on fork: {'PASS' if v2_pass else 'FAIL'}")

        # Verification 3: Upstream has NO new branch/commit
        upstream_ref_after = gh_get(session, f"{GITHUB_API}/repos/{full_name}/git/ref/heads/{default_branch}").json()["object"]["sha"]
        upstream_branch_check = gh_get(session, f"{GITHUB_API}/repos/{full_name}/git/ref/heads/{branch_name}")
        v3_pass = (upstream_ref_before == upstream_ref_after) and (upstream_branch_check.status_code == 404)
        print(f"3. Upstream untouched (SHA unchanged & branch absent): {'PASS' if v3_pass else 'FAIL'}")

        # Verification 4: Fork contains the branch commit
        fork_commit_sha = fork_ref_resp.json()["object"]["sha"] if v2_pass else None
        v4_pass = bool(fork_commit_sha)
        print(f"4. Fork branch commit SHA ({fork_commit_sha[:8] if fork_commit_sha else 'N/A'}): {'PASS' if v4_pass else 'FAIL'}")

        # Verification 5 & 10: PostgreSQL runs table state
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, agent_name, branch_name, status, finished_at, session_id, diff_url
                FROM runs
                WHERE issue_id = %s
            """, (issue_id,))
            run_rows = cur.fetchall()

        v10_pass = len(run_rows) == 1
        if v10_pass:
            r_id, r_agent, r_branch, r_status, r_finished, r_session, r_diff = run_rows[0]
            v5_pass = r_status in ("success", "failed", "timeout")
            v6_pass = (r_branch == branch_name) and (r_agent == agent.name)
            print(f"5. runs.status = '{r_status}': {'PASS' if v5_pass else 'FAIL'}")
            print(f"6. runs.branch_name = '{r_branch}': {'PASS' if v6_pass else 'FAIL'}")
            print(f"10. DB run row count = 1 (run ID {r_id}): PASS")
        else:
            v5_pass = v6_pass = False
            print(f"5. runs.status: FAIL (found {len(run_rows)} runs)")
            print(f"6. runs.branch_name: FAIL")
            print(f"10. DB run row count: FAIL")

        # Verification 7: issues.status = 'dispatched'
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM issues WHERE id = %s", (issue_id,))
            issue_status = cur.fetchone()[0]
        v7_pass = (issue_status == "dispatched")
        print(f"7. issues.status = '{issue_status}': {'PASS' if v7_pass else 'FAIL'}")

        # Verification 8: No unexpected PR was created
        prs_resp = gh_get(session, f"{GITHUB_API}/repos/{full_name}/pulls", params={"head": f"{bot_username}:{branch_name}"})
        v8_pass = (prs_resp.status_code == 200 and len(prs_resp.json()) == 0)
        print(f"8. No unexpected PR created on upstream: {'PASS' if v8_pass else 'FAIL'}")

        # Verification 9: Temporary clone was cleaned up
        temp_dirs = [d for d in os.listdir(tempfile.gettempdir()) if d.startswith(f"resilient-{issue_number}-")]
        v9_pass = len(temp_dirs) == 0
        print(f"9. Temp clone directory cleaned up: {'PASS' if v9_pass else 'FAIL'}")

        all_pass = all([v1_pass, v2_pass, v3_pass, v4_pass, v5_pass, v6_pass, v7_pass, v8_pass, v9_pass, v10_pass])
        print("==================================================")
        print(f"OVERALL AUDIT RESULT: {'[OK] ALL 10 CHECKS PASSED' if all_pass else '[FAIL] AUDIT FAILED'}")
        print("==================================================")

    finally:
        conn.close()


if __name__ == "__main__":
    issue_id_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_controlled_test(issue_id_arg)
