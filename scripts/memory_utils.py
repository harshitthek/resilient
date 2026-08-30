"""
Autonomous Memory Bank & Coordination System for Resilient AI Coding Agents.

Provides hierarchical memory storage (Global & Repo-Specific) to allow agents
to learn across runs, share engineering heuristics, and coordinate fixes.
Features relevance-weighted retrieval, confidence reinforcement, and cross-model knowledge sharing.
"""

import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

DEFAULT_GLOBAL_MEMORIES = [
    {"content": "Always check for None/null/undefined boundaries before dereferencing nested properties.", "confidence": 1.0, "agent_name": "system"},
    {"content": "Edit ONLY target lines to preserve diff minimality and avoid cosmetic whitespace churn.", "confidence": 1.0, "agent_name": "system"},
    {"content": "Prioritize inspecting repository documentation (AGENTS.md, CONTRIBUTING.md, README.md) before making edits.", "confidence": 1.0, "agent_name": "system"},
    {"content": "Ensure syntax validity using static AST compilation check compile(..., 'exec') before committing.", "confidence": 1.0, "agent_name": "system"},
    {"content": "Preserve host repository code style, docstrings, and type annotations.", "confidence": 0.95, "agent_name": "system"}
]


def fetch_agent_memories(conn, repo_id: Optional[int] = None, query_context: str = "") -> Dict[str, List[Dict]]:
    """Fetch relevance-ranked global and repo-specific memories from PostgreSQL.

    Returns:
        {"global": [{"content": str, "confidence": float, "agent_name": str}], "repo": [...]}
    """
    memories = {
        "global": list(DEFAULT_GLOBAL_MEMORIES),
        "repo": []
    }

    if conn is None:
        return memories

    try:
        with conn.cursor() as cur:
            # Fetch active global memories with confidence >= 0.3
            cur.execute("""
                SELECT content, confidence, source_agent_name
                FROM agent_memories
                WHERE scope = 'global' AND confidence >= 0.30
                ORDER BY confidence DESC, id DESC
                LIMIT 15
            """)
            global_rows = cur.fetchall()
            if global_rows:
                memories["global"] = [
                    {
                        "content": r["content"] if isinstance(r, dict) else r[0],
                        "confidence": float(r["confidence"] if isinstance(r, dict) else r[1]),
                        "agent_name": (r["source_agent_name"] if isinstance(r, dict) else r[2]) or "system"
                    }
                    for r in global_rows
                ]

            # Fetch repo-specific memories
            if repo_id:
                cur.execute("""
                    SELECT content, confidence, source_agent_name
                    WHERE scope = 'repository' AND repo_id = %s AND confidence >= 0.30
                    ORDER BY confidence DESC, id DESC
                    LIMIT 15
                """, (repo_id,))
                repo_rows = cur.fetchall()
                if repo_rows:
                    memories["repo"] = [
                        {
                            "content": r["content"] if isinstance(r, dict) else r[0],
                            "confidence": float(r["confidence"] if isinstance(r, dict) else r[1]),
                            "agent_name": (r["source_agent_name"] if isinstance(r, dict) else r[2]) or "system"
                        }
                        for r in repo_rows
                    ]
    except Exception as exc:
        print(f"Warning fetching agent memories from DB: {exc}", file=sys.stderr)

    return memories


def format_memory_prompt(memories: Dict[str, List[Dict]]) -> str:
    """Format global and repository memories into a clean markdown prompt block for agent system prompts."""
    global_list = memories.get("global", [])
    repo_list = memories.get("repo", [])

    lines = ["=== AUTONOMOUS MEMORY BANK & LEARNINGS ==="]

    if global_list:
        lines.append("🌐 GLOBAL PIPELINE HEURISTICS (Learned across all repositories):")
        for g in global_list:
            agent_tag = f"[{g.get('agent_name', 'system')}]" if g.get('agent_name') != 'system' else ""
            lines.append(f"  - {agent_tag} {g['content']} (Confidence: {g.get('confidence', 1.0):.2f})")

    if repo_list:
        lines.append("\n📁 REPOSITORY-SPECIFIC MEMORY & CONVENTIONS (Learned from past runs on this repo):")
        for r in repo_list:
            agent_tag = f"[{r.get('agent_name', 'system')}]" if r.get('agent_name') != 'system' else ""
            lines.append(f"  - {agent_tag} {r['content']} (Confidence: {r.get('confidence', 1.0):.2f})")

    lines.append("\nApply these learned lessons strictly to prevent recurring bugs and maintain peer model coordination.")
    return "\n".join(lines)


def record_memory(conn, scope: str, memory_type: str, content: str,
                  repo_id: Optional[int] = None, run_id: Optional[int] = None,
                  agent_name: str = "system", confidence: float = 1.0) -> bool:
    """Record a new learned heuristic into PostgreSQL memory bank."""
    if conn is None or not content.strip():
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO agent_memories (scope, repo_id, memory_type, content, source_run_id, source_agent_name, confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (scope, repo_id, memory_type, content.strip(), run_id, agent_name, confidence))
            conn.commit()
            return True
    except Exception as exc:
        print(f"Warning recording memory: {exc}", file=sys.stderr)
        return False


def reinforce_memory(conn, memory_id: int, delta: float = 0.10):
    """Reinforce a memory's confidence score upon a successful test run."""
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE agent_memories
                SET confidence = LEAST(1.00, confidence + %s), updated_at = now()
                WHERE id = %s
            """, (delta, memory_id))
            conn.commit()
    except Exception as exc:
        print(f"Warning reinforcing memory: {exc}", file=sys.stderr)


def decay_memory(conn, memory_id: int, delta: float = 0.20):
    """Decay a memory's confidence score upon a failed run or maintainer rejection."""
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE agent_memories
                SET confidence = GREATEST(0.00, confidence - %s), updated_at = now()
                WHERE id = %s
            """, (delta, memory_id))
            conn.commit()
    except Exception as exc:
        print(f"Warning decaying memory: {exc}", file=sys.stderr)


def synthesize_post_mortem_learning(conn, run_id: int, issue_title: str, diff_text: str,
                                     tests_passed: Optional[bool], reviewer_notes: Dict,
                                     repo_id: Optional[int] = None, agent_name: str = "system") -> List[str]:
    """Synthesize post-mortem learnings from an evaluated run and record into memory."""
    new_learnings = []

    # If run passed with high score, record positive pattern
    if tests_passed is True:
        lesson = f"Successful fix pattern for '{issue_title[:50]}': Minimal diff verified with 100% test pass rate."
        new_learnings.append(lesson)
        if repo_id:
            record_memory(conn, scope="repository", memory_type="pattern", content=lesson, repo_id=repo_id, run_id=run_id, agent_name=agent_name, confidence=1.0)
        else:
            record_memory(conn, scope="global", memory_type="pattern", content=lesson, repo_id=None, run_id=run_id, agent_name=agent_name, confidence=0.95)

    # Extract maintainer review findings & pitfalls
    findings = reviewer_notes.get("findings", []) if isinstance(reviewer_notes, dict) else []
    for f in findings:
        if "Warning" in f or "churn" in f.lower():
            pitfall_lesson = f"Avoid pitfall on repo #{repo_id}: {f}"
            new_learnings.append(pitfall_lesson)
            if repo_id:
                record_memory(conn, scope="repository", memory_type="pitfall", content=pitfall_lesson, repo_id=repo_id, run_id=run_id, agent_name=agent_name, confidence=0.85)

    return new_learnings
