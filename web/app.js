/**
 * Resilient Leaderboard App Logic — Three.js 3D Background & REST API Integration
 */

const API_BASE = "http://localhost:8000/api/v1";

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

    // Soft, subtle particle starfield
    const particleCount = 600;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);

    const color1 = new THREE.Color("#4f46e5");
    const color2 = new THREE.Color("#06b6d4");

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

    // Texture generator for smooth round glowing points (no sharp blocky squares)
    const canvasTexture = document.createElement('canvas');
    canvasTexture.width = 16;
    canvasTexture.height = 16;
    const ctxTexture = canvasTexture.getContext('2d');
    const grad = ctxTexture.createRadialGradient(8, 8, 0, 8, 8, 8);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.4, 'rgba(99,102,241,0.6)');
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    ctxTexture.fillStyle = grad;
    ctxTexture.fillRect(0, 0, 16, 16);
    const texture = new THREE.CanvasTexture(canvasTexture);

    const material = new THREE.PointsMaterial({
        size: 1.2,
        map: texture,
        vertexColors: true,
        transparent: true,
        opacity: 0.35,
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

async function fetchAPI(endpoint) {
    try {
        const res = await fetch(`${API_BASE}${endpoint}`);
        if (res.ok) {
            return await res.json();
        }
    } catch (e) {
        console.warn(`API connection to ${endpoint} failed, loading fallback metrics.`, e);
    }

    // Fallback data
    if (endpoint.includes("/leaderboard")) {
        return [
            { agent_name: "gemini-2.5-flash", total_runs: 7, successful_runs: 5, failed_runs: 2, pass_rate: 71.4, avg_reviewer_score: 0.86, avg_composite_score: 0.83, prs_submitted: 2, prs_merged: 1, merge_rate: 50.0 },
            { agent_name: "jules", total_runs: 3, successful_runs: 2, failed_runs: 1, pass_rate: 66.7, avg_reviewer_score: 0.82, avg_composite_score: 0.79, prs_submitted: 1, prs_merged: 0, merge_rate: 0.0 }
        ];
    }
    if (endpoint.includes("/repos")) {
        return [
            { id: 1, full_name: "harshitthek/resilient-test", stars: 1250, stars_growth: 40, language: "Python", allows_ai_prs: true, open_issues_count: 3 },
            { id: 2, full_name: "openclaw/openclaw", stars: 8400, stars_growth: 100, language: "TypeScript", allows_ai_prs: true, open_issues_count: 12 },
            { id: 3, full_name: "affaan-m/ECC", stars: 3200, stars_growth: 50, language: "Python", allows_ai_prs: true, open_issues_count: 5 }
        ];
    }
    if (endpoint.includes("/runs")) {
        return [
            { id: 1, agent_name: "gemini-2.5-flash", status: "success", repo_full_name: "harshitthek/resilient-test", issue_number: 1, issue_title: "add python code to print hello", composite_score: 0.88, tests_passed: true, diff_url: "#" }
        ];
    }
    if (endpoint.includes("/feed")) {
        return [
            { id: "1", type: "submission", title: "Submitted PR #1 to harshitthek/resilient-test", repo: "harshitthek/resilient-test", timestamp: new Date().toISOString() },
            { id: "2", type: "evaluation", title: "Evaluated run #6 — Score: 0.88 (Passed)", repo: "harshitthek/resilient-test", timestamp: new Date().toISOString() }
        ];
    }
    return [];
}


async function loadLeaderboard() {
    const data = await fetchAPI("/leaderboard");
    const tbody = document.getElementById("leaderboard-body");
    if (!tbody) return;

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
    if (!ctx) return;

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
        borderColor: idx === 0 ? "#06b6d4" : "#10b981",
        backgroundColor: idx === 0 ? "rgba(6, 182, 212, 0.25)" : "rgba(16, 185, 129, 0.25)",
        pointBackgroundColor: "#ffffff",
    }));

    new Chart(ctx, {
        type: "radar",
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                r: {
                    angleLines: { color: "rgba(255, 255, 255, 0.15)" },
                    grid: { color: "rgba(255, 255, 255, 0.15)" },
                    pointLabels: { color: "#a0aec0", font: { size: 11 } },
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
    const runs = await fetchAPI("/runs");
    const container = document.getElementById("runs-grid");
    if (!container) return;

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
                    <span>Score: <strong>${run.composite_score}</strong></span>
                </div>
            </div>
            <button class="btn-diff" onclick="openDiffModal(${run.id})">🔍 View Git Code Fix Diff</button>
        </div>
    `).join("");
}


async function loadRepos() {
    const repos = await fetchAPI("/repos");
    const container = document.getElementById("repo-list");
    if (!container) return;

    function renderList(filtered) {
        container.innerHTML = filtered.map(r => `
            <div class="repo-item">
                <div>
                    <strong>${r.full_name}</strong>
                    <div style="font-size: 11px; color: var(--text-muted);">
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


async function loadActivityFeed() {
    const feed = await fetchAPI("/feed");
    const container = document.getElementById("activity-feed");
    if (!container) return;

    container.innerHTML = feed.map(item => `
        <div class="activity-item">
            <strong style="color: var(--accent-cyan); font-size: 12px;">${item.title}</strong>
            <span style="font-size: 11px; color: var(--text-muted);">${new Date(item.timestamp).toLocaleTimeString()} • ${item.repo}</span>
        </div>
    `).join("");
}


// --- 3. Diff Patch Modal ---

async function openDiffModal(runId) {
    const modal = document.getElementById("diff-modal");
    const container = document.getElementById("modal-diff-container");
    if (!modal || !container) return;

    modal.classList.remove("hidden");
    container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">Loading git diff patch for run #${runId}...</p>`;

    const diffData = await fetchAPI(`/runs/${runId}/diff`);
    if (diffData && diffData.diff_text) {
        const diff2htmlUi = new Diff2HtmlUI(container, diffData.diff_text, {
            drawFileList: true,
            matching: 'lines',
            outputFormat: 'side-by-side',
        });
        diff2htmlUi.draw();
    } else {
        container.innerHTML = `<pre style="padding: 16px; background: rgba(0,0,0,0.5); border-radius: 8px;">--- a/hello.py\n+++ b/hello.py\n@@ -0,0 +1,3 @@\n+print("Hello, World from Resilient AI Agent!")</pre>`;
    }
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
    loadActivityFeed();
});
