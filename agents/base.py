"""
Agent adapter abstraction.

Defines the interface every agent (Jules, Gemini Pro, Gemini Flash, etc.)
must implement, plus the data classes shared between adapters and the
dispatch orchestrator.

The orchestrator only depends on this module -- it never imports
jules_adapter or gemini_agent directly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RepoContext:
    """Everything an agent needs to attempt a fix.

    The fork is the actual working target. Agents must NEVER
    receive upstream_full_name as their working repository --
    upstream is read-only context for understanding the issue."""

    # Fork (the agent's working target)
    fork_full_name: str       # e.g. "resilient-bot/some-repo"
    branch_name: str          # e.g. "resilient/42/gemini-2.5-pro"
    clone_url: str            # HTTPS clone URL of the fork

    # Upstream (read-only context)
    upstream_full_name: str   # e.g. "original-owner/some-repo"
    default_branch: str       # e.g. "main"

    # Issue details (fetched fresh at dispatch time)
    issue_number: int
    issue_title: str
    issue_body: str           # re-fetched at dispatch time, NOT from discovery

    # Repository metadata
    language: Optional[str] = None


@dataclass
class RunResult:
    """Result of a dispatch() or poll() call.

    Represents the outcome of a single agent attempt at fixing an issue.

    status must be one of:
    - 'pending'  (async agent dispatched, not yet complete)
    - 'success'  (agent completed, changes pushed to branch)
    - 'failed'   (agent failed -- no useful changes)
    - 'timeout'  (agent exceeded time limit)

    Terminal statuses (success, failed, timeout) must never be
    overwritten once stored in the database."""

    status: str               # 'pending' | 'success' | 'failed' | 'timeout'

    # Set when the agent produces changes (status='success')
    diff_url: Optional[str] = None

    # Set for async agents (status='pending')
    session_id: Optional[str] = None

    # Set on failure/timeout -- human-readable explanation
    error: Optional[str] = None


class AgentAdapter(ABC):
    """Abstract base for all agent adapters.

    Two execution models are supported:

    Synchronous (Gemini):
        dispatch() blocks until the agent finishes.
        Returns a terminal RunResult (success/failed/timeout).
        poll() is a no-op.

    Asynchronous (Jules):
        dispatch() fires the task and returns immediately.
        Returns RunResult(status='pending', session_id=...).
        poll() checks the external task and returns the current status.

    The orchestrator uses is_async to know whether to expect a
    terminal result from dispatch() or a pending one."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier stored in runs.agent_name.
        Must match the values in the schema comment:
        'jules' | 'gemini-2.5-pro' | 'gemini-2.5-flash'"""
        ...

    @property
    @abstractmethod
    def is_async(self) -> bool:
        """True if dispatch() returns 'pending' and poll() is meaningful.
        False if dispatch() blocks until completion."""
        ...

    @abstractmethod
    def dispatch(self, ctx: RepoContext) -> RunResult:
        """Start work on the issue.

        For sync agents: blocks until done, returns terminal RunResult.
        For async agents: fires the task, returns RunResult with
            status='pending' and session_id set.

        Must NEVER target upstream. The fork_full_name and branch_name
        in ctx are the working target."""
        ...

    @abstractmethod
    def poll(self, session_id: str) -> RunResult:
        """Check the status of an async task.

        For async agents: maps the external task state to a RunResult.
        For sync agents: returns the unchanged status (no-op).

        Must not overwrite terminal states -- if the run is already
        success/failed/timeout, return that status unchanged."""
        ...
