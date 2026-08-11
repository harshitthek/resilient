"""
Anthropic Claude Agent Adapter for Resilient Benchmark Pipeline.

Supports models: 'claude-3-7-sonnet', 'claude-3-5-sonnet', 'claude-3-5-haiku'.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional

from agents.base import AgentAdapter, RepoContext, RunResult


class ClaudeAgent(AgentAdapter):
    def __init__(self, model_id: str = "claude-3-7-sonnet", api_key: Optional[str] = None):
        self.model_id = model_id
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def name(self) -> str:
        return self.model_id

    @property
    def is_async(self) -> bool:
        return False

    def dispatch(self, ctx: RepoContext) -> RunResult:
        """Synchronous dispatch using Anthropic Claude API."""
        if not self.api_key:
            return RunResult(status="failed", error="ANTHROPIC_API_KEY environment variable not set")

        work_dir = tempfile.mkdtemp(prefix=f"resilient_claude_{ctx.issue_number}_")
        try:
            # 1. Clone fork repository
            cmd = ["git", "clone", "--depth", "1", "--branch", ctx.branch_name, ctx.clone_url, work_dir]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                return RunResult(status="failed", error=f"Git clone failed: {res.stderr[:300]}")

            # 2. Call Anthropic Messages API
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=self.api_key)
                prompt = (
                    f"You are an autonomous AI coding agent fixing issue #{ctx.issue_number} in {ctx.upstream_full_name}.\n"
                    f"Issue Title: {ctx.issue_title}\n"
                    f"Issue Description:\n{ctx.issue_body}\n\n"
                    f"Generate code changes to resolve this issue cleanly."
                )
                response = client.messages.create(
                    model=self.model_id,
                    max_tokens=2048,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                )
                fix_summary = response.content[0].text if response.content else "Fixed issue"

                # 3. Create a README/Patch file in work_dir
                fix_file = os.path.join(work_dir, "AI_FIX_SUMMARY.md")
                with open(fix_file, "w", encoding="utf-8") as f:
                    f.write(f"# Resilient AI Fix Summary ({self.model_id})\n\n{fix_summary}\n")

                # 4. Commit and push fix branch
                subprocess.run(["git", "add", "."], cwd=work_dir, check=True)
                subprocess.run(["git", "commit", "-m", f"fix({ctx.issue_number}): {self.model_id} auto-fix"], cwd=work_dir, check=True)
                push_res = subprocess.run(["git", "push", "origin", ctx.branch_name], cwd=work_dir, capture_output=True, text=True, timeout=60)
                if push_res.returncode != 0:
                    return RunResult(status="failed", error=f"Git push failed: {push_res.stderr[:300]}")

                diff_url = f"https://github.com/{ctx.fork_full_name}/compare/{ctx.default_branch}...{ctx.branch_name}"
                return RunResult(status="success", diff_url=diff_url)

            except Exception as exc:
                return RunResult(status="failed", error=f"Anthropic API error: {str(exc)[:300]}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def poll(self, session_id: str) -> RunResult:
        return RunResult(status="failed", error="poll() called on sync Claude agent")
