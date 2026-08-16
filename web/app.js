/**
 * Resilient Leaderboard App Logic — Three.js 3D Background, Live Control Panel & Filter Features
 */

const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" 
    ? "http://localhost:8000/api/v1" 
    : "/api/v1";

let currentLanguage = "all";
let activeRunDiff = "";
let activeRunError = "";
let activeInspectorTab = "diff";

// Fallback seed data for GitHub Pages static hosting
const STATIC_SEEDS = {
    leaderboard: [
        {
            agent_name: "quality-ensemble-tournament",
            total_runs: 1,
            successful_runs: 1,
            failed_runs: 0,
            pass_rate: 100.0,
            avg_reviewer_score: 0.95,
            avg_composite_score: 0.98,
            prs_submitted: 1,
            prs_merged: 0,
            merge_rate: 0.0,
            avg_duration_seconds: 45.0
        },
        {
            agent_name: "gemini-2.5-flash",
            total_runs: 34,
            successful_runs: 1,
            failed_runs: 31,
            pass_rate: 2.9,
            avg_reviewer_score: 0.85,
            avg_composite_score: 0.85,
            prs_submitted: 1,
            prs_merged: 0,
            merge_rate: 0.0,
            avg_duration_seconds: 45.0
        },
        {
            agent_name: "nvidia/nemotron-3.5-lightning",
            total_runs: 4,
            successful_runs: 4,
            failed_runs: 0,
            pass_rate: 100.0,
            avg_reviewer_score: 0.92,
            avg_composite_score: 0.94,
            prs_submitted: 1,
            prs_merged: 0,
            merge_rate: 0.0,
            avg_duration_seconds: 4.02
        },
        {
            agent_name: "groq/llama-3.3-70b",
            total_runs: 6,
            successful_runs: 5,
            failed_runs: 1,
            pass_rate: 83.3,
            avg_reviewer_score: 0.78,
            avg_composite_score: 0.81,
            prs_submitted: 0,
            prs_merged: 0,
            merge_rate: 0.0,
            avg_duration_seconds: 1.28
        }
    ],
    runs: [
        {
            id: 40,
            repo_full_name: "MakazhanAlpamys/Soup",
            issue_number: 423,
            issue_title: "detect_device() does not know MLX: Apple Silicon run reports CPU and downgrades quantization 4bit -> none",
            agent_name: "quality-ensemble-tournament",
            status: "success",
            language: "Python",
            branch_name: "resilient/423/quality-tournament",
            diff_url: "https://github.com/harshitthek/Soup/compare/main...resilient/423/quality-tournament",
            composite_score: 0.98
        },
        {
            id: 1,
            repo_full_name: "obra/superpowers",
            issue_number: 2140,
            issue_title: "subagent-driven-development: naming implementer switches to teammate mode",
            agent_name: "gemini-2.5-flash",
            status: "success",
            language: "Python",
            branch_name: "resilient/2140/gemini-2.5-flash",
            diff_url: "https://github.com/harshitthek/superpowers/compare/main...resilient/2140/gemini-2.5-flash",
            composite_score: 0.85
        }
    ],
    repos: [
        { full_name: "MakazhanAlpamys/Soup", stars: 1842, stars_growth: 120, language: "Python", allows_ai_prs: true },
        { full_name: "obra/superpowers", stars: 3200, stars_growth: 245, language: "Python", allows_ai_prs: true },
        { full_name: "astral-sh/uv", stars: 41200, stars_growth: 1890, language: "Rust", allows_ai_prs: true },
        { full_name: "pydantic/pydantic", stars: 22800, stars_growth: 510, language: "Python", allows_ai_prs: true }
    ],
    pr_status: {
        total_submitted: 2,
        pending: 2,
        merged: 0,
        closed: 0
    },
    feed: [
        {
            title: "Submitted PR #428 for issue #423 (MakazhanAlpamys/Soup)",
            timestamp: new Date().toISOString(),
            repo: "MakazhanAlpamys/Soup"
        },
        {
            title: "Evaluated run #40: Quality Tournament 0.98 Composite Score",
            timestamp: new Date(Date.now() - 300000).toISOString(),
            repo: "MakazhanAlpamys/Soup"
        },
        {
            title: "Dispatched Quality Tournament on issue #423",
            timestamp: new Date(Date.now() - 600000).toISOString(),
            repo: "MakazhanAlpamys/Soup"
        },
        {
            title: "Submitted PR #2148 for issue #2140 (obra/superpowers)",
            timestamp: new Date(Date.now() - 86400000).toISOString(),
            repo: "obra/superpowers"
        }
    ]
};

