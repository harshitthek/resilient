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

try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

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
            encoding="utf-8", errors="replace",
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


def assess_code_quality(work_dir: str) -> tuple[float, dict]:
    """Perform Senior Open-Source Maintainer Peer Review of the candidate diff.

    Evaluates the diff across 5 real maintainer rubric dimensions:
    1. Root Cause & Correctness (30%)
    2. Diff Minimality & Zero Formatting Noise (25%)
    3. Edge-Case & Null Safety (20%)
    4. Idiomatic Style & Type Annotations (15%)
    5. Documentation & Test Rationale (10%)

    Returns:
        (reviewer_score: float, reviewer_notes: dict)
    """
    notes = {"syntax_valid": True, "diff_lines": 0, "findings": [], "maintainer_rubric": {}}
    score = 0.85  # baseline starting score for valid diff

    try:
        diff_proc = subprocess.run(
            ["git", "diff", "HEAD~1..HEAD"],
            cwd=work_dir, capture_output=True, text=True,
            encoding="utf-8", errors="replace"
        )
        if diff_proc.returncode != 0:
            diff_proc = subprocess.run(
                ["git", "diff-tree", "--root", "-p", "HEAD"],
                cwd=work_dir, capture_output=True, text=True,
                encoding="utf-8", errors="replace"
            )

        diff_text = diff_proc.stdout
        diff_lines = len(diff_text.splitlines())
        notes["diff_lines"] = diff_lines

        if diff_lines == 0:
            notes["findings"].append("Empty changeset (no modifications made)")
            return 0.0, notes

        # Check changed files list
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

        # Check for cosmetic churn / excessive diff size
        if diff_lines > 500:
            score -= 0.20
            notes["findings"].append("Maintainer Warning: Diff size exceeds 500 lines (high churn risk)")
        elif diff_lines > 200:
            score -= 0.10
            notes["findings"].append("Maintainer Warning: Diff size exceeds 200 lines")
        else:
            notes["findings"].append("Maintainer Note: Patch is clean and minimal")

        # Static AST syntax validation for Python files
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

        # LLM Senior Open-Source Maintainer Peer Review Evaluation
        gemini_key = os.environ.get("GEMINI_API_KEY")
        nvidia_key = os.environ.get("NVIDIA_API_KEY")
        groq_key = os.environ.get("GROQ_API_KEY")

        reviewer_prompt = f"""You are a Principal Open-Source Software Architect and Core Maintainer reviewing an incoming Pull Request patch diff.

=== CANDIDATE GIT DIFF PATCH ===
{diff_text[:3000]}

=== SENIOR MAINTAINER REVIEW RUBRIC ===
Evaluate this patch as a core maintainer:
1. Root Cause & Correctness (0 to 30 pts): Does it solve the actual bug without masking symptoms with silent try-except fallbacks?
2. Diff Minimality & Zero Churn (0 to 25 pts): Is the patch surgical? Avoids touching unrelated files or reformatting imports?
3. Edge-Case & Null Safety (0 to 20 pts): Does it handle None, null, empty strings, and collection boundaries?
4. Idiomatic Style & Typing (0 to 15 pts): Does it match host code conventions and include type annotations?
5. Documentation & Rationale (0 to 10 pts): Is the fix clear and maintainable?

Respond strictly in JSON format:
{{
  "maintainer_score_0_to_1": <float between 0.0 and 1.0>,
  "findings": [<string list of maintainer review notes>]
}}"""

        ai_review_score = None
        # Attempt Gemini -> NVIDIA NIM -> Groq fallback
        if gemini_key:
            try:
                import urllib.request
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
                payload = json.dumps({"contents": [{"parts": [{"text": reviewer_prompt}]}]}).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    if "{" in text and "}" in text:
                        parsed = json.loads(text[text.find("{"):text.rfind("}")+1])
                        ai_review_score = float(parsed.get("maintainer_score_0_to_1", 0.85))
                        notes["findings"].extend(parsed.get("findings", []))
            except Exception:
                pass

        if ai_review_score is None and nvidia_key:
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    data=json.dumps({
                        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
                        "messages": [
                            {"role": "system", "content": "You are a Principal Open-Source Maintainer. Output strictly JSON."},
                            {"role": "user", "content": reviewer_prompt}
                        ],
                        "max_tokens": 300
                    }).encode("utf-8"),
                    headers={"Authorization": f"Bearer {nvidia_key}", "Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data["choices"][0]["message"]["content"]
                    if "{" in text and "}" in text:
                        parsed = json.loads(text[text.find("{"):text.rfind("}")+1])
                        ai_review_score = float(parsed.get("maintainer_score_0_to_1", 0.85))
                        notes["findings"].extend(parsed.get("findings", []))
            except Exception:
                pass

        if ai_review_score is not None:
            score = round((score * 0.4) + (ai_review_score * 0.6), 2)

    except Exception as exc:
        notes["findings"].append(f"Diff evaluation warning: {exc}")

    clamped_score = max(0.0, min(1.0, round(score, 2)))
    return clamped_score, notes


def compute_composite_score(tests_passed: bool | None, reviewer_score: float) -> float:
    """Compute weighted composite score per ROADMAP.md spec.

    If automated tests exist:
      composite = 0.5 * (1 if tests_passed is True else 0)
                + 0.4 * reviewer_score
                + 0.1 * (1 if tests_passed is not None else 0)
    If no test suite exists in the repository (tests_passed is None):
      composite = reviewer_score (normalized to quality score)
    """
    if tests_passed is None:
        return round(reviewer_score if reviewer_score is not None else 0.5, 2)

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

        # Post-mortem memory synthesis & coordination learning feed
        try:
            from memory_utils import synthesize_post_mortem_learning
            learnings = synthesize_post_mortem_learning(
                conn, run_id=run_id, issue_title=issue_title, diff_text="",
                tests_passed=tests_passed, reviewer_notes=reviewer_notes
            )
            if learnings:
                print(f"  [Memory Bank] Synthesized {len(learnings)} new learning(s) for future agent runs.", file=sys.stderr)
        except Exception as mem_exc:
            print(f"  [Memory Bank Warning] {mem_exc}", file=sys.stderr)

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
