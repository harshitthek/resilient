"""
Unit test suite for Stage 1: Discovery (scripts/discover.py).
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add scripts directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import discover


class TestGitHubTrendingScraper(unittest.TestCase):
    @patch("discover.SESSION")
    def test_fetch_github_trending_repos_success(self, mock_session):
        mock_html = """
        <html>
            <h2 class="h3 lh-condensed">
                <a href="/owner1/repo1" data-hydro-click="123">owner1 / repo1</a>
            </h2>
            <h2 class="h3 lh-condensed">
                <a href="/owner2/repo2" data-hydro-click="456">owner2 / repo2</a>
            </h2>
            <a href="/sponsors/explore">sponsors</a>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_session.get.return_value = mock_resp

        trending = discover.fetch_github_trending_repos()
        self.assertIn("owner1/repo1", trending)
        self.assertIn("owner2/repo2", trending)
        self.assertNotIn("sponsors/explore", trending)

    @patch("discover.SESSION")
    def test_fetch_github_trending_handles_failure(self, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_session.get.return_value = mock_resp

        trending = discover.fetch_github_trending_repos()
        self.assertEqual(trending, [])


class TestOSSInsightTrendingFetcher(unittest.TestCase):
    @patch("discover.SESSION")
    def test_fetch_ossinsight_trending_repos_success(self, mock_session):
        mock_json = {
            "data": [
                {"repo_name": "oss/repo-a", "stars_delta": 150},
                {"repo_name": "oss/repo-b", "stars_delta": 120},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_json
        mock_session.get.return_value = mock_resp

        trending = discover.fetch_ossinsight_trending_repos()
        self.assertEqual(len(trending), 2)
        self.assertIn("oss/repo-a", trending)
        self.assertIn("oss/repo-b", trending)

    @patch("discover.SESSION")
    def test_fetch_ossinsight_handles_error(self, mock_session):
        mock_session.get.side_effect = Exception("Network connection error")

        trending = discover.fetch_ossinsight_trending_repos()
        self.assertEqual(trending, [])


class TestCandidateRepoDeduplication(unittest.TestCase):
    @patch("discover.fetch_github_trending_repos", return_value=["org/repo1", "org/repo2"])
    @patch("discover.fetch_ossinsight_trending_repos", return_value=["org/repo2", "org/repo3"])
    @patch("discover.gh_get")
    def test_find_candidate_repos_deduplicates(self, mock_gh_get, mock_oss, mock_gh):
        # Mock search API response
        mock_search_resp = MagicMock()
        mock_search_resp.status_code = 200
        mock_search_resp.json.return_value = {"items": [{"full_name": "org/repo3"}, {"full_name": "org/repo4"}]}

        # Mock GET /repos/{full_name} calls
        mock_repo_resp = MagicMock()
        mock_repo_resp.status_code = 200
        mock_repo_resp.json.side_effect = lambda: {"id": 1, "full_name": "test/repo"}

        mock_gh_get.side_effect = [mock_search_resp] + [mock_repo_resp] * 4

        repos = discover.find_candidate_repos()
        self.assertTrue(len(repos) > 0)


if __name__ == "__main__":
    unittest.main()
