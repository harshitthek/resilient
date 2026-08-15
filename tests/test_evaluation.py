"""
Unit test suite for Stage 3: Evaluation (scripts/evaluate.py).
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Add scripts directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import evaluate


class TestTestFrameworkDetection(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        evaluate._remove_readonly_dir(self.test_dir)

    def test_python_detection_via_conftest(self):
        with open(os.path.join(self.test_dir, "conftest.py"), "w") as f:
            f.write("# conftest\n")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
            passed, summary = evaluate.detect_and_run_tests(self.test_dir, language="python")
            self.assertTrue(passed)
            self.assertIn("1 passed", summary)
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0], ["pytest", "-v"])

    def test_node_detection_via_package_json(self):
        pkg_json = {"name": "test-pkg", "scripts": {"test": "mocha"}}
        with open(os.path.join(self.test_dir, "package.json"), "w") as f:
            json.dump(pkg_json, f)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="passing tests", stderr="")
            passed, summary = evaluate.detect_and_run_tests(self.test_dir)
            self.assertTrue(passed)
            self.assertEqual(mock_run.call_args[0][0], ["npm", "test"])

    def test_go_detection_via_gomod(self):
        with open(os.path.join(self.test_dir, "go.mod"), "w") as f:
            f.write("module test\n")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="PASS", stderr="")
            passed, summary = evaluate.detect_and_run_tests(self.test_dir)
            self.assertTrue(passed)
            self.assertEqual(mock_run.call_args[0][0], ["go", "test", "./..."])

    def test_rust_detection_via_cargotoml(self):
        with open(os.path.join(self.test_dir, "Cargo.toml"), "w") as f:
            f.write("[package]\nname = \"test\"\n")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="test result: ok", stderr="")
            passed, summary = evaluate.detect_and_run_tests(self.test_dir)
            self.assertTrue(passed)
            self.assertEqual(mock_run.call_args[0][0], ["cargo", "test"])

    def test_no_test_suite_returns_none(self):
        passed, summary = evaluate.detect_and_run_tests(self.test_dir)
        self.assertIsNone(passed)
        self.assertEqual(summary, "No automated test suite detected")


class TestScoringLogic(unittest.TestCase):
    def test_composite_score_tests_pass(self):
        # tests_passed=True, reviewer_score=0.85
        # 0.5*1.0 + 0.4*0.85 + 0.1*1.0 = 0.5 + 0.34 + 0.1 = 0.94
        score = evaluate.compute_composite_score(tests_passed=True, reviewer_score=0.85)
        self.assertEqual(score, 0.94)

    def test_composite_score_tests_fail(self):
        # tests_passed=False, reviewer_score=0.70
        # 0.5*0.0 + 0.4*0.70 + 0.1*1.0 = 0.0 + 0.28 + 0.1 = 0.38
        score = evaluate.compute_composite_score(tests_passed=False, reviewer_score=0.70)
        self.assertEqual(score, 0.38)

    def test_composite_score_no_test_suite(self):
        # tests_passed=None, reviewer_score=0.80 -> normalized composite score = 0.80
        score = evaluate.compute_composite_score(tests_passed=None, reviewer_score=0.80)
        self.assertEqual(score, 0.80)


class TestCodeQualityAssessment(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        evaluate._remove_readonly_dir(self.test_dir)

    def test_empty_diff_returns_zero(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            score, notes = evaluate.assess_code_quality(self.test_dir)
            self.assertEqual(score, 0.0)
            self.assertIn("Empty changeset", notes["findings"])

    def test_valid_diff_returns_score(self):
        with patch("subprocess.run") as mock_run:
            # Mock git diff and git diff --name-only
            mock_run.side_effect = [
                MagicMock(stdout="diff --git a/main.py b/main.py\n+print('hello')", returncode=0),
                MagicMock(stdout="main.py\n", returncode=0),
            ]
            score, notes = evaluate.assess_code_quality(self.test_dir)
            self.assertEqual(score, 0.85)
            self.assertTrue(notes["syntax_valid"])

    def test_large_diff_penalty(self):
        with patch("subprocess.run") as mock_run:
            large_diff = "line\n" * 550
            mock_run.side_effect = [
                MagicMock(stdout=large_diff, returncode=0),
                MagicMock(stdout="main.py\n", returncode=0),
            ]
            score, notes = evaluate.assess_code_quality(self.test_dir)
            self.assertEqual(score, 0.70)
            self.assertIn("Large diff size (>500 lines)", notes["findings"])

    def test_timeout_execution_handled(self):
        import subprocess
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["pytest"], timeout=300)
            passed, summary = evaluate.detect_and_run_tests(self.test_dir, language="python")
            self.assertFalse(passed)
            self.assertIn("timed out after 300s", summary)


class TestEvaluationPipeline(unittest.TestCase):
    def test_find_unevaluated_runs(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [(1, 10, "gemini-2.5-flash", "resilient/1/gemini", "http://diff", 1, "Title", "repo", "fork", "main", "python")]

        runs = evaluate.find_unevaluated_runs(mock_conn)
        self.assertEqual(len(runs), 1)
        mock_cursor.execute.assert_called_once()
class TestTokenSanitization(unittest.TestCase):
    def test_token_redaction_in_urls(self):
        raw_err = "fatal: clone failed https://x-access-token:ghp_1234567890abcdef1234567890abcdef1234@github.com/org/repo.git"
        clean_err = evaluate.sanitize_token(raw_err)
        self.assertNotIn("ghp_1234567890abcdef1234567890abcdef1234", clean_err)
        self.assertIn("https://***@github.com", clean_err)

    def test_raw_pat_token_redaction(self):
        raw_token = "Failed with token ghp_ABCDEF1234567890abcdef12345678901234"
        clean = evaluate.sanitize_token(raw_token)
        self.assertNotIn("ghp_ABCDEF1234567890abcdef12345678901234", clean)
        self.assertIn("[REDACTED_TOKEN]", clean)


if __name__ == "__main__":
    unittest.main()

