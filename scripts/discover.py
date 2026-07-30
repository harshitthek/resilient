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

import base64
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import psycopg2
import requests

GITHUB_API = "https://api.github.com"
TOKEN = os.environ["GITHUB_SCAN_TOKEN"]  # PAT with public_repo scope -- NOT the default
                                          # Actions GITHUB_TOKEN, which can't search
                                          # outside the current repo.
DB_URL = os.environ["DATABASE_URL"]

SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
})

TARGET_LABELS = {"bug", "good first issue", "help wanted"}
AI_POLICY_DISALLOW_PATTERNS = [
    r"no\s+ai[-\s]generated\s+(pull requests|prs|code)",
    r"do not (submit|open)\s+ai[-\s]generated",
    r"ai[-\s]generated (pull requests|contributions) (are|will be) (not accepted|rejected|closed)",
    r"no\s+llm[-\s]generated",
]
AI_POLICY_ALLOW_PATTERNS = [
    r"ai[-\s]assisted contributions? (are\s+)?welcome",
    r"we welcome ai[-\s]generated",
]

MIN_STARS = 500        # floor so we're not scanning noise
SCAN_PAGE_SIZE = 30
MAX_REPOS_PER_RUN = 60  # cost/rate-limit guardrail


def gh_get(url, params=None):
    """GET with basic secondary-rate-limit backoff. Search endpoints have
    a much stricter limit (30 req/min) than core REST (5000 req/hr for an
    authenticated PAT), so we back off conservatively on any 403/429.

    A 404 is returned as-is rather than raised -- it's a legitimate,
    expected response for things like "this repo has no CONTRIBUTING.md",
    and callers need to be able to tell that apart from a real failure."""
    for attempt in range(5):
        resp = SESSION.get(url, params=params)
        if resp.status_code in (403, 429):
            reset = resp.headers.get("X-RateLimit-Reset")
            wait = max(int(reset) - int(time.time()), 5) if reset else 30 * (attempt + 1)
            print(f"Rate limited on {url}, sleeping {wait}s", file=sys.stderr)
            time.sleep(min(wait, 120))
            continue
        if resp.status_code == 404:
            return resp
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"Gave up on {url} after repeated rate limiting")


def find_candidate_repos():
    """Broad, legitimate star-count search (no scraping github.com/trending,
    which is fragile and against the spirit of the ToS for automated use).
    'Trending' itself is computed downstream from the stars/stars_prev delta
    once we've snapshotted a repo at least twice."""
    query = f"stars:>{MIN_STARS} pushed:>{recent_cutoff()}"
    resp = gh_get(
        f"{GITHUB_API}/search/repositories",
        params={"q": query, "sort": "stars", "order": "desc", "per_page": SCAN_PAGE_SIZE},
    )
    return resp.json().get("items", [])[:MAX_REPOS_PER_RUN]


def recent_cutoff():
    return (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")

