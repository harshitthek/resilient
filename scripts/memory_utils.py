"""
Autonomous Memory Bank & Coordination System for Resilient AI Coding Agents.

Provides hierarchical memory storage (Global & Repo-Specific) to allow agents
to learn across runs, share engineering heuristics, and coordinate fixes.
"""

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

# Shared fallback memory when running offline / without DB
DEFAULT_GLOBAL_MEMORIES = [
    "Always check for None/null/undefined boundaries before dereferencing nested properties.",
    "Edit ONLY target lines to preserve diff minimality and avoid cosmetic whitespace churn.",
    "Prioritize inspecting repository documentation (AGENTS.md, CONTRIBUTING.md, README.md) before making edits.",
    "Ensure syntax validity using static AST compilation check compile(..., 'exec') before committing.",
    "Preserve host repository code style, docstrings, and type annotations."
]


def fetch_agent_memories(conn, repo_id: Optional[int] = None) -> Dict[str, List[str]]:
    """Fetch global and repo-specific memories from PostgreSQL.

    Returns:
        {"global": [str], "repo": [str]}
    """
    memories = {"global": list(DEFAULT_GLOBAL_MEMORIES), "repo": []}

    if conn is None:
        return memories

    try:
        with conn.cursor() as cur:
            # Fetch global memories
            cur.execute("""
                SELECT content FROM agent_memories
                WHERE scope = 'global'
                ORDER BY confidence DESC, id DESC
                LIMIT 10
            """)
            global_rows = cur.fetchall()
            if global_rows:
                memories["global"] = [r["content"] if isinstance(r, dict) else r[0] for r in global_rows]

            # Fetch repo-specific memories
            if repo_id:
                cur.execute("""
                    SELECT content FROM agent_memories
                    WHERE scope = 'repository' AND repo_id = %s
                    ORDER BY confidence DESC, id DESC
                    LIMIT 10
                """, (repo_id,))
                repo_rows = cur.fetchall()
                if repo_rows:
                    memories["repo"] = [r["content"] if isinstance(r, dict) else r[0] for r in repo_rows]
    except Exception as exc:
        print(f"Warning fetching agent memories from DB: {exc}", file=sys.stderr)

    return memories


def format_memory_prompt(memories: Dict[str, List[str]]) -> str:
    """Format global and repository memories into a clean markdown prompt block for agent system prompts."""
    global_list = memories.get("global", [])
    repo_list = memories.get("repo", [])

    lines = ["=== AUTONOMOUS MEMORY BANK & LEARNINGS ==="]

    if global_list:
        lines.append("🌐 GLOBAL PIPELINE HEURISTICS (Learned across all repositories):")
        for g in global_list:
            lines.append(f"  - {g}")

    if repo_list:
        lines.append("\n📁 REPOSITORY-SPECIFIC MEMORY & CONVENTIONS (Learned from past runs on this repo):")
        for r in repo_list:
            lines.append(f"  - {r}")

    lines.append("\nApply these learned lessons strictly to prevent recurring bugs and maintain consistency.")
    return "\n".join(lines)


def record_memory(conn, scope: str, memory_type: str, content: str,
                  repo_id: Optional[int] = None, run_id: Optional[int] = None) -> bool:
    """Record a new learned heuristic into PostgreSQL memory bank."""
    if conn is None or not content.strip():
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO agent_memories (scope, repo_id, memory_type, content, source_run_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (scope, repo_id, memory_type, content.strip(), run_id))
            conn.commit()
            return True
    except Exception as exc:
        print(f"Warning recording memory: {exc}", file=sys.stderr)
        return False


def synthesize_post_mortem_learning(conn, run_id: int, issue_title: str, diff_text: str,
                                     tests_passed: Optional[bool], reviewer_notes: Dict,
                                     repo_id: Optional[int] = None) -> List[str]:
    """Synthesize post-mortem learnings from an evaluated run and record into memory."""
    new_learnings = []

    # If run passed with high score, record positive pattern
    if tests_passed is True:
        lesson = f"Successful fix pattern for '{issue_title[:50]}': Minimal diff verified with 100% test pass rate."
        new_learnings.append(lesson)
        if repo_id:
            record_memory(conn, scope="repository", memory_type="pattern", content=lesson, repo_id=repo_id, run_id=run_id)

    # Extract maintainer review findings
    findings = reviewer_notes.get("findings", []) if isinstance(reviewer_notes, dict) else []
    for f in findings:
        if "Warning" in f or "churn" in f.lower():
            pitfall_lesson = f"Avoid pitfall on repo #{repo_id}: {f}"
            new_learnings.append(pitfall_lesson)
            if repo_id:
                record_memory(conn, scope="repository", memory_type="pitfall", content=pitfall_lesson, repo_id=repo_id, run_id=run_id)

    return new_learnings
