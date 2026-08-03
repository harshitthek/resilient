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
WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"].encode()
DB_URL = os.environ["DATABASE_URL"]
TARGET_LABELS = {"bug", "good first issue", "help wanted"}


def verify_signature(payload_body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET, payload_body, hashlib.sha256).hexdigest()
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

