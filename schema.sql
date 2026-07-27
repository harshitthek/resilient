-- Core data model for the repo-scanning / multi-agent PR pipeline.
-- Postgres syntax (works fine on a small instance -- this schema is
-- lightweight since the heavy compute happens on the agents' own
-- infrastructure, not here).

CREATE TABLE repos (
    id                SERIAL PRIMARY KEY,
    github_id         BIGINT UNIQUE NOT NULL,
    full_name         TEXT UNIQUE NOT NULL,      -- "owner/repo"
    default_branch    TEXT NOT NULL DEFAULT 'main',
    language          TEXT,
    stars             INTEGER NOT NULL DEFAULT 0,
    stars_prev        INTEGER,                   -- snapshot from previous scan
    stars_checked_at  TIMESTAMPTZ,
    is_archived       BOOLEAN NOT NULL DEFAULT FALSE,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,  -- false = stopped tracking
                                                        -- (opted out / deleted / policy disallows AI PRs)
    fork_full_name    TEXT,                      -- our fork, once created
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scanned_at   TIMESTAMPTZ
);

-- Cached read of whether a repo's own docs allow AI-assisted contributions.
-- Checked once per repo (re-checked periodically) so we don't re-fetch
-- CONTRIBUTING.md on every issue.
CREATE TABLE repo_policies (
    repo_id           INTEGER PRIMARY KEY REFERENCES repos(id) ON DELETE CASCADE,
    allows_ai_prs     TEXT NOT NULL DEFAULT 'unknown', -- 'allowed' | 'disallowed' | 'unknown'
    source_file       TEXT,        -- CONTRIBUTING.md, PULL_REQUEST_TEMPLATE.md, etc.
    matched_snippet   TEXT,
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE issues (
    id                    SERIAL PRIMARY KEY,
    repo_id               INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    github_issue_number   INTEGER NOT NULL,
    title                 TEXT NOT NULL,
    labels                TEXT[],
    has_linked_pr         BOOLEAN NOT NULL DEFAULT FALSE, -- someone's already on it
    status                TEXT NOT NULL DEFAULT 'discovered',
        -- Coarse pipeline stage. Individual run state is in the runs table.
        -- Readiness for submission is derived from runs + evaluations, not
        -- from this column.
        --
        -- discovered → dispatched → submitted
        --      ↘            ↘
        --    skipped       skipped
    discovered_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repo_id, github_issue_number)
);

-- One attempt: a specific issue handed to a specific agent.
CREATE TABLE runs (
    id            SERIAL PRIMARY KEY,
    issue_id      INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    agent_name    TEXT NOT NULL,     -- 'jules' | 'gemini-2.5-pro' | 'gemini-2.5-flash'
    branch_name   TEXT,              -- branch on OUR fork, never upstream directly
    status        TEXT NOT NULL,     -- pending | running | success | failed | timeout
                                    -- No DEFAULT: dispatch code must set explicitly per agent type.
                                    -- pending = async agent dispatched (Jules).
                                    -- running = sync agent executing (Gemini).
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    diff_url      TEXT,
    session_id    TEXT               -- external task ID for async agents (e.g. Jules session ID);
                                    -- NULL for sync agents (Gemini)
);

CREATE TABLE evaluations (
    id               SERIAL PRIMARY KEY,
    run_id           INTEGER NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE,
                     -- UNIQUE: exactly one evaluation per run. The existence of the row
                     -- means "we tried to evaluate this." Its absence means "evaluation
                     -- hasn't run yet."
    tests_passed     BOOLEAN,
    test_summary     TEXT,
    reviewer_score   NUMERIC(5,2),
    reviewer_notes   JSONB,
    composite_score  NUMERIC(5,2),   -- weighted combo used for ranking / leaderboard
    evaluated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pr_submissions (
    id                 SERIAL PRIMARY KEY,
    issue_id           INTEGER NOT NULL UNIQUE REFERENCES issues(id) ON DELETE CASCADE,
                       -- UNIQUE: exactly one PR submission per issue, ever.
    winning_run_id     INTEGER NOT NULL REFERENCES runs(id),
    pr_url             TEXT,
    disclosure_text    TEXT NOT NULL,   -- required: how we disclose AI involvement
    submitted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    maintainer_status  TEXT NOT NULL DEFAULT 'pending' -- pending | merged | closed | rejected
);

CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_runs_issue ON runs(issue_id);
CREATE INDEX idx_runs_status ON runs(status);       -- Mode 1: poll pending/running runs
CREATE INDEX idx_evaluations_run ON evaluations(run_id);
