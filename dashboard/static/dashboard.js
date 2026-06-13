/* dashboard.js — MHTCET Checker Live Dashboard Logic */

let countdownInterval = null;
let refreshInterval = null;
let countdownSeconds = 0;

// ── Init ────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  fetchLogs();
  // Poll status every 5s for live countdown, logs every 15s
  setInterval(fetchStatus, 5000);
  setInterval(fetchLogs, 15000);
  generateParticles();
});

// ── Fetch Live Status ──────────────────────────────────────────
async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    updateDashboard(data);
  } catch (e) {
    console.error("Status fetch failed:", e);
  }
}

function updateDashboard(data) {
  // ── Header badge ──
  const dot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");

  if (data.pcm_found) {
    dot.className = "status-dot found";
    statusText.textContent = "PCM Found! 🎉";
    document.getElementById("alert-banner").classList.remove("hidden");
  } else if (data.checker_running) {
    dot.className = "status-dot running";
    statusText.textContent = "Running";
    document.getElementById("alert-banner").classList.add("hidden");
  } else {
    dot.className = "status-dot stopped";
    statusText.textContent = "Stopped";
    document.getElementById("alert-banner").classList.add("hidden");
  }

  // ── Checker badge ──
  const badge = document.getElementById("checker-running-badge");
  if (data.checker_running) {
    badge.textContent = "Running";
    badge.classList.add("running");
  } else {
    badge.textContent = "Stopped";
    badge.classList.remove("running");
  }

  // ── PCM Status card ──
  const pcmEl = document.getElementById("pcm-status");
  if (data.pcm_found) {
    pcmEl.textContent = "✅ AVAILABLE";
    pcmEl.style.color = "#4ade80";
  } else {
    pcmEl.textContent = "⏳ Not Yet";
    pcmEl.style.color = "#94a3b8";
  }

  // ── Login status ──
  const loginEl = document.getElementById("login-status");
  const ls = data.last_login_status || "—";
  loginEl.textContent = ls.charAt(0).toUpperCase() + ls.slice(1);
  loginEl.style.color = ls === "success" ? "#4ade80" : ls === "failed" ? "#f87171" : "#94a3b8";

  // ── Last checked ──
  document.getElementById("last-checked").textContent = data.last_checked || "Never";

  // ── Total checks ──
  document.getElementById("total-checks").textContent = data.total_checks ?? 0;

  // ── Consecutive errors ──
  const errEl = document.getElementById("consec-errors");
  errEl.textContent = data.consecutive_errors ?? 0;
  errEl.style.color = (data.consecutive_errors > 0) ? "#fbbf24" : "#94a3b8";

  // ── Countdown — pass both secs and running state ──
  startCountdown(data.next_check_secs, data.checker_running);

  // ── Error banner ──
  const errorBanner = document.getElementById("error-banner");
  const errorText   = document.getElementById("error-text");
  if (data.last_error && data.checker_running) {
    errorBanner.classList.remove("hidden");
    errorText.textContent = data.last_error;
  } else {
    errorBanner.classList.add("hidden");
  }

  // ── Fire event so monitor cards update ──
  document.dispatchEvent(new CustomEvent('statusUpdated', { detail: data }));
}

// ── Countdown Timer ────────────────────────────────────────────
function startCountdown(seconds, checkerRunning) {
  clearInterval(countdownInterval);
  const el = document.getElementById("next-check-countdown");

  // Checker stopped
  if (!checkerRunning) {
    el.textContent = "Stopped";
    el.style.color = "#64748b";
    return;
  }

  // No next run time from scheduler yet
  if (seconds === null || seconds === undefined) {
    el.textContent = "Starting...";
    el.style.color = "#94a3b8";
    return;
  }

  // Currently checking (countdown hit 0 and check is running)
  if (seconds === 0) {
    el.textContent = "Checking...";
    el.style.color = "#60a5fa";
    return;
  }

  el.style.color = "";
  countdownSeconds = seconds;
  el.textContent = formatTime(countdownSeconds);

  countdownInterval = setInterval(() => {
    countdownSeconds--;
    if (countdownSeconds <= 0) {
      el.textContent = "Checking...";
      el.style.color = "#60a5fa";
      clearInterval(countdownInterval);
      // fetchStatus() will be called by the 5s poll, no need for extra setTimeout
    } else {
      el.style.color = "";
      el.textContent = formatTime(countdownSeconds);
    }
  }, 1000);
}

function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

// ── Fetch Logs ────────────────────────────────────────────────
async function fetchLogs() {
  try {
    const res = await fetch("/api/logs");
    const logs = await res.json();
    renderLogs(logs);
  } catch (e) {
    console.error("Logs fetch failed:", e);
  }
}