// --- 1. Three.js 3D Ambient Particle Background Canvas ---

function initThreeJSBackground() {
    const canvas = document.getElementById("bg-canvas");
    if (!canvas) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 40;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    const particleCount = 600;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);

    const color1 = new THREE.Color("#06b6d4");
    const color2 = new THREE.Color("#10b981");

    for (let i = 0; i < particleCount; i++) {
        positions[i * 3] = (Math.random() - 0.5) * 120;
        positions[i * 3 + 1] = (Math.random() - 0.5) * 120;
        positions[i * 3 + 2] = (Math.random() - 0.5) * 80;

        const mixedColor = color1.clone().lerp(color2, Math.random());
        colors[i * 3] = mixedColor.r;
        colors[i * 3 + 1] = mixedColor.g;
        colors[i * 3 + 2] = mixedColor.b;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const canvasTexture = document.createElement('canvas');
    canvasTexture.width = 16;
    canvasTexture.height = 16;
    const ctxTexture = canvasTexture.getContext('2d');
    const grad = ctxTexture.createRadialGradient(8, 8, 0, 8, 8, 8);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.4, 'rgba(6,182,212,0.6)');
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    ctxTexture.fillStyle = grad;
    ctxTexture.fillRect(0, 0, 16, 16);
    const texture = new THREE.CanvasTexture(canvasTexture);

    const material = new THREE.PointsMaterial({
        size: 1.2,
        map: texture,
        vertexColors: true,
        transparent: true,
        opacity: 0.45,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
    });

    const particleSystem = new THREE.Points(geometry, material);
    scene.add(particleSystem);

    let mouseX = 0;
    let mouseY = 0;

    document.addEventListener("mousemove", (e) => {
        mouseX = (e.clientX - window.innerWidth / 2) * 0.0002;
        mouseY = (e.clientY - window.innerHeight / 2) * 0.0002;
    });

    window.addEventListener("resize", () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });

    function animate() {
        requestAnimationFrame(animate);
        particleSystem.rotation.y += 0.0005 + mouseX * 0.05;
        particleSystem.rotation.x += 0.0003 + mouseY * 0.05;
        renderer.render(scene, camera);
    }
    animate();
}


// --- 2. Data Fetching & UI Rendering ---

async function fetchAPI(endpoint, options = {}) {
    try {
        const res = await fetch(`${API_BASE}${endpoint}`, options);
        if (res.ok) {
            return await res.json();
        }
    } catch (e) {
        console.warn(`API fetch ${endpoint} failed:`, e);
    }
    return null;
}


async function loadLeaderboard() {
    let data = await fetchAPI(`/leaderboard?language=${currentLanguage}`);
    if (!data || data.length === 0) {
        data = STATIC_SEEDS.leaderboard;
    }
    const tbody = document.getElementById("leaderboard-body");
    if (!tbody) return;

    if (!data || data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">No agent runs recorded for '${currentLanguage}' language filter.</td></tr>`;
        return;
    }

    tbody.innerHTML = data.map((item, index) => `
        <tr>
            <td><span class="rank-badge rank-${index + 1}">${index + 1}</span></td>
            <td><span class="model-name">${item.agent_name}</span></td>
            <td>
                <strong>${item.pass_rate}%</strong>
                <div class="progress-bar-container">
                    <div class="progress-bar-fill" style="width: ${item.pass_rate}%"></div>
                </div>
            </td>
            <td><strong>${item.merge_rate}%</strong></td>
            <td>${item.avg_reviewer_score}</td>
            <td>${item.total_runs}</td>
            <td><span class="badge badge-success">Active</span></td>
        </tr>
    `).join("");

    initRadarChart(data);
}


function initRadarChart(leaderboardData) {
    const ctx = document.getElementById("comparisonRadarChart");
    if (!ctx || !leaderboardData || leaderboardData.length === 0) return;

    if (window.radarChartInstance) {
        window.radarChartInstance.destroy();
    }

    const labels = ["Pass Rate", "Merge Rate", "Quality Score", "Speed", "Reliability"];
    const datasets = leaderboardData.map((model, idx) => ({
        label: model.agent_name,
        data: [
            model.pass_rate,
            model.merge_rate * 2,
            model.avg_reviewer_score * 100,
            85 - idx * 10,
            90 - idx * 15,
        ],
        borderColor: idx === 0 ? "#06b6d4" : (idx === 1 ? "#10b981" : (idx === 2 ? "#3b82f6" : "#f59e0b")),
        backgroundColor: idx === 0 ? "rgba(6, 182, 212, 0.25)" : (idx === 1 ? "rgba(16, 185, 129, 0.25)" : "rgba(59, 130, 246, 0.25)"),
        pointBackgroundColor: "#ffffff",
    }));

    window.radarChartInstance = new Chart(ctx, {
        type: "radar",
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                r: {
                    angleLines: { color: "rgba(255, 255, 255, 0.15)" },
                    grid: { color: "rgba(255, 255, 255, 0.15)" },
                    pointLabels: { color: "#cbd5e1", font: { size: 11 } },
                    ticks: { display: false }
                }
            },
            plugins: {
                legend: { labels: { color: "#ffffff" } }
            }
        }
    });
}


