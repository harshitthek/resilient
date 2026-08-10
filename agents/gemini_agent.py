"""
Gemini coding agent adapter.

Synchronous agent: dispatch() blocks until the agent loop finishes
(or times out), then returns a terminal RunResult.

Uses the google-genai SDK with function calling to give the model
read/write/execute capabilities within a cloned fork. The model
iterates: read code → reason → edit → test, until it either produces
a fix or exhausts the iteration/time budget.

The agent NEVER targets upstream. It clones the fork, works on the
dispatch branch, and pushes to the fork.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional

from agents.base import AgentAdapter, RepoContext, RunResult

# Lazy-import google.genai so the module can be imported for testing
# without the SDK installed. The actual SDK is only needed at dispatch time.
_genai_client = None


def _get_genai_client():
    """Lazy-initialize the Gemini client."""
    global _genai_client
    if _genai_client is None:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        _genai_client = genai.Client(api_key=api_key)
    return _genai_client


# --- Constants ---

MAX_ITERATIONS = 15       # max agent loop iterations
TIMEOUT_SECONDS = 300     # 5-minute execution timeout
MAX_FILE_SIZE = 50_000    # don't read files larger than 50KB into context
COMMAND_TIMEOUT = 60      # max seconds for a single shell command


# --- Tool functions ---
# These are called by the Gemini function-calling loop within the
# context of a cloned repo. They operate on the local filesystem.

class RepoTools:
    """Filesystem and command tools scoped to a cloned repo directory.

    Each instance is bound to a specific working directory (the clone).
    The tools are passed to Gemini as function-calling tools."""

    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def _safe_path(self, rel_path: str) -> str:
        """Resolve a relative path within the work dir, preventing
        directory traversal."""
        resolved = os.path.normpath(os.path.join(self.work_dir, rel_path))
        if not resolved.startswith(os.path.normpath(self.work_dir)):
            raise ValueError(f"Path traversal detected: {rel_path}")
        return resolved

    def read_file(self, path: str) -> str:
        """Read the contents of a file in the repository.

        Args:
            path: Relative path from the repository root.

        Returns:
            The file contents as a string, or an error message."""
        try:
            full_path = self._safe_path(path)
            if not os.path.isfile(full_path):
                return f"Error: {path} does not exist or is not a file"
            size = os.path.getsize(full_path)
            if size > MAX_FILE_SIZE:
                return f"Error: {path} is too large ({size} bytes, max {MAX_FILE_SIZE})"
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            return f"Error reading {path}: {e}"

    def write_file(self, path: str, content: str) -> str:
        """Write content to a file in the repository. Creates parent
        directories if needed.

        Args:
            path: Relative path from the repository root.
            content: The full file content to write.

        Returns:
            A confirmation message or an error message."""
        try:
            full_path = self._safe_path(path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} chars to {path}"
        except Exception as e:
            return f"Error writing {path}: {e}"

    def list_files(self, directory: str = ".") -> str:
        """List files and directories at the given path.

        Args:
            directory: Relative path from the repository root. Defaults to root.

        Returns:
            A newline-separated list of entries, or an error message."""
        try:
            full_path = self._safe_path(directory)
            if not os.path.isdir(full_path):
                return f"Error: {directory} is not a directory"
            entries = []
            for entry in sorted(os.listdir(full_path)):
                if entry.startswith(".git"):
                    continue  # skip .git internals
                entry_path = os.path.join(full_path, entry)
                marker = "/" if os.path.isdir(entry_path) else ""
                entries.append(f"{entry}{marker}")
            return "\n".join(entries) if entries else "(empty directory)"
        except Exception as e:
            return f"Error listing {directory}: {e}"

    def run_command(self, command: str) -> str:
        """Run a shell command in the repository directory.

        Commands are executed with a timeout. Use this for running tests,
        linting, or checking build output.

        Args:
            command: The shell command to run.

        Returns:
            Combined stdout and stderr output, truncated if too long."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
            )
            output = result.stdout + result.stderr
            # Truncate very long output to avoid blowing up context
            if len(output) > 10_000:
                output = output[:5_000] + "\n\n... (truncated) ...\n\n" + output[-3_000:]
            exit_info = f"\n[exit code: {result.returncode}]"
            return output + exit_info
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {COMMAND_TIMEOUT}s"
        except Exception as e:
            return f"Error running command: {e}"


# --- Git operations ---

def _clone_fork(clone_url: str, branch_name: str, work_dir: str):
    """Clone the fork and checkout the dispatch branch."""
    # Clone with limited depth to save time/bandwidth
    subprocess.run(
        ["git", "clone", "--depth", "50", "--branch", branch_name, clone_url, work_dir],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    # Configure git identity for commits
    subprocess.run(
        ["git", "config", "user.name", "Resilient Bot"],
        cwd=work_dir, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "resilient-bot@users.noreply.github.com"],
        cwd=work_dir, check=True, capture_output=True,
    )


def _commit_and_push(work_dir: str, issue_number: int):
    """Stage all changes, commit, and push. Returns True if there were
    changes to push, False if the working tree was clean."""
    # Check for changes
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=work_dir, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        return False  # no changes

    subprocess.run(
        ["git", "add", "-A"],
        cwd=work_dir, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"fix: address issue #{issue_number}\n\n"
         f"Automated fix by Resilient Gemini agent."],
        cwd=work_dir, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "push", "origin", "HEAD"],
        cwd=work_dir, check=True, capture_output=True, text=True,
        timeout=60,
    )
    return True


