"""
Webhook glue -- complements discover.py rather than replacing it.

discover.py (cron) finds NEW trending repos, since "trending" is
inherently something you compute periodically. Once a repo is already
in our `repos` table, though, polling it every 3 hours for new issues
wastes API budget and adds latency. Install a GitHub App on tracked
repos and point its webhook here instead: new/labeled issues land in
the DB within seconds, no polling needed.

Deploy this as its own long-running service (see requirements-webhook.txt)
next to the orchestration DB -- it's lightweight, no agent work happens
here. Doesn't check for an already-linked PR, same as discover.py --
that's deferred to the dispatch stage, right before an agent starts work.
"""

import hashlib
import hmac
import os

import psycopg2
from flask import Flask, abort, request

app = Flask(__name__)
TARGET_LABELS = {"bug", "good first issue", "help wanted"}


def verify_signature(payload_body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
    if not webhook_secret:
        return False
    expected = "sha256=" + hmac.new(webhook_secret, payload_body, hashlib.sha256).hexdigest()
    # constant-time compare -- do not use `==` here, it leaks timing info
    return hmac.compare_digest(expected, signature_header)


@app.route("/webhook", methods=["POST"])
def webhook():
    if not verify_signature(request.data, request.headers.get("X-Hub-Signature-256")):
        abort(401)

    event = request.headers.get("X-GitHub-Event")
    payload = request.get_json(silent=True)
    if not payload:
        abort(400)

    if event == "issues" and payload.get("action") in ("opened", "labeled"):
        handle_issue_event(payload)
    elif event == "repository" and payload.get("action") == "archived":
        deactivate_repo(payload["repository"]["full_name"])
    elif event == "ping":
        pass  # GitHub sends this on webhook setup -- just acknowledge it

    return "", 204


def handle_issue_event(payload):
    # Keep original case for storage (matches discover.py), lowercase only
    # for the membership check -- otherwise the same label ends up stored
    # differently depending on which path (cron vs webhook) wrote it.
    raw_labels = [l["name"] for l in payload["issue"]["labels"]]
    labels_lower = {name.lower() for name in raw_labels}
    if not labels_lower & TARGET_LABELS:
        return  # not a genuine-improvement candidate by our criteria

    full_name = payload["repository"]["full_name"]
    conn = psycopg2.connect(os.environ.get("DATABASE_URL", ""))
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM repos WHERE full_name = %s AND is_active",
                (full_name,),
            )
            row = cur.fetchone()
            if not row:
                return  # only react to repos we're already tracking and
                        # haven't been told to leave alone
            repo_id = row[0]
            cur.execute(
                """
                INSERT INTO issues (repo_id, github_issue_number, title, labels)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (repo_id, github_issue_number) DO UPDATE SET
                    labels = EXCLUDED.labels,
                    title = EXCLUDED.title
                """,
                (repo_id, payload["issue"]["number"], payload["issue"]["title"], raw_labels),
            )
    finally:
        conn.close()


def deactivate_repo(full_name):
    """A repo we're tracking got archived -- stop touching it immediately
    rather than waiting for the next scheduled scan to notice."""
    conn = psycopg2.connect(os.environ.get("DATABASE_URL", ""))
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE repos SET is_active = FALSE, is_archived = TRUE WHERE full_name = %s",
                (full_name,),
            )
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 8000)))
