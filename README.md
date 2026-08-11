<div align="center">

# 🚀 RESILIENT
### *Empirical Open-Source AI Coding Agent Leaderboard & Autonomous Remediation Pipeline*

[![GitHub Actions Status](https://img.shields.io/github/actions/workflow/status/harshitthek/resilient/leaderboard.yml?branch=main&style=for-the-badge&logo=github&label=PIPELINE%20CI)](https://github.com/harshitthek/resilient/actions)
[![Pytest Suite](https://img.shields.io/badge/TESTS-47%20PASSED%20(100%25)-10b981?style=for-the-badge&logo=pytest)](https://github.com/harshitthek/resilient)
[![Python Version](https://img.shields.io/badge/PYTHON-3.11%2B-06b6d4?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FASTAPI-v1.1.0-059669?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![Three.js](https://img.shields.io/badge/THREE.JS-3D%20DASHBOARD-818cf8?style=for-the-badge&logo=threedotjs)](http://localhost:8000)

<p align="center">
  <b>Resilient</b> is an enterprise-grade autonomous pipeline and empirical benchmarking platform that continuously scans GitHub, dispatches AI coding agents in isolated branch sandboxes, executes local test suites, assesses diff quality, submits authenticated pull requests upstream, and benchmarks performance live on a 3D Web Dashboard.
</p>

[🌐 Web Dashboard](#-interactive-3d-web-dashboard) • [ARCHITECTURE](#-end-to-end-pipeline-architecture) • [SETUP GUIDE](#%EF%B8%8F-quick-start) • [SECURITY](#-security--policy-enforcement)

</div>

---

## 📊 Interactive 3D Web Dashboard

Resilient features a **Next.js/React & Three.js 3D Web Dashboard** served live by a **FastAPI REST API Backend**:

- 🌌 **Ambient 3D Particle Starfield & Soothing Video Canvas**: Non-intrusive ambient background with smooth mouse parallax.
- 🧪 **Side-by-Side Model Comparison Matrix**: Chart.js radar graph measuring Pass Rate, Merge Rate, Quality Score, Speed, and Reliability.
- ⚡ **Live Interactive Pipeline Control Panel**: Trigger Stage 1 (Discovery), Stage 2 (Dispatch), Stage 3 (Evaluate), and Stage 4 (Submit) with real-time console feedback.
- 🏷️ **Language Filter Tabs**: Filter benchmark metrics across Python, TypeScript, Rust, and Go.
- 🔍 **Code Fix Patch & Error Log Inspector**: 1-click **Copy to Clipboard** inspector for full git diff patches and error tracebacks.

```
+-----------------------------------------------------------------------------------+
|  RESILIENT | AI Agent Open-Source Benchmark          [● Live Pipeline]  [GitHub]  |
|                                                                                   |
|  [30 Tracked Repos]   [139 Candidate Issues]   [7 Dispatched Fixes]   [2 PRs]    |
|                                                                                   |
|  [AI Agent Leaderboard]                      [Model Comparison Matrix]            |
|  #1 gemini-2.5-flash | 71.4% Pass | 50% Merge     +--- Radar Chart ---+         |
|  #2 jules            | 45.0% Pass | 20% Merge     |   Pass / Merge    |         |
|                                                   +-------------------+         |
|  [Live Pipeline Control]                                                          |
|  [Trigger Discovery] [Trigger Dispatch] [Trigger Evaluate] [Trigger Submit]       |
+-----------------------------------------------------------------------------------+
```

---

## 🏗️ End-to-End Pipeline Architecture

```mermaid
flowchart TD
    subgraph STAGE_1 ["Stage 1: Discovery"]
        A[GitHub Trending & OSSInsight API] -->|Scan Repos| B[(PostgreSQL DB)]
        C[Webhook Receiver HMAC] -->|Push Issues| B
        B --> D{Scan CONTRIBUTING.md}
        D -->|Disallowed| E[Deactivate Repo]
        D -->|Allowed| F[Store Candidate Issues]
    end

    subgraph STAGE_2 ["Stage 2: Dispatch"]
        F --> G[Dispatch Orchestrator]
        G -->|Isolated Fork Branch| H[Gemini 2.5 Agent Sandbox]
        H -->|Generate Patch| I[Store Branch Diff]
    end

    subgraph STAGE_3 ["Stage 3: Evaluation"]
        I --> J[Auto-Detect Test Framework]
        J -->|pytest / npm / cargo / go| K[Execute Test Suite]
        K --> L[Compute Composite Quality Score]
        L --> M[Sanitize Secrets & Tokens]
    end

    subgraph STAGE_4 ["Stage 4: Submission"]
        M --> N[Enforce 24h Rolling Rate Caps]
        N --> O[GitHub App RS256 Auth]
        O --> P[Submit Authenticated PR Upstream]
    end

    subgraph STAGE_5 ["Stage 5: Leaderboard"]
        P --> Q[FastAPI REST API Backend]
        Q --> R[3D Web Dashboard & Visual Matrix]
    end
```

---

## 🚦 Master Pipeline Status

| Stage | Implementation Component | Operational Status | Verification Method |
|---|---|---|---|
| **Stage 1: Discovery** | `scripts/discover.py`, `webhook_receiver.py` | ✅ **100% Live & Verified** | GitHub Actions (`discover.yml`, 47 repos tracked) |
| **Stage 2: Dispatch** | `scripts/dispatch.py`, `agents/gemini_agent.py` | ✅ **100% Live & Verified** | Isolated fork branches (`resilient/{issue}/gemini`) |
| **Stage 3: Evaluation** | `scripts/evaluate.py` | ✅ **100% Live & Verified** | Local test runners (`pytest`, `npm`, `cargo`, `go`) |
| **Stage 4: Submission** | `scripts/submit.py`, `scripts/github_utils.py` | ✅ **100% Live & Verified** | `resilient-bot` GitHub App (JWT RS256 Auth) |
| **Stage 5: Leaderboard** | `api/main.py`, `web/` | ✅ **100% Live & Verified** | FastAPI REST API + 3D Web UI (**47/47 Tests Passed**) |

---

## ⚙️ Quick Start

### 1. Prerequisites & Environment Setup
Clone the repository and install the dependencies:
```bash
git clone https.github.com/harshitthek/resilient.git
cd resilient
pip install -r scripts/requirements.txt -r requirements-webhook.txt -r scripts/requirements-dispatch.txt
```

Create a `.env` configuration file based on `.env.example`:
```ini
DATABASE_URL=postgres://user:password@localhost:5432/resilient
DISCOVERY_GH_TOKEN=ghp_your_discovery_token
DISPATCH_GH_TOKEN=ghp_your_dispatch_token
GEMINI_API_KEY=your_gemini_api_key
GH_APP_ID=123456
GH_APP_INSTALLATION_ID=789012
GH_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
```

### 2. Launch the Web Dashboard & REST API
Run the unified FastAPI server:
```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser to interact with the 3D Leaderboard Dashboard and REST API!

### 3. Run the Unit Test Suite
Execute the full automated test suite:
```bash
pytest -v
```

---

## 🛡️ Security & Policy Enforcement

Resilient is engineered with explicit safeguards to respect open-source maintainers and secure agent sandboxes:

- **AI Policy Scans**: Automatically inspects `CONTRIBUTING.md` and repository templates. Repositories with explicit AI prohibitions are deactivated immediately (`is_active = FALSE`).
- **Fork Sandbox Isolation**: Agents execute code exclusively inside isolated personal fork branches (`resilient/{issue}/{model}`). Agents are never given upstream write targets.
- **24-Hour Rolling Rate Caps**: Enforces strict submission caps (max 10 global PRs / max 2 per repo per 24 hours).
- **Secret Redaction**: `sanitize_token()` automatically redacts PATs, JWT RS256 tokens, and environment secrets from diff patches and log tracebacks.
- **AI Disclosure Notice**: Every pull request includes an explicit mandatory notice: `> [!NOTE] Generated by Resilient AI Coding Agent`.

---

## 📂 Repository File Index

```
resilient/
├── api/
│   └── main.py              # FastAPI REST API Server & Web UI static mount
├── web/
│   ├── index.html           # 3D Dashboard HTML5 layout with SVG vector icons
│   ├── style.css            # Ultra-transparent glassmorphism CSS theme
│   ├── app.js               # Three.js background, Chart.js radar & REST API client
│   └── favicon.svg          # Glowing cyan vector favicon
├── scripts/
│   ├── discover.py          # Stage 1: GitHub Trending & OSSInsight scraper
│   ├── dispatch.py          # Stage 2: Agent dispatch & fork branch orchestrator
│   ├── evaluate.py          # Stage 3: Test runner execution & quality scoring
│   ├── submit.py            # Stage 4: GitHub App authenticated PR submission
│   └── github_utils.py      # Shared GitHub API & RS256 JWT auth utilities
├── agents/
│   ├── base.py              # Abstract Agent interface & dataclasses
│   ├── gemini_agent.py      # Gemini 2.5 Flash function-calling agent
│   └── jules_adapter.py     # Jules API integration
├── tests/                   # 47 Passing unit tests (test_api, test_discovery, etc.)
├── schema.sql               # PostgreSQL schema definition
└── webhook_receiver.py      # HMAC-authenticated real-time issue receiver
```

---

<div align="center">
  <sub>Built with ❤️ by the Resilient Engineering Team. Licensed under the MIT License.</sub>
</div>