def _get_diff_stat(work_dir: str) -> str:
    """Get a summary of changes for logging."""
    result = subprocess.run(
        ["git", "diff", "--stat", "HEAD~1..HEAD"],
        cwd=work_dir, capture_output=True, text=True,
    )
    return result.stdout.strip()


# --- Agent loop ---

def _build_system_prompt(ctx: RepoContext) -> str:
    """Build the system prompt for the Gemini agent."""
    lang_hint = f"The repository is primarily written in {ctx.language}." if ctx.language else ""
    return f"""You are an expert software engineer working on a fix for a GitHub issue.

Repository: {ctx.upstream_full_name}
Issue #{ctx.issue_number}: {ctx.issue_title}
{lang_hint}

Issue description:
{ctx.issue_body}

You have access to the repository's source code through the provided tools.
Your goal is to understand the issue, find the relevant code, and implement a fix.

Guidelines:
- Use read_file and list_files to understand the codebase structure first.
- Make targeted, minimal changes that directly address the issue.
- If the repository has tests, run them after making changes to verify your fix.
- Do not modify files unrelated to the issue.
- Do not add unnecessary dependencies.
- If you cannot fix the issue, explain why clearly.

When you are done (either with a fix or having determined you cannot fix it),
respond with a clear summary of what you did."""


def _run_agent_loop(ctx: RepoContext, work_dir: str) -> RunResult:
    """Run the Gemini function-calling agent loop.

    Returns a terminal RunResult (success/failed/timeout)."""
    from google.genai import types

    client = _get_genai_client()
    tools = RepoTools(work_dir)

    # Build the tool list for Gemini function calling
    tool_functions = [tools.read_file, tools.write_file, tools.list_files, tools.run_command]

    system_prompt = _build_system_prompt(ctx)
    user_message = (
        f"Please fix the issue described above. Start by exploring the repository "
        f"structure and understanding the relevant code, then implement a fix."
    )

    start_time = time.time()

    try:
        # Use automatic function calling with an iteration limit.
        # The SDK handles the call-response loop automatically.
        response = client.models.generate_content(
            model=ctx.language and "gemini-2.5-pro" or "gemini-2.5-pro",  # always use pro
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=tool_functions,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=MAX_ITERATIONS,
                ),
                temperature=0.2,  # deterministic-ish for code
            ),
        )

        elapsed = time.time() - start_time
        if elapsed > TIMEOUT_SECONDS:
            return RunResult(status="timeout", error=f"Agent loop took {elapsed:.0f}s")

        # Check if the agent made any changes
        has_changes = _commit_and_push(work_dir, ctx.issue_number)
        if not has_changes:
            summary = response.text[:500] if response.text else "No explanation provided"
            return RunResult(
                status="failed",
                error=f"No changes produced. Agent response: {summary}",
            )

        # Success — changes were committed and pushed
        diff_stat = _get_diff_stat(work_dir)
        print(f"  Gemini produced changes:\n{diff_stat}", file=sys.stderr)
        return RunResult(status="success")

    except Exception as e:
        elapsed = time.time() - start_time
        if elapsed > TIMEOUT_SECONDS:
            return RunResult(status="timeout", error=f"Timed out after {elapsed:.0f}s: {e}")
        return RunResult(status="failed", error=f"Agent error: {e}")


def _remove_readonly(func, path, exc_info):
    import stat
    os.chmod(path, stat.S_IWRITE)
    func(path)


# --- Adapter ---

class GeminiAgent(AgentAdapter):
    """Synchronous Gemini coding agent.

    Uses Gemini 2.5 Pro with function calling to read, edit, and test
    code within a cloned fork. Blocks until the agent loop finishes."""

    def __init__(self, model_id: str = "gemini-2.5-pro"):
        self._model_id = model_id

    @property
    def name(self) -> str:
        return self._model_id

    @property
    def is_async(self) -> bool:
        return False

    def dispatch(self, ctx: RepoContext) -> RunResult:
        """Clone the fork, run the agent loop, commit and push.

        Returns a terminal RunResult (success/failed/timeout).
        Never returns 'pending'."""
        work_dir = None
        try:
            # Create a temporary directory for the clone
            work_dir = tempfile.mkdtemp(prefix=f"resilient-{ctx.issue_number}-{self.name}-")

            # Clone the fork and checkout the branch
            print(f"  Cloning {ctx.fork_full_name} branch {ctx.branch_name}...",
                  file=sys.stderr)
            _clone_fork(ctx.clone_url, ctx.branch_name, work_dir)

            # Run the agent loop
            print(f"  Starting Gemini agent loop (max {MAX_ITERATIONS} iterations, "
                  f"{TIMEOUT_SECONDS}s timeout)...", file=sys.stderr)
            result = _run_agent_loop(ctx, work_dir)

            return result

        except subprocess.CalledProcessError as e:
            error_msg = f"Git operation failed: {e.cmd} → {e.returncode}"
            if e.stderr:
                error_msg += f"\n{e.stderr[:500]}"
            return RunResult(status="failed", error=error_msg)
        except Exception as e:
            return RunResult(status="failed", error=f"Dispatch failed: {e}")
        finally:
            # Clean up the temporary clone
            if work_dir and os.path.exists(work_dir):
                try:
                    shutil.rmtree(work_dir, onerror=_remove_readonly)
                except Exception:
                    pass  # best-effort cleanup

    def poll(self, session_id: str) -> RunResult:
        """No-op for synchronous agents. Gemini dispatch() blocks until
        completion, so there's nothing to poll."""
        # This should never be called for a Gemini run in practice,
        # since Gemini runs go directly to a terminal state.
        return RunResult(status="failed", error="poll() called on synchronous agent")
