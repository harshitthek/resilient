"""
Unit test suite for Autonomous Memory Bank System (scripts/memory_utils.py).
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import memory_utils


class TestMemoryUtils(unittest.TestCase):
    def test_fetch_agent_memories_fallback(self):
        memories = memory_utils.fetch_agent_memories(conn=None)
        self.assertIn("global", memories)
        self.assertGreaterEqual(len(memories["global"]), 3)
        self.assertIn("Always check for None/null/undefined", memories["global"][0])

    def test_format_memory_prompt(self):
        memories = {
            "global": ["Global rule A", "Global rule B"],
            "repo": ["Repo convention X"]
        }
        prompt_text = memory_utils.format_memory_prompt(memories)
        self.assertIn("=== AUTONOMOUS MEMORY BANK & LEARNINGS ===", prompt_text)
        self.assertIn("Global rule A", prompt_text)
        self.assertIn("Repo convention X", prompt_text)

    def test_record_memory(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        success = memory_utils.record_memory(
            conn=mock_conn,
            scope="global",
            memory_type="pattern",
            content="Always use parameterized SQL queries."
        )
        self.assertTrue(success)
        mock_cursor.execute.assert_called_once()
        self.assertIn("INSERT INTO agent_memories", mock_cursor.execute.call_args[0][0])

    def test_synthesize_post_mortem_learning(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        learnings = memory_utils.synthesize_post_mortem_learning(
            conn=mock_conn,
            run_id=10,
            issue_title="Fix memory leak in parser",
            diff_text="",
            tests_passed=True,
            reviewer_notes={"findings": ["Maintainer Warning: Diff size exceeds 200 lines"]},
            repo_id=5
        )
        self.assertGreaterEqual(len(learnings), 2)
        self.assertTrue(any("Successful fix pattern" in l for l in learnings))
        self.assertTrue(any("Avoid pitfall" in l for l in learnings))


if __name__ == "__main__":
    unittest.main()
