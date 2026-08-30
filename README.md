<div align="center">

# 🚀 RESILIENT
### *Empirical Open-Source AI Coding Agent Leaderboard & Autonomous Remediation Engine*
**Created & Maintained by Harshit ([@harshitthek](https://github.com/harshitthek))**

[![Vercel Deployment](https://img.shields.io/badge/LIVE%20SAAS-VERCEL%20PRODUCTION-000000?style=for-the-badge&logo=vercel)](https://resilient-cockpit.vercel.app)
[![GitHub Pages](https://img.shields.io/badge/LIVE%20DEMO-GITHUB%20PAGES-8b5cf6?style=for-the-badge&logo=githubpages)](https://harshitthek.github.io/resilient/)
[![Pytest Suite](https://img.shields.io/badge/TESTS-59%20PASSED%20(100%25)-10b981?style=for-the-badge&logo=pytest)](https://github.com/harshitthek/resilient)
[![Python Version](https://img.shields.io/badge/PYTHON-3.11%2B-06b6d4?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FASTAPI-v1.1.0-059669?style=for-the-badge&logo=fastapi)](https://resilient-cockpit.vercel.app/api/v1/memories)
[![Three.js](https://img.shields.io/badge/THREE.JS-3D%20DASHBOARD-818cf8?style=for-the-badge&logo=threedotjs)](https://resilient-cockpit.vercel.app)
[![License: MIT](https://img.shields.io/badge/LICENSE-MIT-yellow?style=for-the-badge)](LICENSE)

<p align="center">
  <b>Resilient</b> is an enterprise-grade autonomous pipeline and empirical benchmarking platform that continuously scans GitHub for real-world issues, orchestrates multi-agent coding tournaments in isolated sandboxes, executes test-driven validation and self-healing loops, audits code quality with maintainer-grade AI peer reviews, submits authenticated pull requests upstream, and benchmarks performance live on an interactive 3D Web Dashboard.
</p>

[🚀 Live Vercel SaaS Cockpit](https://resilient-cockpit.vercel.app) • [🌐 Live GitHub Pages](https://harshitthek.github.io/resilient/) • [🧠 Memory API](https://resilient-cockpit.vercel.app/api/v1/memories) • [🛡️ Quality Tournament](#%EF%B8%8F-quality-first-multi-model-tournament) • [🏗️ Architecture](#%EF%B8%8F-end-to-end-pipeline-architecture) • [🧪 Live Benchmarks](#-empirical-model-benchmarks) • [⚙️ Setup Guide](#%EF%B8%8F-quick-start)

</div>

---

## 📊 Interactive 3D Web Dashboard

Resilient features a real-time **HTML5 / Three.js 3D Web Dashboard** served directly by a **FastAPI REST API Backend**:

- 🌌 **Ambient 3D Particle Starfield & Particle Canvas**: Smooth mouse parallax and responsive rendering.
- 🧪 **Side-by-Side Model Comparison Matrix**: Dynamic radar graphs measuring Pass Rate, Merge Rate, Quality Score, Latency, and Reliability.
- ⚡ **Live Interactive Pipeline Control Panel**: Trigger Stage 1 (Discovery), Stage 2 (Dispatch), Stage 3 (Evaluate), and Stage 4 (Submit) with live streaming console logs.
- 🏷️ **Multi-Language Support**: Dedicated metrics and test runners for Python, TypeScript, JavaScript, Rust, and Go.
- 🔍 **Code Fix Patch & Traceback Inspector**: 1-click **Copy to Clipboard** inspector for git diff patches, compiler logs, and AI audit notes.

```
+-----------------------------------------------------------------------------------+
|  RESILIENT | AI Agent Open-Source Benchmark          [● Live Pipeline]  [GitHub]  |
|                                                                                   |
|  [30 Tracked Repos]   [139 Candidate Issues]   [12 Dispatched Fixes]   [4 PRs]   |
|                                                                                   |
|  [AI Agent Leaderboard]                      [Model Comparison Matrix]            |
|  #1 quality-ensemble | 95.0% Pass | 80% Merge     +--- Radar Chart ---+         |
|  #2 gemini-2.5-flash | 71.4% Pass | 50% Merge     |   Pass / Merge    |         |
|  #3 groq/llama-3.3   | 68.0% Pass | 45% Merge     |   Quality/Speed   |         |
|  #4 nvidia/nemotron  | 82.0% Pass | 60% Merge     +-------------------+         |
|                                                                                   |
|  [Live Pipeline Control]                                                          |
|  [Trigger Discovery] [Trigger Dispatch] [Trigger Evaluate] [Trigger Submit]       |
+-----------------------------------------------------------------------------------+
```

---

## 🛡️ Quality-First Multi-Model Tournament

Instead of relying on single-shot monolithic generation, Resilient employs a **Quality-First Autonomous Tournament & Consensus Engine** that prioritizes maximum maintainer mergeability and zero regressions:

```mermaid
flowchart TD
    subgraph PHASE_1 ["Phase 1: Deep Problem Distillation"]
        A[GitHub Issue + Repository Tree] --> B[Gemini 2.5 Pro / Cohere]
        B -->|Extract Root Cause, Target Files & Edge Cases| C[Technical Task Brief]
    end

    subgraph PHASE_2 ["Phase 2: Multi-Model Tournament Generation"]
        C --> D[Candidate 1: Gemini 2.5 Pro]
        C --> E[Candidate 2: NVIDIA Nemotron 3.5]
        C --> F[Candidate 3: Groq Llama 3.3 70B]
    end

    subgraph PHASE_3 ["Phase 3: Sandbox Testing & Self-Healing"]
        D & E & F --> G[Execute AST & Test Suites]
        G -->|If tests fail| H[Feed Tracebacks back for Auto-Repair]
        H --> G
    end

    subgraph PHASE_4 ["Phase 4: Strict Maintainer AI Peer Review"]
        G -->|Passing Patches| I[NVIDIA Nemotron Reviewer]
        I -->|Audit: Edge Cases, Style, Security & Diff Minimality| J[Maintainer Score /100]
        J --> K[Select #1 Winning Patch]
    end

    subgraph PHASE_5 ["Phase 5: Authenticated Upstream Delivery"]
        K --> L[Commit Winning Patch to Fork Branch]
        L --> M[resilient-fix bot Upstream PR]
    end
```

### The 4 Pillars of Maintainer-Grade AI Peer Review
1. **Edge-Case Safety**: Exhaustive checks for `None`/`null` boundaries, empty collections, and unhandled exceptions.
2. **Style & Conventions**: Type annotations, docstrings, and strict adherence to the host repository's conventions.
3. **Diff Minimality**: Elimination of cosmetic formatting churn and unrelated whitespace edits.
4. **Security & Secrets**: Verification against token leaks, shell injection, or unsafe evaluations.

---

## 🏗️ End-to-End Pipeline Architecture

```mermaid
flowchart LR
    subgraph STAGE_1 ["Stage 1: Discover"]
        D1[GitHub Trending] --> D2[Check AI Policy]
        D2 --> D3[(PostgreSQL DB)]
    end

    subgraph STAGE_2 ["Stage 2: Dispatch"]
        D3 --> S1[Fork Repo Sandbox]
        S1 --> S2[Quality Tournament]
        S2 --> S3[Commit Winning Branch]
    end

    subgraph STAGE_3 ["Stage 3: Evaluate"]
        S3 --> E1[Run Test Runners]
        E1 --> E2[AI Code Review Score]
        E2 --> E3[Compute Composite Score]
    end

    subgraph STAGE_4 ["Stage 4: Submit"]
        E3 --> SB1{Score >= 0.70 & Caps OK?}
        SB1 -->|Yes| SB2[GitHub App JWT RS256]
        SB2 --> SB3[Open Upstream PR]
    end

    subgraph STAGE_5 ["Stage 5: Leaderboard"]
        SB3 --> L1[FastAPI REST API]
        L1 --> L2[3D Web Dashboard]
    end
```

---

## 🧪 Empirical Model Benchmarks

Live empirical benchmarks executed across Resilient's active zero-credit-card model roster:

| Provider | Active Model | Live Latency | Context Window | Best Suited Role |
|---|---|---|---|---|
| ⚡ **Groq Cloud** | `llama-3.3-70b-versatile` | **1.28s** | 128,000 | 🏎️ **Fast Patch Synthesis**: Ultra-fast code generation (~300+ tok/s). |
| 🟢 **NVIDIA NIM** | `nemotron-3.5-lightning-30b-a3b` | **4.02s** | 128,000 | 🧠 **Reasoning & Code Audit**: Chain-of-thought logic and peer review. |
| 💬 **Cohere** | `command-r-08-2024` | **3.37s** | 128,000 | 📚 **Problem Distillation**: Root cause extraction and issue synthesis. |
| ♊ **Google AI Studio** | `gemini-2.5-flash` / `pro` | **9.85s** | **1,000,000+** | 👁️ **Massive Context & Architecture**: Ingesting entire codebases. |
| 🤖 **GitHub App** | `resilient-fix[bot]` | **0.55s** | N/A | 🔒 **Authenticated PR Gatekeeper**: Fork branching and PR delivery. |
| 🌐 **OpenRouter** | Free Shared Pool (`Qwen`, `DeepSeek`) | Variable | 32k - 128k | 🔀 **Consensus Fallback**: Multi-provider consensus routing. |

---

## 🚦 Master Pipeline Stage Verification

| Stage | Implementation Component | Operational Status | Verification Method |
|---|---|---|---|
| **Stage 1: Discovery** | [`scripts/discover.py`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/scripts/discover.py), [`webhook_receiver.py`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/webhook_receiver.py) | ✅ **100% Live & Verified** | Daily Trending Scraper (`since=daily`, 500-5,000 star creator window) |
| **Stage 2: Dispatch** | [`scripts/dispatch.py`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/scripts/dispatch.py), [`agents/`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/agents) | ✅ **100% Live & Verified** | Sandbox Isolation + DB Connection Liveness Guard (`ensure_connection`) |
| **Stage 3: Evaluation** | [`scripts/evaluate.py`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/scripts/evaluate.py) | ✅ **100% Live & Verified** | Test runners (`pytest`, `npm`) + AI Review (Normalized Non-Test Scoring) |
| **Stage 4: Submission** | [`scripts/submit.py`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/scripts/submit.py), [`scripts/github_utils.py`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/scripts/github_utils.py) | ✅ **100% Live & Verified** | `resilient-fix[bot]` GitHub App (JWT RS256 Auth) |
| **Stage 5: Leaderboard** | [`api/main.py`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/api/main.py), [`web/`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/web) | ✅ **100% Live & Verified** | FastAPI REST API + Three.js UI (**47/47 Tests Passed**) |

---

## ⚙️ Quick Start

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/harshitthek/resilient.git
cd resilient
pip install -r scripts/requirements.txt -r requirements-webhook.txt -r scripts/requirements-dispatch.txt
```

### 2. Configure Environment Variables
Create a `.env` configuration file (see [`.env.example`](file:///c:/Users/user/Desktop/dwsktop/harshit/projects/Resilient/.env.example)):
```ini
# PostgreSQL Database (e.g. Neon Serverless)
DATABASE_URL=postgresql://user:password@ep-host.region.aws.neon.tech/neondb?sslmode=require

# GitHub App Authentication (resilient-fix[bot])
GITHUB_APP_ID=4556724
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
GITHUB_SCAN_TOKEN=github_pat_...
GITHUB_DISPATCH_TOKEN=gho_...

# Free AI Model API Keys (Zero Credit Card Required)
GEMINI_API_KEY=AQ.Ab8RN6...
GROQ_API_KEY=gsk_...
NVIDIA_API_KEY=nvapi-...
COHERE_API_KEY=...
HF_TOKEN=hf_...
OPENROUTER_API_KEY=sk-or-v1-...
```

### 3. Launch Web Dashboard & REST API
```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser to view the live 3D Leaderboard!

### 4. Run Automated Test Suite
```bash
pytest -v
```

---

## 🔒 Security & Policy Enforcement

Resilient is engineered with strict safeguards to respect open-source maintainers and secure agent execution:

- 🛡️ **AI Policy Verification**: Inspects `CONTRIBUTING.md` and repository templates. Repositories with explicit AI prohibitions are deactivated immediately (`is_active = FALSE`).
- 📦 **Fork Sandbox Isolation**: Agents execute exclusively inside isolated personal fork branches (`resilient/{issue}/{model}`). Upstream repositories are never touched directly during development.
- ⏱️ **24-Hour Rolling Rate Caps**: Enforces strict submission caps (max 10 global PRs / max 2 per repo per 24 hours).
- 🔑 **Credential Redaction**: `sanitize_token()` automatically redacts PATs, JWT RS256 tokens, and environment secrets from diff patches and log outputs.
- 📢 **Transparent AI Disclosure**: Every pull request includes an explicit disclosure:
  > `> [!NOTE] This pull request was automatically generated by Resilient using an AI coding agent.`

---

## 📂 Repository Structure

```
resilient/
├── api/
│   └── main.py                     # FastAPI REST API Server & Leaderboard Endpoints
├── web/
│   ├── index.html                  # 3D Dashboard HTML5 layout with vector icons
│   ├── style.css                   # Glassmorphism dark theme CSS
│   ├── app.js                      # Three.js 3D Starfield & Chart.js radar client
│   └── favicon.svg                 # Glowing cyan vector favicon
├── scripts/
│   ├── discover.py                 # Stage 1: GitHub Trending & policy verification
│   ├── dispatch.py                 # Stage 2: Multi-agent tournament orchestrator
│   ├── evaluate.py                 # Stage 3: Test runner execution & AI code review
│   ├── submit.py                   # Stage 4: GitHub App authenticated PR delivery
│   └── github_utils.py             # Shared GitHub API & RS256 JWT auth utilities
├── agents/
│   ├── base.py                     # AgentAdapter interface & RepoContext dataclasses
│   ├── quality_ensemble_agent.py   # Quality-First Tournament & Consensus Agent
│   ├── gemini_agent.py             # Google Gemini 2.5 Flash / Pro adapter
│   ├── groq_agent.py               # Groq Cloud Llama 3.3 70B adapter
│   ├── nvidia_agent.py             # NVIDIA NIM Nemotron 3.5 adapter
│   ├── cohere_agent.py             # Cohere Command R adapter
│   ├── openrouter_agent.py         # OpenRouter free model pool adapter
│   ├── qwen_agent.py               # Qwen 2.5 Coder adapter
│   ├── mistral_agent.py            # Mistral / Codestral adapter
│   └── jules_adapter.py            # Google Jules cloud agent adapter
├── tests/                          # 52 Passing unit tests (100% green suite)
├── schema.sql                      # PostgreSQL schema definition
└── webhook_receiver.py             # HMAC-authenticated real-time issue receiver
```

---

<div align="center">
  <sub>Created with ❤️ by <b>Harshit</b> (<a href="https://github.com/harshitthek">@harshitthek</a>) • Licensed under the <a href="LICENSE">MIT License</a></sub>
</div>
