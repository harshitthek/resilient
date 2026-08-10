"""
Jules agent adapter (async).

Jules is Google's AI coding agent that runs on its own Cloud VMs.
It uses a fire-and-poll model:
  - dispatch() creates a task via the Jules REST API and returns 'pending'
  - poll() checks the task status and returns the current state

Jules v1alpha API: https://jules.googleapis.com/v1alpha/

IMPORTANT: The Jules auto-PR behavior must be verified with a throwaway
fork before production use. The locked contract says:
  - Do NOT set automationMode to AUTO_CREATE_PR
  - If Jules creates a PR on the fork anyway, that's acceptable (benign)
  - The submission stage creates the upstream PR, not Jules

This adapter does NOT create upstream PRs. It only targets our fork.
"""

import os
import sys
from typing import Optional

import requests

from agents.base import AgentAdapter, RepoContext, RunResult

JULES_API_BASE = "https://jules.googleapis.com/v1alpha"


class JulesAdapter(AgentAdapter):
    """Asynchronous Jules coding agent.

    dispatch() fires a task on Google's infrastructure and returns
    immediately with status='pending'. poll() checks the task state
    on subsequent invocations."""

    def __init__(self):
        self._api_key = os.environ.get("JULES_API_KEY")
        if not self._api_key:
            raise RuntimeError("JULES_API_KEY not set")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        })

    @property
    def name(self) -> str:
        return "jules"

    @property
    def is_async(self) -> bool:
        return True

    def dispatch(self, ctx: RepoContext) -> RunResult:
        """Create a Jules task targeting our fork branch.

        Returns RunResult(status='pending', session_id=...) on success.
        Returns RunResult(status='failed', error=...) if task creation fails.

        Never returns 'success' — Jules is async, completion is
        detected via poll()."""
        try:
            # Build the task request per Jules v1alpha API
            task_payload = {
                "repository": {
                    "gitUri": f"https://github.com/{ctx.fork_full_name}.git",
                    "branch": ctx.branch_name,
                },
                "task": {
                    "title": f"Fix #{ctx.issue_number}: {ctx.issue_title[:100]}",
                    "description": (
                        f"Repository: {ctx.upstream_full_name}\n"
                        f"Issue #{ctx.issue_number}: {ctx.issue_title}\n\n"
                        f"{ctx.issue_body[:3000]}"
                    ),
                },
                # Do NOT set automationMode to AUTO_CREATE_PR.
                # Per locked contract #6: Jules must not create a PR.
            }

            resp = self._session.post(
                f"{JULES_API_BASE}/tasks",
                json=task_payload,
                timeout=30,
            )

            if resp.status_code not in (200, 201):
                return RunResult(
                    status="failed",
                    error=f"Jules task creation failed: status={resp.status_code}, "
                          f"body={resp.text[:500]}",
                )

            task_data = resp.json()
            session_id = task_data.get("name") or task_data.get("taskId") or task_data.get("id")

            if not session_id:
                return RunResult(
                    status="failed",
                    error=f"Jules task created but no task ID in response: "
                          f"{resp.text[:500]}",
                )

            print(f"    Jules task created: {session_id}", file=sys.stderr)
            return RunResult(status="pending", session_id=session_id)

        except requests.Timeout:
            return RunResult(
                status="failed",
                error="Jules API timeout during task creation",
            )
        except Exception as e:
            return RunResult(
                status="failed",
                error=f"Jules dispatch error: {e}",
            )

    def poll(self, session_id: str) -> RunResult:
        """Check the status of a Jules task.

        Maps Jules task states to RunResult statuses:
          COMPLETED / SUCCEEDED → success
          FAILED               → failed
          CANCELLED            → failed
          (anything else)      → pending

        Returns the current status without modifying it."""
        try:
            resp = self._session.get(
                f"{JULES_API_BASE}/tasks/{session_id}",
                timeout=15,
            )

            if resp.status_code == 404:
                return RunResult(
                    status="failed",
                    error=f"Jules task {session_id} not found (404)",
                )

            if resp.status_code != 200:
                # Transient API error — keep polling, don't change status
                print(f"    Jules poll error for {session_id}: "
                      f"status={resp.status_code}", file=sys.stderr)
                return RunResult(status="pending", session_id=session_id)

            task_data = resp.json()
            task_state = (task_data.get("state") or task_data.get("status") or "").upper()

            if task_state in ("COMPLETED", "SUCCEEDED"):
                diff_url = task_data.get("diffUrl") or task_data.get("resultUrl")
                return RunResult(status="success", diff_url=diff_url)

            elif task_state in ("FAILED",):
                error_msg = task_data.get("error", {}).get("message", "Unknown Jules failure")
                return RunResult(status="failed", error=error_msg)

            elif task_state in ("CANCELLED",):
                return RunResult(
                    status="failed",
                    error="Jules task was cancelled",
                )

            else:
                # Still running: QUEUED, RUNNING, IN_PROGRESS, etc.
                return RunResult(status="pending", session_id=session_id)

        except requests.Timeout:
            # Transient — don't change status
            print(f"    Jules poll timeout for {session_id}", file=sys.stderr)
            return RunResult(status="pending", session_id=session_id)
        except Exception as e:
            # Transient — don't change status
            print(f"    Jules poll error for {session_id}: {e}", file=sys.stderr)
            return RunResult(status="pending", session_id=session_id)