function renderLogs(logs) {
  const tbody = document.getElementById("log-body");
  if (!logs || logs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-row">No checks yet. Start the checker!</td></tr>`;
    return;
  }

  tbody.innerHTML = logs.map((log, i) => {
    const loginBadge = log.login_status === "success"
      ? `<span class="badge badge-success">✓ Success</span>`
      : log.login_status === "failed"
      ? `<span class="badge badge-failed">✗ Failed</span>`
      : `<span class="badge badge-error">⚠ Error</span>`;

    const pcmBadge = log.pcm_found
      ? `<span class="badge badge-yes">🎯 YES</span>`
      : `<span class="badge badge-no">—</span>`;

    // Method column: show if detection was API-based or UI scan
    const methodBadge = log.api_detected
      ? `<span style="font-size:.7rem;background:rgba(52,211,153,.15);color:#34d399;padding:2px 6px;border-radius:5px;">API</span>`
      : `<span style="font-size:.7rem;background:rgba(167,139,250,.12);color:#a78bfa;padding:2px 6px;border-radius:5px;">UI</span>`;

    const notes = log.error_message
      ? `<span style="color:#fca5a5;font-size:0.78rem;">${escapeHtml(log.error_message.substring(0,80))}</span>`
      : log.page_title
      ? `<span style="color:#64748b;font-size:0.78rem;">${escapeHtml(log.page_title.substring(0,60))}</span>`
      : `<span style="color:#374151;">—</span>`;

    return `
      <tr>
        <td>${log.id}</td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:0.78rem;">${log.timestamp}</td>
        <td>${loginBadge}</td>
        <td>${pcmBadge}</td>
        <td>${methodBadge}</td>
        <td>${notes}</td>
      </tr>
    `;
  }).join("");
}

// ── Controls ──────────────────────────────────────────────────
async function controlChecker(action) {
  try {
    const res = await fetch(`/api/${action}`, { method: "POST" });
    const data = await res.json();
    showToast(data.msg, data.ok ? "success" : "error");
    setTimeout(fetchStatus, 500);
  } catch (e) {
    showToast("Request failed. Is the server running?", "error");
  }
}

async function runNow() {
  showToast("⏱ Triggering immediate check...", "info");
  try {
    const res = await fetch("/api/run-now", { method: "POST" });
    const data = await res.json();
    showToast(data.msg, "success");
    setTimeout(() => { fetchStatus(); fetchLogs(); }, 3000);
  } catch (e) {
    showToast("Failed to trigger check.", "error");
  }
}

async function resetAlert() {
  if (!confirm("Reset alert status? This allows new notifications to be sent.")) return;
  try {
    const res = await fetch("/api/reset", { method: "POST" });
    const data = await res.json();
    showToast(data.msg, "success");
    setTimeout(fetchStatus, 500);
  } catch (e) {
    showToast("Reset failed.", "error");
  }
}

async function testNotification(type) {
  showToast(`📤 Sending test ${type}...`, "info");
  try {
    const res = await fetch("/api/test-notification", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type })
    });
    const data = await res.json();
    const success = Object.values(data.results || {}).some(r => r?.success);
    showToast(
      success ? `✅ Test ${type} sent!` : `⚠️ Test ${type} failed — check Twilio config`,
      success ? "success" : "error"
    );
  } catch (e) {
    showToast("Test notification request failed.", "error");
  }
}

// ── Toast ──────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, type = "info") {
  const toast = document.getElementById("toast");
  const colors = {
    success: "#22c55e",
    error:   "#ef4444",
    info:    "#3b82f6"
  };
  toast.style.borderColor = colors[type] || colors.info;
  toast.textContent = msg;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3500);
}

// ── Particles ─────────────────────────────────────────────────
function generateParticles() {
  const container = document.getElementById("particles");
  if (!container) return;
  const count = 20;
  for (let i = 0; i < count; i++) {
    const el = document.createElement("div");
    el.style.cssText = `
      position: absolute;
      width: ${Math.random() * 3 + 1}px;
      height: ${Math.random() * 3 + 1}px;
      background: rgba(${Math.random() > 0.5 ? '59,130,246' : '139,92,246'},${Math.random() * 0.3 + 0.1});
      border-radius: 50%;
      left: ${Math.random() * 100}%;
      top: ${Math.random() * 100}%;
      animation: float ${Math.random() * 15 + 10}s ease-in-out infinite;
      animation-delay: ${Math.random() * -10}s;
    `;
    container.appendChild(el);
  }

  const style = document.createElement("style");
  style.textContent = `
    @keyframes float {
      0%, 100% { transform: translateY(0px) translateX(0px); opacity: 0.3; }
      25% { transform: translateY(-30px) translateX(15px); opacity: 0.7; }
      50% { transform: translateY(-15px) translateX(-20px); opacity: 0.4; }
      75% { transform: translateY(-40px) translateX(10px); opacity: 0.6; }
    }
  `;
  document.head.appendChild(style);
}

// ── Helpers ────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
