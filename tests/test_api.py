"""
Unit test suite for Stage 5: FastAPI REST API (api/main.py).
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# Add workspace directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.main import app

client = TestClient(app)


class TestLeaderboardAPI(unittest.TestCase):
    def test_health_check_endpoint(self):
        response = client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("database", data)

    def test_get_leaderboard_fallback(self):
        response = client.get("/api/v1/leaderboard")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) >= 1)
        self.assertIn("agent_name", data[0])
        self.assertIn("pass_rate", data[0])
        self.assertIn("merge_rate", data[0])

    def test_get_models_comparison(self):
        response = client.get("/api/v1/models/compare")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("models", data)
        self.assertIn("metrics_evaluated", data)

    def test_get_repositories(self):
        response = client.get("/api/v1/repos")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) >= 1)
        self.assertIn("full_name", data[0])
        self.assertIn("allows_ai_prs", data[0])

    def test_get_runs(self):
        response = client.get("/api/v1/runs")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) >= 1)
        self.assertIn("agent_name", data[0])

    def test_get_run_diff(self):
        response = client.get("/api/v1/runs/1/diff")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["run_id"], 1)
        self.assertIn("diff_text", data)
        self.assertIn("files_changed", data)

    def test_get_activity_feed(self):
        response = client.get("/api/v1/feed")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) >= 1)
        self.assertIn("type", data[0])


if __name__ == "__main__":
    unittest.main()
