/**
 * Resilient Leaderboard App Logic — Three.js 3D Background & Live REST API Integration
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

async function fetchAPI(endpoint) {
    try {
        const res = await fetch(`${API_BASE}${endpoint}`);
        if (res.ok) {
            return await res.json();
        }
    } catch (e) {
        console.warn(`API fetch ${endpoint} failed:`, e);
    }
    return [];
}


async function loadLeaderboard() {
    const data = await fetchAPI("/leaderboard");
    const tbody = document.getElementById("leaderboard-body");
    if (!tbody) return;

    if (!data || data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">No agent runs recorded yet. Dispatched runs will populate live.</td></tr>`;
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
    const runs = await fetchAPI("/runs");
    const container = document.getElementById("runs-grid");
    if (!container) return;

    if (!runs || runs.length === 0) {
        container.innerHTML = `<div class="glass-card" style="padding: 24px; text-align: center; color: var(--text-muted); grid-column: 1/-1;">No runs dispatched yet. Candidate issues land from GitHub discovery scan.</div>`;
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
                    <span>Score: <strong>${run.composite_score}</strong></span>
                </div>
            </div>
            <button class="btn-diff" onclick="openDiffModal(${run.id})">🔍 Inspect Code Fix / Error Log</button>
        </div>
    `).join("");
}


async function loadRepos() {
    const repos = await fetchAPI("/repos");
    const container = document.getElementById("repo-list");
    if (!container) return;

    const kpiRepos = document.getElementById("kpi-repos");
    if (kpiRepos && repos.length > 0) kpiRepos.innerText = repos.length;

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


async function loadActivityFeed() {
    const feed = await fetchAPI("/feed");
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


// --- 3. Diff Patch Modal ---

async function openDiffModal(runId) {
    const modal = document.getElementById("diff-modal");
    const container = document.getElementById("modal-diff-container");
    if (!modal || !container) return;

    modal.classList.remove("hidden");
    container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">Fetching live git patch / error log for run #${runId}...</p>`;

    const diffData = await fetchAPI(`/runs/${runId}/diff`);
    if (diffData && diffData.diff_text) {
        container.innerHTML = `<pre style="padding: 16px; background: rgba(0,0,0,0.6); border-radius: 8px; color: #a5b4fc; overflow-x: auto;">${escapeHtml(diffData.diff_text)}</pre>`;
    } else {
        container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">No diff data available for run #${runId}.</p>`;
    }
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
    loadActivityFeed();
});
