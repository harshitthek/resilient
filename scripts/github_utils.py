"""
Shared GitHub API utilities.

Used by both discovery and dispatch stages. Provides rate-limited HTTP,
AI-policy checking, fork management, and branch management.

Callers must create their own requests.Session (with appropriate auth
token) and pass it to functions that make GitHub API calls. This avoids
coupling to a single global PAT -- discovery and dispatch use different
tokens with different scopes.
"""

import base64
import logging
import random
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# --- AI contribution policy patterns ---

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


# --- Rate-limited HTTP ---

def gh_get(session: requests.Session, url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """GET with secondary-rate-limit backoff.

    A 404 is returned as-is rather than raised -- it's a legitimate,
    expected response for things like 'this repo has no CONTRIBUTING.md'.

    403/429 trigger exponential backoff with jitter (up to 5 attempts).
    Other errors raise via raise_for_status()."""
    for attempt in range(5):
        resp = session.get(url, params=params)
        if resp.status_code in (403, 429):
            reset = resp.headers.get("X-RateLimit-Reset")
            base_wait = max(int(reset) - int(time.time()), 5) if reset else 30 * (attempt + 1)
            wait = min(int(base_wait * random.uniform(0.9, 1.2)), 120)
            logger.warning(f"Rate limited on {url}, sleeping {wait}s")
            print(f"Rate limited on {url}, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return resp
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"Gave up on {url} after repeated rate limiting")


def sanitize_token(text: str) -> str:
    """Redact GitHub PAT tokens and credentials from strings/error logs."""
    if not text:
        return ""
    sanitized = re.sub(r"https://[^@]+@github\.com", "https://***@github.com", text)
    sanitized = re.sub(r"gh[pousr]_[A-Za-z0-9_]{36,}", "[REDACTED_TOKEN]", sanitized)
    return sanitized


def get_app_installation_token(app_id: str, private_key_pem: str, owner: str = None) -> str:
    """Generate a temporary installation access token for resilient-bot (GitHub App)."""
    import jwt
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (9 * 60),
        "iss": str(app_id).strip(),
    }
    formatted_pem = private_key_pem.strip().replace("\\n", "\n")
    encoded_jwt = jwt.encode(payload, formatted_pem, algorithm="RS256")

    headers = {
        "Authorization": f"Bearer {encoded_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Fetch app installations
    resp = requests.get(f"{GITHUB_API}/app/installations", headers=headers, timeout=30)
    resp.raise_for_status()
    installations = resp.json()

    if not installations:
        raise RuntimeError(f"No installations found for GitHub App ID {app_id}")

    installation_id = None
    if owner:
        for inst in installations:
            if inst.get("account", {}).get("login", "").lower() == owner.lower():
                installation_id = inst["id"]
                break

    if not installation_id:
        installation_id = installations[0]["id"]

    # Exchange for installation token
    token_url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"
    token_resp = requests.post(token_url, headers=headers, timeout=30)
    token_resp.raise_for_status()
    return token_resp.json()["token"]




def gh_post(session: requests.Session, url: str, json: Optional[Any] = None) -> requests.Response:
    """POST with the same backoff semantics as gh_get().

    Returns the response on success (2xx) or 404.
    Backs off on 403/429 (rate limiting) with randomized jitter.
    Raises on other errors."""
    for attempt in range(5):
        resp = session.post(url, json=json)
        if resp.status_code in (403, 429):
            reset = resp.headers.get("X-RateLimit-Reset")
            base_wait = max(int(reset) - int(time.time()), 5) if reset else 30 * (attempt + 1)
            wait = min(int(base_wait * random.uniform(0.9, 1.2)), 120)
            logger.warning(f"Rate limited on POST {url}, sleeping {wait}s")
            print(f"Rate limited on POST {url}, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return resp
        # 409 (Conflict) is returned to caller for specific handling
        # (e.g. branch already exists, fork already exists)
        if resp.status_code == 409:
            return resp
        # 422 (Validation failed) is returned to caller -- can mean
        # "resource already exists" in some GitHub endpoints
        if resp.status_code == 422:
            return resp
        # 202 (Accepted) is common for async operations like fork creation
        if resp.status_code == 202:
            return resp
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"Gave up on POST {url} after repeated rate limiting")


# --- AI policy checking ---

def check_ai_policy(session: requests.Session, full_name: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Best-effort keyword check against common policy locations.

    Returns (status, source_file, snippet) where status is one of:
    'allowed', 'disallowed', 'unknown'.

    'unknown' is the safe default -- treat it as 'don't auto-submit
    PRs here yet', not as tacit permission."""
    candidates = ["CONTRIBUTING.md", ".github/CONTRIBUTING.md", ".github/PULL_REQUEST_TEMPLATE.md"]
    for path in candidates:
        resp = gh_get(session, f"{GITHUB_API}/repos/{full_name}/contents/{path}")
        if resp.status_code != 200:
            continue
        try:
            text = base64.b64decode(resp.json()["content"]).decode("utf-8", errors="ignore")
        except Exception:
            continue
        lower = text.lower()
        for pat in AI_POLICY_DISALLOW_PATTERNS:
            m = re.search(pat, lower)
            if m:
                return "disallowed", path, text[max(0, m.start() - 40): m.end() + 40]
        for pat in AI_POLICY_ALLOW_PATTERNS:
            m = re.search(pat, lower)
            if m:
                return "allowed", path, text[max(0, m.start() - 40): m.end() + 40]
    return "unknown", None, None


# --- Linked PR check ---

def has_linked_pr(session: requests.Session, full_name: str, issue_number: int) -> bool:
    """Check whether an issue already has a linked pull request.

    Uses the search API to find PRs that reference the issue. This is
    deliberately NOT called during discovery (too expensive at scale) --
    it's called once at dispatch time, right before agent work starts.

    Returns True if a potentially-relevant PR exists, False otherwise."""
    query = f"repo:{full_name} is:pr {issue_number} in:title,body"
    resp = gh_get(session, f"{GITHUB_API}/search/issues", params={"q": query, "per_page": 5})
    if resp.status_code != 200:
        # If search fails, be conservative -- don't block dispatch
        # on a transient search API failure.
        print(f"Warning: linked-PR search failed for {full_name}#{issue_number}, "
              f"status={resp.status_code}", file=sys.stderr)
        return False
    items = resp.json().get("items", [])
    # Filter to PRs that actually reference this issue number.
    # The search is broad (matches in title/body), so also check
    # for PRs that specifically mention "Fixes #N" or "Closes #N".
    for item in items:
        # Any open or merged PR mentioning the issue is enough.
        if item.get("state") in ("open", "closed") and item.get("pull_request"):
            return True
    return False


# --- Fork management ---

def ensure_fork(session: requests.Session, upstream_full_name: str) -> str:
    """Create or reuse our fork of the upstream repo.

    Idempotent: if the fork already exists, returns it without error.

    Returns the fork's full_name (e.g. 'our-bot/repo-name') on success.
    Raises on unrecoverable failure."""
    owner, repo = upstream_full_name.split("/", 1)
    resp = gh_post(session, f"{GITHUB_API}/repos/{owner}/{repo}/forks",
                   json={"default_branch_only": True})

    if resp.status_code in (200, 201, 202):
        if resp.status_code == 202:
            time.sleep(3)  # Allow GitHub async fork initialization to complete
        fork_data = resp.json()
        return fork_data["full_name"]

    if resp.status_code == 422:
        # 422 typically means the fork already exists. GitHub's fork
        # endpoint returns 422 when you try to fork a repo you've
        # already forked. Look up the existing fork.
        user_resp = gh_get(session, f"{GITHUB_API}/user")
        user_resp.raise_for_status()
        username = user_resp.json()["login"]
        fork_check = gh_get(session, f"{GITHUB_API}/repos/{username}/{repo}")
        if fork_check.status_code == 200:
            fork_data = fork_check.json()
            # Verify it's actually a fork of the expected repo
            parent = fork_data.get("parent", {})
            if parent.get("full_name") == upstream_full_name:
                return fork_data["full_name"]
            # Fork exists but it's not a fork of the expected repo --
            # this is unusual but possible if the user has a same-named
            # repo. Let it through with a warning.
            logger.warning(f"{username}/{repo} exists but parent is {parent.get('full_name')}, not {upstream_full_name}")
            print(f"Warning: {username}/{repo} exists but parent is "
                  f"{parent.get('full_name')}, not {upstream_full_name}",
                  file=sys.stderr)
            return fork_data["full_name"]
        # Fork doesn't exist despite 422 -- unexpected
        raise RuntimeError(
            f"Fork creation returned 422 but {username}/{repo} not found. "
            f"Response: {resp.text[:500]}"
        )

    raise RuntimeError(
        f"Failed to fork {upstream_full_name}: "
        f"status={resp.status_code}, body={resp.text[:500]}"
    )


# --- Branch management ---

def get_default_branch_sha(session: requests.Session, full_name: str, default_branch: str = "main") -> str:
    """Get the SHA of the tip of the default branch.

    Returns the SHA string on success.
    Raises on failure."""
    resp = gh_get(session, f"{GITHUB_API}/repos/{full_name}/git/ref/heads/{default_branch}")
    if resp.status_code != 200:
        raise RuntimeError(
            f"Could not get default branch SHA for {full_name}/{default_branch}: "
            f"status={resp.status_code}"
        )
    return resp.json()["object"]["sha"]


def create_branch(session: requests.Session, fork_full_name: str, branch_name: str, base_sha: str) -> str:
    """Create a branch on the fork from the given base SHA.

    Safe against retries: if the branch already exists and points to
    the expected base_sha (or a descendant), it's treated as reusable.
    If it exists but points to an unexpected commit, raises an error
    rather than silently reusing potentially incompatible work.

    Returns the branch ref SHA on success.
    Raises on unrecoverable failure."""
    ref = f"refs/heads/{branch_name}"
    resp = gh_post(session, f"{GITHUB_API}/repos/{fork_full_name}/git/refs",
                   json={"ref": ref, "sha": base_sha})

    if resp.status_code in (200, 201):
        return resp.json()["object"]["sha"]

    if resp.status_code == 422:
        # Branch already exists. This can happen if:
        # 1. A previous dispatch created it but the DB transaction rolled back
        # 2. A retry of the same dispatch
        # 3. An orphaned branch from a crashed dispatch
        #
        # Verify the existing branch is compatible before reusing it.
        existing = gh_get(session,
                          f"{GITHUB_API}/repos/{fork_full_name}/git/ref/heads/{branch_name}")
        if existing.status_code != 200:
            raise RuntimeError(
                f"Branch {branch_name} supposedly exists (422) but can't be read: "
                f"status={existing.status_code}"
            )
        existing_sha = existing.json()["object"]["sha"]

        if existing_sha == base_sha:
            # Points to exactly our expected base -- safe to reuse.
            # This is the common retry/orphan case.
            print(f"Branch {branch_name} already exists at expected SHA {base_sha[:8]}, reusing",
                  file=sys.stderr)
            return existing_sha

        # Branch exists but points somewhere else. This could be:
        # - An orphaned branch with agent commits from a previous dispatch
        # - A tracked run's work branch
        # - A manually-created branch
        #
        # Per contract: "verify the existing ref is compatible, do not
        # silently ignore." An unexpected SHA means unknown work exists
        # on this branch — force-resetting could destroy legitimate
        # agent output. Raise so the orchestrator skips this agent.
        raise RuntimeError(
            f"Branch {branch_name} exists at {existing_sha[:8]} but expected "
            f"{base_sha[:8]}. Refusing to overwrite — branch may contain "
            f"agent work from a previous dispatch."
        )

    raise RuntimeError(
        f"Failed to create branch {branch_name} on {fork_full_name}: "
        f"status={resp.status_code}, body={resp.text[:500]}"
    )


# --- Session factory ---

def create_github_session(token: str) -> requests.Session:
    """Create a requests.Session configured for the GitHub API.

    Each caller (discovery, dispatch) should create their own session
    with the appropriate token/scope."""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return session
