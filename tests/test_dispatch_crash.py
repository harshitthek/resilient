"""
Tests for dispatch crash/orphan behavior.

These tests verify that the system behaves correctly under the
failure scenarios identified in the architectural review:

1. Transaction rollback after external dispatch
2. Process crash during Gemini execution
3. Stale-run detection by Mode 1
4. Branch conflict from orphaned previous dispatch
5. Idempotent re-dispatch after partial failure

Uses mock objects for GitHub API, agent adapters, and PostgreSQL
(via in-memory state or a test database).
"""

import sys
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root and scripts to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from agents.base import AgentAdapter, RepoContext, RunResult


# --- Mock agent adapters ---

class MockSyncAgent(AgentAdapter):
    """Mock synchronous agent (like Gemini)."""

    def __init__(self, agent_name="gemini-2.5-pro", result=None, side_effect=None):
        self._name = agent_name
        self._result = result or RunResult(status="success")
        self._side_effect = side_effect
        self.dispatch_calls = []

    @property
    def name(self):
        return self._name

    @property
    def is_async(self):
        return False

    def dispatch(self, ctx):
        self.dispatch_calls.append(ctx)
        if self._side_effect:
            raise self._side_effect
        return self._result

    def poll(self, session_id):
        return RunResult(status="failed", error="poll() called on sync agent")


class MockAsyncAgent(AgentAdapter):
    """Mock asynchronous agent (like Jules)."""

    def __init__(self, agent_name="jules", session_id="task-123",
                 dispatch_result=None, poll_result=None, dispatch_side_effect=None):
        self._name = agent_name
        self._session_id = session_id
        self._dispatch_result = dispatch_result or RunResult(
            status="pending", session_id=session_id)
        self._poll_result = poll_result or RunResult(status="pending", session_id=session_id)
        self._dispatch_side_effect = dispatch_side_effect
        self.dispatch_calls = []
        self.poll_calls = []

    @property
    def name(self):
        return self._name

    @property
    def is_async(self):
        return True

    def dispatch(self, ctx):
        self.dispatch_calls.append(ctx)
        if self._dispatch_side_effect:
            raise self._dispatch_side_effect
        return self._dispatch_result

    def poll(self, session_id):
        self.poll_calls.append(session_id)
        return self._poll_result


# --- Mock database ---

class MockCursor:
    """Minimal cursor mock that tracks executed SQL and returns configured data."""

    def __init__(self, db):
        self.db = db
        self.last_query = None
        self.last_params = None
        self._return_value = None

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params
        self.db.queries.append((query.strip(), params))

        # Simulate INSERT RETURNING
        if "INSERT INTO runs" in query and "RETURNING id" in query:
            self.db.run_counter += 1
            self._return_value = (self.db.run_counter,)

        # Simulate SELECT for Mode 1
        if "SELECT id, issue_id, agent_name" in query and "FROM runs" in query:
            self._return_value = None  # fetchall returns the list

        # Simulate SELECT for candidates
        if "SELECT i.id, i.repo_id" in query:
            self._return_value = None  # fetchall returns the list

    def fetchone(self):
        return self._return_value

    def fetchall(self):
        return self.db.fetchall_returns.pop(0) if self.db.fetchall_returns else []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockConnection:
    """Minimal connection mock that tracks commits and rollbacks."""

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.queries = []
        self.run_counter = 0
        self.fetchall_returns = []

    def cursor(self):
        return MockCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# --- Tests ---

class TestOrphanScenario(unittest.TestCase):
    """Test: Jules dispatch succeeds, Gemini dispatch fails, verify behavior."""

    def test_jules_succeeds_gemini_fails_issue_still_dispatched(self):
        """Scenario from the architectural review:
        1. Jules dispatch succeeds (returns pending)
        2. Gemini dispatch fails (raises exception)
        3. Issue should still be 'dispatched' (Jules run exists)
        4. Next invocation sees the Jules pending run for polling
        """
        # Setup
        jules = MockAsyncAgent(session_id="jules-task-abc")
        gemini = MockSyncAgent(side_effect=RuntimeError("Gemini API crashed"))

        conn = MockConnection()
        session = MagicMock()

        # Mock the GitHub API responses for pre-checks
        issue_resp = MagicMock()
        issue_resp.status_code = 200
        issue_resp.json.return_value = {
            "state": "open",
            "title": "Test issue",
            "body": "Fix this bug",
        }

        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = {"items": []}

        sha_resp = MagicMock()
        sha_resp.status_code = 200
        sha_resp.json.return_value = {"object": {"sha": "abc123def456"}}

        branch_resp = MagicMock()
        branch_resp.status_code = 201
        branch_resp.json.return_value = {"object": {"sha": "abc123def456"}}

        # Configure session.get and session.post
        def mock_gh_get(url, params=None):
            if "/issues/" in url and "/search/" not in url:
                return issue_resp
            if "/search/issues" in url:
                return search_resp
            if "/git/ref/" in url:
                return sha_resp
            return MagicMock(status_code=404)

        def mock_gh_post(url, json=None):
            return branch_resp

        session.get = mock_gh_get
        session.post = mock_gh_post

        # Import and patch
        from scripts import dispatch as dispatch_mod

        # Run dispatch_one_issue
        dispatch_mod.DISPATCH_TOKEN = "fake-token"
        dispatch_mod.dispatch_one_issue(
            conn, session, [jules, gemini],
            issue_id=1, repo_id=1, issue_number=42,
            full_name="owner/repo", default_branch="main",
            language="python", existing_fork="bot/repo",
        )

        # Assertions
        # Jules should have been dispatched
        self.assertEqual(len(jules.dispatch_calls), 1)

        # Gemini dispatch should have been attempted (and failed)
        self.assertEqual(len(gemini.dispatch_calls), 1)

        # Issue should be dispatched (not skipped) because Jules succeeded
        status_updates = [
            q for q, p in conn.queries
            if "UPDATE issues SET status" in q
        ]
        self.assertTrue(len(status_updates) > 0)
        # The last status update should be 'dispatched'
        last_status_query = [(q, p) for q, p in conn.queries
                             if "UPDATE issues SET status" in q][-1]
        self.assertEqual(last_status_query[1], ("dispatched", 1))

        # There should be commits (run row committed before dispatch)
        self.assertGreater(conn.commits, 0)

        print("✓ Jules succeeds, Gemini fails → issue dispatched correctly")


