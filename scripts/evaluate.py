"""
Evaluation stage.

Runs after agent dispatch (see .github/workflows/evaluate.yml). Responsibilities:
  1. Find completed runs (status = 'success') that do not have an evaluation row.
  2. Clone the fork repository and checkout the agent's branch.
  3. Detect and run the project's test suite (pytest, npm test, go test, cargo test).
  4. Perform automated diff quality assessment.
  5. Compute a composite score using exact weights:
     composite = 0.5 * (1 if tests_passed is True else 0)
               + 0.4 * reviewer_score
               + 0.1 * (1 if tests_passed is not None else 0)
  6. Write row to evaluations table with per-run transaction isolation.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

import psycopg2

from github_utils import GITHUB_API, create_github_session, gh_get, sanitize_token

DB_URL = ""
DISPATCH_TOKEN = ""
TEST_TIMEOUT_SECONDS = 300


def find_unevaluated_runs(conn):
    """Find all runs with status = 'success' that lack an evaluation row."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT r.id, r.issue_id, r.agent_name, r.branch_name, r.diff_url,
                   i.github_issue_number, i.title,
                   repo.full_name, repo.fork_full_name, repo.default_branch, repo.language
            FROM runs r
            JOIN issues i ON i.id = r.issue_id
            JOIN repos repo ON repo.id = i.repo_id
            LEFT JOIN evaluations e ON e.run_id = r.id
            WHERE r.status = 'success'
              AND e.id IS NULL
            ORDER BY r.id ASC
        """)
        return cur.fetchall()


def detect_and_run_tests(work_dir: str, language: str = None):
    """Detect test framework and execute test suite with timeout.

    Returns:
        (tests_passed: bool | None, test_summary: str)
    """
    cmd = None
    lang_lower = (language or "").lower()

    # 1. Python Detection
    if os.path.exists(os.path.join(work_dir, "pytest.ini")) or \
       os.path.exists(os.path.join(work_dir, "conftest.py")) or \
       os.path.exists(os.path.join(work_dir, "pyproject.toml")) or \
       lang_lower == "python":
        cmd = ["pytest", "-v"]

    # 2. Node / JavaScript / TypeScript Detection
    elif os.path.exists(os.path.join(work_dir, "package.json")):
        pkg_path = os.path.join(work_dir, "package.json")
        try:
            with open(pkg_path, "r", encoding="utf-8") as f:
                pkg_data = json.load(f)
                if "test" in pkg_data.get("scripts", {}):
                    cmd = ["npm", "test"]
        except Exception:
            pass

    # 3. Go Detection
    elif os.path.exists(os.path.join(work_dir, "go.mod")) or lang_lower == "go":
        cmd = ["go", "test", "./..."]

    # 4. Rust Detection
    elif os.path.exists(os.path.join(work_dir, "Cargo.toml")) or lang_lower == "rust":
        cmd = ["cargo", "test"]

    # 5. Makefile fallback
    elif os.path.exists(os.path.join(work_dir, "Makefile")):
        cmd = ["make", "test"]

    if not cmd:
        return None, "No automated test suite detected"

    try:
        proc = subprocess.run(
            cmd, cwd=work_dir, capture_output=True, text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
        passed = (proc.returncode == 0)
        output = (proc.stdout + "\n" + proc.stderr).strip()
        summary = output[-1000:] if len(output) > 1000 else output
        return passed, sanitize_token(summary if summary else f"Command '{' '.join(cmd)}' exited with code {proc.returncode}")
    except subprocess.TimeoutExpired:
        return False, f"Test execution timed out after {TEST_TIMEOUT_SECONDS}s"
    except FileNotFoundError:
        return None, f"Test runner executable '{cmd[0]}' not installed on system"
    except Exception as exc:
        return False, sanitize_token(f"Test execution failed: {exc}")


def assess_code_quality(work_dir: str):
    """Analyze agent diff for code quality, structural sanity, and size.

    Returns:
        (reviewer_score: float, reviewer_notes: dict)
    """
    notes = {"syntax_valid": True, "diff_lines": 0, "findings": []}
    score = 0.85  # baseline score for successful diff generation

    try:
        diff_proc = subprocess.run(
            ["git", "diff", "HEAD~1..HEAD"],
            cwd=work_dir, capture_output=True, text=True
        )
        if diff_proc.returncode != 0:
            diff_proc = subprocess.run(
                ["git", "diff-tree", "--root", "-p", "HEAD"],
                cwd=work_dir, capture_output=True, text=True
            )

        diff_text = diff_proc.stdout
        diff_lines = len(diff_text.splitlines())
        notes["diff_lines"] = diff_lines

        if diff_lines == 0:
            notes["findings"].append("Empty changeset")
            return 0.0, notes

        if diff_lines > 500:
            score -= 0.15
            notes["findings"].append("Large diff size (>500 lines)")
        elif diff_lines > 200:
            score -= 0.05
            notes["findings"].append("Moderate diff size (>200 lines)")

        # Python syntax check if python files changed
        stat_proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1..HEAD"],
            cwd=work_dir, capture_output=True, text=True
        )
        if stat_proc.returncode != 0:
            stat_proc = subprocess.run(
                ["git", "diff-tree", "--root", "--name-only", "-r", "HEAD"],
                cwd=work_dir, capture_output=True, text=True
            )

        changed_files = [f.strip() for f in stat_proc.stdout.splitlines() if f.strip()]
        notes["changed_files"] = changed_files

        for f in changed_files:
            if f.endswith(".py") and os.path.exists(os.path.join(work_dir, f)):
                try:
                    with open(os.path.join(work_dir, f), "r", encoding="utf-8") as py_file:
                        compile(py_file.read(), f, "exec")
                except SyntaxError as syn_err:
                    notes["syntax_valid"] = False
                    notes["findings"].append(f"Syntax error in {f}: {syn_err.msg} (line {syn_err.lineno})")
                    score -= 0.40
                except UnicodeDecodeError:
                    notes["syntax_valid"] = False
                    notes["findings"].append(f"Encoding error in {f}: File is not valid UTF-8")
                    score -= 0.20

    except Exception as exc:
        notes["findings"].append(f"Diff evaluation warning: {exc}")

    clamped_score = max(0.0, min(1.0, round(score, 2)))
    return clamped_score, notes


def compute_composite_score(tests_passed: bool | None, reviewer_score: float) -> float:
    """Compute weighted composite score per ROADMAP.md spec (w1=0.5, w2=0.4, w3=0.1).

    composite = 0.5 * (1 if tests_passed is True else 0)
              + 0.4 * reviewer_score
              + 0.1 * (1 if tests_passed is not None else 0)
    """
    w1_test = 0.5 * (1.0 if tests_passed is True else 0.0)
    w2_rev = 0.4 * (reviewer_score if reviewer_score is not None else 0.5)
    w3_suite = 0.1 * (1.0 if tests_passed is not None else 0.0)
    return round(w1_test + w2_rev + w3_suite, 2)


def evaluate_run(conn, session, run_row):
    """Process a single run evaluation within a per-run transaction."""
    run_id, issue_id, agent_name, branch_name, diff_url, issue_num, issue_title, full_name, fork_full_name, default_branch, language = run_row
    print(f"Evaluating run #{run_id} ({agent_name} on {full_name}#{issue_num})...", file=sys.stderr)

    target_repo = fork_full_name or full_name
    clone_url = f"https://x-access-token:{DISPATCH_TOKEN}@github.com/{target_repo}.git"

    work_dir = tempfile.mkdtemp(prefix=f"resilient-eval-{run_id}-")
    try:
        # Clone fork branch
        clone_proc = subprocess.run(
            ["git", "clone", "--depth", "50", "--branch", branch_name, clone_url, work_dir],
            capture_output=True, text=True, timeout=120
        )
        if clone_proc.returncode != 0:
            sanitized_err = sanitize_token(clone_proc.stderr.strip())
            print(f"Failed to clone branch '{branch_name}': {sanitized_err}", file=sys.stderr)
            tests_passed, test_summary = False, f"Git clone failed: {sanitized_err}"
            reviewer_score, reviewer_notes = 0.0, {"findings": ["Git clone failed"]}
        else:
            tests_passed, test_summary = detect_and_run_tests(work_dir, language)
            reviewer_score, reviewer_notes = assess_code_quality(work_dir)

        composite = compute_composite_score(tests_passed, reviewer_score)

        # Insert evaluation row into database
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO evaluations (run_id, tests_passed, test_summary, reviewer_score, reviewer_notes, composite_score, evaluated_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (run_id) DO UPDATE SET
                    tests_passed = EXCLUDED.tests_passed,
                    test_summary = EXCLUDED.test_summary,
                    reviewer_score = EXCLUDED.reviewer_score,
                    reviewer_notes = EXCLUDED.reviewer_notes,
                    composite_score = EXCLUDED.composite_score,
                    evaluated_at = now()
            """, (run_id, tests_passed, test_summary, reviewer_score, json.dumps(reviewer_notes), composite))
        conn.commit()
        print(f"  Run #{run_id} evaluated: tests_passed={tests_passed}, reviewer={reviewer_score}, composite={composite}", file=sys.stderr)

    finally:
        _remove_readonly_dir(work_dir)


def _remove_readonly_dir(path):
    def _on_error(func, p, exc_info):
        import stat
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_on_error)


def main():
    global DB_URL, DISPATCH_TOKEN
    DB_URL = os.environ.get("DATABASE_URL", "").strip()
    DISPATCH_TOKEN = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip() or os.environ.get("GITHUB_SCAN_TOKEN", "").strip()

    if not DB_URL:
        print("Error: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    if not DISPATCH_TOKEN:
        print("Error: GITHUB_DISPATCH_TOKEN or GITHUB_SCAN_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    session = create_github_session(DISPATCH_TOKEN)
    conn = psycopg2.connect(DB_URL)
    try:
        unevaluated = find_unevaluated_runs(conn)
        print(f"Found {len(unevaluated)} unevaluated run(s).", file=sys.stderr)
        for run_row in unevaluated:
            try:
                evaluate_run(conn, session, run_row)
            except Exception as exc:
                conn.rollback()
                print(f"Error evaluating run #{run_row[0]}: {exc}", file=sys.stderr)

        print("\n=== Evaluation complete ===", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
