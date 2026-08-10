"""Regression tests for remediation findings in discovery and Gemini dispatch."""

import io
import os
import sys
import types
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

from agents.base import RepoContext
from agents import gemini_agent
from scripts import discover, dispatch
from tests.test_dispatch_crash import MockConnection


class TestDiscoveryConfiguration(unittest.TestCase):
    def test_missing_environment_is_reported_at_runtime(self):
        """Importing discovery must not require deployment secrets."""
        with patch.dict(os.environ, {"GITHUB_SCAN_TOKEN": "", "DATABASE_URL": ""}):
            stderr = io.StringIO()
            with patch.object(discover, "create_github_session") as create_session:
                with redirect_stderr(stderr):
                    configured = discover._configure_from_env()

        self.assertFalse(configured)
        create_session.assert_not_called()
        self.assertIn("GITHUB_SCAN_TOKEN", stderr.getvalue())
        self.assertIn("DATABASE_URL", stderr.getvalue())


class TestGeminiDispatch(unittest.TestCase):
    def test_selected_model_and_diff_url_are_returned(self):
        """Flash/Pro configuration must reach the SDK and persist a diff URL."""
        context = RepoContext(
            fork_full_name="bot/example",
            branch_name="resilient/17/gemini-2.5-flash",
            clone_url="https://example.invalid/bot/example.git",
            upstream_full_name="owner/example",
            default_branch="main",
            issue_number=17,
            issue_title="Fix sample bug",
            issue_body="A small reproducible issue",
            language="Python",
        )
        client = MagicMock()
        client.models.generate_content.return_value = types.SimpleNamespace(text="done")
        fake_genai = types.ModuleType("google.genai")
        fake_genai.types = types.SimpleNamespace(
            GenerateContentConfig=lambda **kwargs: kwargs,
            AutomaticFunctionCallingConfig=lambda **kwargs: kwargs,
        )
        fake_google = types.ModuleType("google")
        fake_google.genai = fake_genai

        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}):
            with patch.object(gemini_agent, "_get_genai_client", return_value=client):
                with patch.object(gemini_agent, "_commit_and_push", return_value=True):
                    with patch.object(gemini_agent, "_get_diff_stat", return_value="1 file changed"):
                        result = gemini_agent._run_agent_loop(
                            context, PROJECT_ROOT, "gemini-2.5-flash"
                        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.diff_url,
            "https://github.com/bot/example/compare/main...resilient/17/gemini-2.5-flash",
        )
        self.assertEqual(
            client.models.generate_content.call_args.kwargs["model"], "gemini-2.5-flash"
        )

    def test_jules_is_not_loaded_even_when_its_key_exists(self):
        """Jules remains off until its separate controlled validation."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test", "JULES_API_KEY": "test"}):
            agents = dispatch.load_agents()

        self.assertEqual([agent.name for agent in agents], ["gemini-2.5-pro", "gemini-2.5-flash"])


class TestRunErrorPersistence(unittest.TestCase):
    def test_terminal_error_is_saved(self):
        """A failed live agent run must retain its diagnostic detail."""
        conn = MockConnection()
        dispatch._update_run_from_result(
            conn,
            run_id=42,
            result=gemini_agent.RunResult(status="failed", error="Gemini API rejected request"),
        )
        update_query, parameters = next(
            (query, params) for query, params in conn.queries if "UPDATE runs" in query
        )
        self.assertIn("error = %s", update_query)
        self.assertIn("Gemini API rejected request", parameters)


if __name__ == "__main__":
    unittest.main()