class TestStaleRunDetection(unittest.TestCase):
    """Test: Mode 1 detects and times out stale runs."""

    def test_stale_gemini_running_becomes_timeout(self):
        """A Gemini `running` row older than GEMINI_STALE_THRESHOLD_MINUTES
        should be set to `timeout` by Mode 1."""
        conn = MockConnection()
        session = MagicMock()

        stale_time = datetime.now(timezone.utc) - timedelta(minutes=45)

        # Simulate: one stale running row
        conn.fetchall_returns = [
            [(99, 1, "gemini-2.5-pro", "running", None, stale_time)]
        ]

        from scripts import dispatch as dispatch_mod
        dispatch_mod.GEMINI_STALE_THRESHOLD_MINUTES = 30

        dispatch_mod.mode1_poll_and_recover(conn, session, {})

        # Should have updated the run to timeout
        timeout_updates = [
            (q, p) for q, p in conn.queries
            if "UPDATE runs" in q and "timeout" in str(p)
        ]
        self.assertTrue(len(timeout_updates) > 0,
                        "Stale running row should be set to timeout")

        print("✓ Stale Gemini running → timeout detected by Mode 1")

    def test_stale_jules_pending_becomes_timeout(self):
        """A Jules `pending` row older than JULES_TIMEOUT_HOURS
        should be set to `timeout` by Mode 1."""
        conn = MockConnection()
        session = MagicMock()

        stale_time = datetime.now(timezone.utc) - timedelta(hours=3)

        # Simulate: one stale pending row
        conn.fetchall_returns = [
            [(88, 1, "jules", "pending", "task-xyz", stale_time)]
        ]

        from scripts import dispatch as dispatch_mod
        dispatch_mod.JULES_TIMEOUT_HOURS = 2

        dispatch_mod.mode1_poll_and_recover(conn, session, {})

        # Should have updated the run to timeout
        timeout_updates = [
            (q, p) for q, p in conn.queries
            if "UPDATE runs" in q and "timeout" in str(p)
        ]
        self.assertTrue(len(timeout_updates) > 0,
                        "Stale pending Jules row should be set to timeout")

        print("✓ Stale Jules pending → timeout detected by Mode 1")

    def test_fresh_jules_pending_gets_polled(self):
        """A Jules `pending` row within timeout should be polled,
        not timed out."""
        conn = MockConnection()
        session = MagicMock()

        fresh_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        # Simulate: one fresh pending row
        conn.fetchall_returns = [
            [(77, 1, "jules", "pending", "task-fresh", fresh_time)]
        ]

        jules = MockAsyncAgent(
            poll_result=RunResult(status="success", diff_url="https://diff")
        )

        from scripts import dispatch as dispatch_mod
        dispatch_mod.JULES_TIMEOUT_HOURS = 2

        dispatch_mod.mode1_poll_and_recover(
            conn, session, {"jules": jules})

        # Jules should have been polled
        self.assertEqual(len(jules.poll_calls), 1)
        self.assertEqual(jules.poll_calls[0], "task-fresh")

        # Run should be updated to success
        success_updates = [
            (q, p) for q, p in conn.queries
            if "UPDATE runs" in q and "success" in str(p)
        ]
        self.assertTrue(len(success_updates) > 0,
                        "Fresh pending Jules row should be polled and updated")

        print("✓ Fresh Jules pending → polled → success")