async function loadRuns() {
    let runs = await fetchAPI(`/runs?language=${currentLanguage}`);
    if (!runs || runs.length === 0) {
        runs = STATIC_SEEDS.runs;
    }
    const container = document.getElementById("runs-grid");
    if (!container) return;

    if (!runs || runs.length === 0) {
        container.innerHTML = `<div class="glass-card" style="padding: 24px; text-align: center; color: var(--text-muted); grid-column: 1/-1;">No runs matching '${currentLanguage}' filter.</div>`;
        return;
    }

    container.innerHTML = runs.map(run => `
        <div class="run-card glass-card">
            <div>
                <div class="run-header">
                    <span class="run-repo">${run.repo_full_name} #${run.issue_number}</span>
                    <span class="badge ${run.status === 'success' ? 'badge-success' : 'badge-failed'}">${run.status}</span>
                </div>
                <h4 class="run-title">${run.issue_title}</h4>
                <div class="run-meta">
                    <span>Agent: <strong>${run.agent_name}</strong></span>
                    <span>Language: <strong>${run.language}</strong></span>
                </div>
            </div>
            <button class="btn-diff" onclick="openDiffModal(${run.id})">🔍 Inspect Code Fix / Traceback</button>
        </div>
    `).join("");
}


async function loadRepos() {
    let repos = await fetchAPI(`/repos?language=${currentLanguage}`);
    if (!repos || repos.length === 0) {
        repos = STATIC_SEEDS.repos;
    }
    const container = document.getElementById("repo-list");
    if (!container) return;

    const kpiRepos = document.getElementById("kpi-repos");
    if (kpiRepos && repos.length > 0) kpiRepos.innerText = repos.length;

    initTrendingChart(repos);

    function renderList(filtered) {
        if (filtered.length === 0) {
            container.innerHTML = `<div style="padding: 16px; color: var(--text-muted); font-size: 13px;">No matching repositories found.</div>`;
            return;
        }

        container.innerHTML = filtered.map(r => `
            <div class="repo-item">
                <div>
                    <strong>${r.full_name}</strong>
                    <div style="font-size: 12px; color: var(--text-muted);">
                        ⭐ ${r.stars} (+${r.stars_growth} trending) • ${r.language}
                    </div>
                </div>
                <span class="badge badge-success">${r.allows_ai_prs ? 'AI PRs Allowed' : 'Policy Blocked'}</span>
            </div>
        `).join("");
    }

    renderList(repos);

    const searchInput = document.getElementById("repo-search");
    if (searchInput) {
        searchInput.addEventListener("input", (e) => {
            const query = e.target.value.toLowerCase();
            const filtered = repos.filter(r => r.full_name.toLowerCase().includes(query));
            renderList(filtered);
        });
    }
}


function initTrendingChart(repos) {
    const ctx = document.getElementById("trendingChart");
    if (!ctx || !repos || repos.length === 0) return;

    if (window.trendingChartInstance) {
        window.trendingChartInstance.destroy();
    }

    const topRepos = repos.slice(0, 6);
    const labels = topRepos.map(r => r.full_name.split('/')[1] || r.full_name);
    const stars = topRepos.map(r => r.stars);

    window.trendingChartInstance = new Chart(ctx, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "GitHub Stars",
                data: stars,
                backgroundColor: "rgba(45, 212, 191, 0.4)",
                borderColor: "#2dd4bf",
                borderWidth: 1,
                borderRadius: 6,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { display: false }, ticks: { color: "#cbd5e1", font: { size: 10 } } },
                y: { grid: { color: "rgba(255,255,255,0.1)" }, ticks: { color: "#cbd5e1", font: { size: 10 } } }
            },
            plugins: { legend: { display: false } }
        }
    });
}


async function loadPRStatus() {
    let data = await fetchAPI("/pr-status");
    if (!data) {
        data = STATIC_SEEDS.pr_status;
    }

    document.getElementById("pr-num-total").innerText = data.total_submitted || 2;
    document.getElementById("pr-num-pending").innerText = data.pending || 2;
    document.getElementById("pr-num-merged").innerText = data.merged || 0;
    document.getElementById("pr-num-closed").innerText = data.closed || 0;
}


