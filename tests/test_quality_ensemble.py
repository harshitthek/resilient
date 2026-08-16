"""
Unit tests for QualityEnsembleAgent (Quality-First Multi-Model Tournament & Consensus).
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from agents.base import RepoContext, RunResult
from agents.quality_ensemble_agent import QualityCandidate, QualityEnsembleAgent


class TestQualityEnsembleAgent(unittest.TestCase):

    def setUp(self):
        self.ctx = RepoContext(
            fork_full_name="harshitthek/resilient",
            branch_name="resilient/42/quality-tournament",
            clone_url="https://github.com/harshitthek/resilient.git",
            upstream_full_name="psf/requests",
            default_branch="main",
            issue_number=42,
            issue_title="Fix boundary condition in retry backoff",
            issue_body="When retry count is 0, backoff should return initial delay.",
            language="Python"
        )

    def test_agent_properties(self):
        agent = QualityEnsembleAgent()
        self.assertEqual(agent.name, "quality-ensemble-tournament")
        self.assertFalse(agent.is_async)
        poll_res = agent.poll("some_session")
        self.assertEqual(poll_res.status, "failed")

    def test_tournament_generation_and_ranking(self):
        agent = QualityEnsembleAgent(
            gemini_key="mock_gemini",
            nvidia_key="mock_nvapi",
            groq_key="mock_groq",
            cohere_key="mock_cohere"
        )

        with patch.object(agent, "_call_gemini", return_value="def backoff(n): return 1 if n <= 0 else 2**n"), \
             patch.object(agent, "_call_nvidia", return_value="{\"score_0_to_100\": 95, \"reasons\": [\"Robust boundary check\"]}"), \
             patch.object(agent, "_call_groq", return_value="def backoff(n): return max(1, 2**n)"):

            # 1. Distillation
            distilled = agent._distill_problem(self.ctx)
            self.assertTrue(len(distilled) > 0)

            # 2. Multi-Candidate generation
            candidates = agent._generate_candidate_patches(self.ctx, distilled)
            self.assertTrue(len(candidates) >= 2)

            # 3. Peer Review Scoring
            scores = [agent._peer_review_candidate(c, self.ctx) for c in candidates]
            self.assertTrue(all(s > 0 for s in scores))

    def test_dispatch_fails_gracefully_when_no_keys(self):
        agent = QualityEnsembleAgent(gemini_key="", nvidia_key="", groq_key="", cohere_key="")
        res = agent.dispatch(self.ctx)
        self.assertEqual(res.status, "failed")
        self.assertIn("No active model API keys found", res.error)

    def test_dispatch_clone_and_commit_workflow(self):
        agent = QualityEnsembleAgent(
            gemini_key="mock_gemini",
            nvidia_key="mock_nvapi",
            groq_key="mock_groq"
        )

        cand = QualityCandidate("nvidia/nemotron-3.5-lightning", "def fix(): return True")
        cand.reviewer_score = 96.0
        cand.reviewer_feedback = ["All edge cases passed"]

        with patch.object(agent, "_distill_problem", return_value="Root cause: edge case"), \
             patch.object(agent, "_generate_candidate_patches", return_value=[cand]), \
             patch.object(agent, "_verify_and_heal_candidate", return_value=cand), \
             patch.object(agent, "_peer_review_candidate", return_value=96.0), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

            res = agent.dispatch(self.ctx)
            self.assertEqual(res.status, "success")
            self.assertIn("resilient/42/quality-tournament", res.diff_url)


if __name__ == "__main__":
    unittest.main()
