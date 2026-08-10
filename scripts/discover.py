"""
Discovery stage.

Run on a schedule (see .github/workflows/discover.yml). Responsibilities:
  1. Find candidate repos ("trending" via a star-delta snapshot, since
     GitHub's REST/Search API has no native trending endpoint).
  2. Check each repo's own docs for an AI-contribution policy, and skip
     (or flag disallowed) repos that say no.
  3. Pull open issues that look like genuine, maintainer-acknowledged
     improvement targets (labeled bug / good-first-issue / help-wanted).

Deliberately does NOT check whether an issue already has a linked PR --
that check is deferred to the dispatch stage, right before an agent
starts work. Doing it here as well would cost ~1 Search API call per
matching issue (600+ calls across a full scan) against a 30/min search
limit, and the answer can go stale in the gap between discovery and
dispatch anyway, so it's only checked once, where it actually matters.

Also deliberately does NOT fork, dispatch agents, or touch any repo's
issues/PRs -- this stage only reads.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2

from github_utils import (
    GITHUB_API,
    check_ai_policy,
    create_github_session,
    gh_get,
)

# Configuration is intentionally deferred to main() so that this module can
# be imported by tests or tooling without requiring deployment secrets.
TOKEN = ""
DB_URL = ""
SESSION = None

TARGET_LABELS = {"bug", "good first issue", "help wanted"}

MIN_STARS = 500        # floor so we're not scanning noise
SCAN_PAGE_SIZE = 30
MAX_REPOS_PER_RUN = 60  # cost/rate-limit guardrail


def find_candidate_repos():
    """Broad, legitimate star-count search (no scraping github.com/trending,
    which is fragile and against the spirit of the ToS for automated use).
    'Trending' itself is computed downstream from the stars/stars_prev delta
    once we've snapshotted a repo at least twice."""
    query = f"stars:>{MIN_STARS} pushed:>{recent_cutoff()}"
    resp = gh_get(
        SESSION,
        f"{GITHUB_API}/search/repositories",
        params={"q": query, "sort": "stars", "order": "desc", "per_page": SCAN_PAGE_SIZE},
    )
    return resp.json().get("items", [])[:MAX_REPOS_PER_RUN]


def recent_cutoff():
    return (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")


def fetch_open_issues(full_name):
    resp = gh_get(
        SESSION,
        f"{GITHUB_API}/repos/{full_name}/issues",
        params={"state": "open", "per_page": 50},
    )
    if resp.status_code != 200:
        return []
    # NOTE: this endpoint also returns PRs (GitHub treats PRs as issues
    # internally) -- filter those out explicitly.
    return [i for i in resp.json() if "pull_request" not in i]


def upsert_repo(conn, repo_json):
    """Writes only -- does not commit. Caller commits once per repo so a
    mid-repo failure rolls back cleanly instead of leaving partial state."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO repos (github_id, full_name, default_branch, language,
                                stars, stars_prev, stars_checked_at, is_archived, last_scanned_at)
            VALUES (%s, %s, %s, %s, %s,
                    (SELECT stars FROM repos WHERE github_id = %s), now(),
                    %s, now())
            ON CONFLICT (github_id) DO UPDATE SET
                full_name        = EXCLUDED.full_name,
                stars_prev       = repos.stars,
                stars            = EXCLUDED.stars,
                stars_checked_at = now(),
                is_archived      = EXCLUDED.is_archived,
                last_scanned_at  = now(),
                default_branch   = EXCLUDED.default_branch
            RETURNING id, is_active
            """,
            (
                repo_json["id"], repo_json["full_name"], repo_json["default_branch"],
                repo_json.get("language"), repo_json["stargazers_count"],
                repo_json["id"], repo_json["archived"],
            ),
        )
        return cur.fetchone()


def upsert_policy(conn, repo_id, status, source_file, snippet):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO repo_policies (repo_id, allows_ai_prs, source_file, matched_snippet, checked_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (repo_id) DO UPDATE SET
                allows_ai_prs = EXCLUDED.allows_ai_prs,
                source_file = EXCLUDED.source_file,
                matched_snippet = EXCLUDED.matched_snippet,
                checked_at = now()
            """,
            (repo_id, status, source_file, snippet),
        )


def deactivate_repo(conn, repo_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE repos SET is_active = FALSE WHERE id = %s", (repo_id,))


def upsert_issue(conn, repo_id, issue_json):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO issues (repo_id, github_issue_number, title, labels)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (repo_id, github_issue_number) DO UPDATE SET
                labels = EXCLUDED.labels,
                title = EXCLUDED.title
            """,
            (repo_id, issue_json["number"], issue_json["title"],
             [l["name"] for l in issue_json["labels"]]),
        )


def process_repo(conn, repo_json):
    """One repo's worth of work, all in the caller's transaction. Raises
    on unexpected failure -- main() catches it, rolls back just this
    repo, and moves on rather than losing the whole run."""
    if repo_json["archived"]:
        return

    repo_id, was_active = upsert_repo(conn, repo_json)
    if not was_active:
        return  # previously opted-out / disallowed -- respect it, don't re-scan issues

    policy_status, source_file, snippet = check_ai_policy(SESSION, repo_json["full_name"])
    upsert_policy(conn, repo_id, policy_status, source_file, snippet)
    if policy_status == "disallowed":
        deactivate_repo(conn, repo_id)
        return

    labeled_target = [
        i for i in fetch_open_issues(repo_json["full_name"])
        if TARGET_LABELS & {l["name"].lower() for l in i["labels"]}
    ]
    for issue in labeled_target:
        upsert_issue(conn, repo_id, issue)


def _configure_from_env():
    """Load and validate required runtime configuration."""
    global TOKEN, DB_URL, SESSION
    TOKEN = os.environ.get("GITHUB_SCAN_TOKEN", "")
    DB_URL = os.environ.get("DATABASE_URL", "")
    missing = [
        name for name, value in (
            ("GITHUB_SCAN_TOKEN", TOKEN),
            ("DATABASE_URL", DB_URL),
        ) if not value
    ]
    if missing:
        print(f"Error: missing required environment variable(s): {', '.join(missing)}",
              file=sys.stderr)
        return False
    SESSION = create_github_session(TOKEN)
    return True


def main():
    if not _configure_from_env():
        return 1

    conn = psycopg2.connect(DB_URL)
    try:
        repos = find_candidate_repos()
        print(f"Scanning {len(repos)} candidate repos")
        for repo_json in repos:
            try:
                process_repo(conn, repo_json)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                print(f"Skipping {repo_json.get('full_name')}: {exc}", file=sys.stderr)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