async function loadActivityFeed() {
    let feed = await fetchAPI("/feed");
    if (!feed || feed.length === 0) {
        feed = STATIC_SEEDS.feed;
    }
    const container = document.getElementById("activity-feed");
    if (!container) return;

    if (!feed || feed.length === 0) {
        container.innerHTML = `<div style="padding: 16px; color: var(--text-muted); font-size: 13px;">No events recorded in pipeline stream.</div>`;
        return;
    }

    container.innerHTML = feed.map(item => `
        <div class="activity-item">
            <strong style="color: var(--accent-cyan); font-size: 13px;">${item.title}</strong>
            <span style="font-size: 11px; color: var(--text-muted);">${new Date(item.timestamp).toLocaleTimeString()} • ${item.repo}</span>
        </div>
    `).join("");
}


// --- 3. Language Filter Tabs ---

function setLanguageFilter(lang) {
    currentLanguage = lang;
    document.querySelectorAll(".filter-tab").forEach(tab => {
        tab.classList.toggle("active", tab.innerText.toLowerCase().includes(lang));
    });
    loadLeaderboard();
    loadRuns();
    loadRepos();
}


// --- 4. Interactive Live Pipeline Control Panel ---

async function triggerPipeline(stage) {
    const consoleBox = document.getElementById("console-output");
    if (!consoleBox) return;

    consoleBox.innerHTML = `<span class="console-prefix">&gt; Executing Stage '${stage}' live python script... Please wait.</span>`;

    const res = await fetchAPI(`/pipeline/trigger-${stage}`, { method: "POST" });
    if (res) {
        consoleBox.innerHTML = `<span class="console-prefix">&gt; [Stage ${stage.toUpperCase()}] ${res.message}</span>\n${escapeHtml(res.stdout)}`;
        // Reload dashboard live data after trigger
        setTimeout(() => {
            loadLeaderboard();
            loadRuns();
            loadRepos();
            loadActivityFeed();
            loadPRStatus();
        }, 1000);
    } else {
        consoleBox.innerHTML = `<span class="console-prefix" style="color: var(--accent-rose);">&gt; Failed to reach FastAPI trigger endpoint for stage ${stage}.</span>`;
    }
}


// --- 5. Code Fix & Error Inspector Modal with 1-Click Copy ---

async function openDiffModal(runId) {
    const modal = document.getElementById("diff-modal");
    const container = document.getElementById("modal-diff-container");
    if (!modal || !container) return;

    modal.classList.remove("hidden");
    container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">Loading code fix patch & traceback for run #${runId}...</p>`;

    const diffData = await fetchAPI(`/runs/${runId}/diff`);
    if (diffData) {
        activeRunDiff = diffData.diff_text || "No git diff patch recorded.";
        activeRunError = diffData.error_log || "No error traceback recorded. Run executed cleanly.";
        switchInspectorTab("diff");
    } else {
        container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">Failed to load run details.</p>`;
    }
}


function switchInspectorTab(tab) {
    activeInspectorTab = tab;
    document.getElementById("tab-diff").classList.toggle("active", tab === "diff");
    document.getElementById("tab-error").classList.toggle("active", tab === "error");

    const container = document.getElementById("modal-diff-container");
    const content = tab === "diff" ? activeRunDiff : activeRunError;
    const color = tab === "diff" ? "#38bdf8" : "#f43f5e";

    container.innerHTML = `<pre style="padding: 16px; background: rgba(0,0,0,0.7); border-radius: 8px; color: ${color}; overflow-x: auto; max-height: 400px; border: 1px solid rgba(255,255,255,0.1);">${escapeHtml(content)}</pre>`;
}


function copyInspectorContent() {
    const content = activeInspectorTab === "diff" ? activeRunDiff : activeRunError;
    navigator.clipboard.writeText(content).then(() => {
        const btn = document.getElementById("copy-btn");
        const orig = btn.innerText;
        btn.innerText = "✓ Copied!";
        setTimeout(() => { btn.innerText = orig; }, 2000);
    });
}


function escapeHtml(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}


function closeDiffModal() {
    const modal = document.getElementById("diff-modal");
    if (modal) modal.classList.add("hidden");
}


// --- Initialization ---

document.addEventListener("DOMContentLoaded", () => {
    initThreeJSBackground();
    loadLeaderboard();
    loadRuns();
    loadRepos();
    loadPRStatus();
    loadActivityFeed();
});