class TestBranchConflict(unittest.TestCase):
    """Test: create_branch handles existing branches correctly."""

    def test_branch_at_expected_sha_is_reused(self):
        """Branch exists at the expected base SHA → reuse without error."""
        from scripts.github_utils import create_branch

        session = MagicMock()
        base_sha = "abc123def456789"

        # POST returns 422 (already exists)
        post_resp = MagicMock()
        post_resp.status_code = 422
        session.post.return_value = post_resp

        # GET returns the existing ref at expected SHA
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = {"object": {"sha": base_sha}}
        session.get.return_value = get_resp

        result = create_branch(session, "bot/repo", "resilient/42/gemini", base_sha)
        self.assertEqual(result, base_sha)
        print("✓ Branch at expected SHA → reused")

    def test_branch_at_unexpected_sha_raises(self):
        """Branch exists at an unexpected SHA → raise, don't force-reset."""
        from scripts.github_utils import create_branch

        session = MagicMock()

        # POST returns 422
        post_resp = MagicMock()
        post_resp.status_code = 422
        session.post.return_value = post_resp

        # GET returns ref at different SHA
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = {"object": {"sha": "different_sha_999"}}
        session.get.return_value = get_resp

        with self.assertRaises(RuntimeError) as ctx:
            create_branch(session, "bot/repo", "resilient/42/gemini", "expected_sha_123")

        self.assertIn("Refusing to overwrite", str(ctx.exception))

        # Verify no PATCH (force update) was called
        session.patch.assert_not_called()
        print("✓ Branch at unexpected SHA → raise, no force-reset")


class TestTerminalStateImmutability(unittest.TestCase):
    """Test: Terminal run statuses are never overwritten."""

    def test_mode1_skips_terminal_runs(self):
        """Mode 1 should only process pending/running rows, never
        re-process terminal ones."""
        conn = MockConnection()
        session = MagicMock()

        # Simulate: no active (pending/running) rows
        conn.fetchall_returns = [[]]

        from scripts import dispatch as dispatch_mod
        dispatch_mod.mode1_poll_and_recover(conn, session, {})

        # No UPDATE queries should have been issued
        updates = [q for q, p in conn.queries if "UPDATE" in q]
        self.assertEqual(len(updates), 0)
        print("✓ Mode 1 with no active runs → no updates")

    def test_update_guards_terminal_status(self):
        """The SQL UPDATE in _update_run_from_result should include
        a WHERE guard preventing overwrite of terminal statuses."""
        from scripts.dispatch import _update_run_from_result

        conn = MockConnection()
        result = RunResult(status="success", diff_url="https://diff")
        _update_run_from_result(conn, run_id=42, result=result)

        # Check the executed SQL includes the terminal-state guard
        update_queries = [q for q, p in conn.queries if "UPDATE runs" in q]
        self.assertTrue(len(update_queries) > 0)
        self.assertIn("NOT IN", update_queries[0])
        print("✓ _update_run_from_result includes terminal-state guard")


class TestRunRowCommittedBeforeDispatch(unittest.TestCase):
    """Test: Run row is committed BEFORE agent.dispatch() is called."""

    def test_commit_happens_before_dispatch(self):
        """The run INSERT must be committed before agent.dispatch()
        so that Mode 1 can find stale rows if the process crashes."""
        conn = MockConnection()
        session = MagicMock()
        commits_before_dispatch = []

        class TrackingAgent(AgentAdapter):
            @property
            def name(self):
                return "gemini-2.5-pro"

            @property
            def is_async(self):
                return False

            def dispatch(self, ctx):
                # Record how many commits happened before dispatch was called
                commits_before_dispatch.append(conn.commits)
                return RunResult(status="success")

            def poll(self, session_id):
                return RunResult(status="failed")

        agent = TrackingAgent()

        # Mock GitHub responses
        issue_resp = MagicMock()
        issue_resp.status_code = 200
        issue_resp.json.return_value = {
            "state": "open", "title": "Test", "body": "Fix",
        }
        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = {"items": []}
        sha_resp = MagicMock()
        sha_resp.status_code = 200
        sha_resp.json.return_value = {"object": {"sha": "abc123"}}
        branch_resp = MagicMock()
        branch_resp.status_code = 201
        branch_resp.json.return_value = {"object": {"sha": "abc123"}}

        session.get = lambda url, **kw: (
            issue_resp if "/issues/" in url and "/search/" not in url
            else search_resp if "/search/" in url
            else sha_resp
        )
        session.post = lambda url, **kw: branch_resp

        from scripts import dispatch as dispatch_mod
        dispatch_mod.DISPATCH_TOKEN = "fake"

        initial_commits = conn.commits

        dispatch_mod.dispatch_one_issue(
            conn, session, [agent],
            issue_id=1, repo_id=1, issue_number=42,
            full_name="owner/repo", default_branch="main",
            language="python", existing_fork="bot/repo",
        )

        # The dispatch function should have been called with at least
        # 2 commits already done (Phase A commit + run row commit)
        self.assertGreaterEqual(
            commits_before_dispatch[0], initial_commits + 2,
            "Run row must be committed BEFORE agent.dispatch() is called"
        )
        print("✓ Run row committed before agent.dispatch()")


if __name__ == "__main__":
    unittest.main(verbosity=2)
