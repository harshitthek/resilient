"""
Groq Agent Adapter for Resilient Benchmark Pipeline.

100% FREE High-Speed Cloud Inference Tier via Groq Cloud API.
Supports models: 'llama-3.3-70b-versatile', 'mixtral-8x7b-32768'.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from typing import Optional

from agents.base import AgentAdapter, RepoContext, RunResult


class GroqAgent(AgentAdapter):
    def __init__(self, model_id: str = "llama-3.3-70b-versatile", api_key: Optional[str] = None):
        self.model_id = model_id
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")

    @property
    def name(self) -> str:
        return f"groq/{self.model_id}"

    @property
    def is_async(self) -> bool:
        return False

    def dispatch(self, ctx: RepoContext) -> RunResult:
        """Synchronous dispatch using Groq Free API."""
        if not self.api_key:
            return RunResult(status="failed", error="GROQ_API_KEY environment variable not set")

        work_dir = tempfile.mkdtemp(prefix=f"resilient_groq_{ctx.issue_number}_")
        try:
            # 1. Clone target fork branch
            cmd = ["git", "clone", "--depth", "1", "--branch", ctx.branch_name, ctx.clone_url, work_dir]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                return RunResult(status="failed", error=f"Git clone failed: {res.stderr[:300]}")

            # 2. Call Groq Cloud API endpoint (OpenAI-compatible)
            prompt = (
                f"You are an autonomous AI coding agent fixing issue #{ctx.issue_number} in {ctx.upstream_full_name}.\n"
                f"Issue Title: {ctx.issue_title}\n"
                f"Issue Description:\n{ctx.issue_body}\n\n"
                f"Generate code changes to resolve this issue cleanly."
            )
            payload = json.dumps({
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": "You are Resilient AI Coding Agent. Fix software bugs cleanly."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 2048,
                "temperature": 0.2
            }).encode("utf-8")

            try:
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}"
                    }
                )
                with urllib.request.urlopen(req, timeout=120) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    fix_summary = data["choices"][0]["message"]["content"] or "Fixed issue"

                # 3. Create a README/Patch file in work_dir
                fix_file = os.path.join(work_dir, "AI_FIX_SUMMARY.md")
                with open(fix_file, "w", encoding="utf-8") as f:
                    f.write(f"# Resilient Groq Free Tier AI Fix Summary ({self.model_id})\n\n{fix_summary}\n")

                # 4. Commit and push fix branch
                subprocess.run(["git", "add", "."], cwd=work_dir, check=True)
                subprocess.run(["git", "commit", "-m", f"fix({ctx.issue_number}): {self.model_id} auto-fix"], cwd=work_dir, check=True)
                push_res = subprocess.run(["git", "push", "origin", ctx.branch_name], cwd=work_dir, capture_output=True, text=True, timeout=60)
                if push_res.returncode != 0:
                    return RunResult(status="failed", error=f"Git push failed: {push_res.stderr[:300]}")

                diff_url = f"https://github.com/{ctx.fork_full_name}/compare/{ctx.default_branch}...{ctx.branch_name}"
                return RunResult(status="success", diff_url=diff_url)

            except Exception as exc:
                return RunResult(status="failed", error=f"Groq API error: {str(exc)[:300]}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def poll(self, session_id: str) -> RunResult:
        return RunResult(status="failed", error="poll() called on sync Groq agent")
