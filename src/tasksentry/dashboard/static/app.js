document.addEventListener("DOMContentLoaded", () => {
  // Tab switching
  const tabs = document.querySelectorAll(".nav-tab");
  const contents = document.querySelectorAll(".tab-content");

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      contents.forEach(c => c.classList.remove("active"));
      tab.classList.add("active");
      const target = document.getElementById(`tab-${tab.dataset.tab}`);
      if (target) target.classList.add("active");

      // Auto-load tab data
      if (tab.dataset.tab === "tasks") loadTasks();
      if (tab.dataset.tab === "benchmarks") loadBenchmarks();
      if (tab.dataset.tab === "ollama-health") checkOllamaHealth();
    });
  });

  // Load metrics & tasks
  async function loadTasks() {
    try {
      const [mRes, tRes] = await Promise.all([
        fetch("/api/metrics"),
        fetch("/api/tasks?limit=50")
      ]);
      const metrics = await mRes.json();
      const tasks = await tRes.json();

      document.getElementById("m-tasks").textContent = metrics.total_tasks;
      document.getElementById("m-success").textContent = (metrics.success_rate * 100).toFixed(1) + "%";
      document.getElementById("m-tokens").textContent = metrics.total_tokens.toLocaleString();
      document.getElementById("m-cost").textContent = "$" + metrics.total_cost_usd.toFixed(4);
      document.getElementById("m-dups").textContent = metrics.duplicate_calls_blocked;

      const tbody = document.getElementById("tasks-tbody");
      if (!tasks.length) {
        tbody.innerHTML = `<tr><td colspan="8">No tasks recorded yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = tasks.map(t => `
        <tr>
          <td><strong>${t.task_id}</strong></td>
          <td><span class="status-badge status-${t.status}">${t.status}</span></td>
          <td>${t.success ? "✅ Yes" : "❌ No"}</td>
          <td>${t.tokens.toLocaleString()}</td>
          <td>$${t.cost_usd.toFixed(4)}</td>
          <td>${t.tool_calls}</td>
          <td>${t.wall_time_seconds.toFixed(2)}s</td>
          <td><button class="btn" style="padding: 0.2rem 0.5rem; font-size: 0.8rem;" onclick="viewDetail('${t.task_id}')">Inspect</button></td>
        </tr>
      `).join("");
    } catch (e) {
      console.error(e);
    }
  }

  // Load task detail
  window.viewDetail = function(taskId) {
    document.querySelector('.nav-tab[data-tab="task-detail"]').click();
    document.getElementById("detail-task-id").value = taskId;
    loadTaskDetail(taskId);
  };

  async function loadTaskDetail(taskId) {
    const view = document.getElementById("task-detail-view");
    if (!taskId) return;
    view.innerHTML = "<p>Loading task details...</p>";
    try {
      const res = await fetch(`/api/tasks/${taskId}`);
      if (!res.ok) {
        view.innerHTML = `<p style="color:var(--danger)">Task '${taskId}' not found.</p>`;
        return;
      }
      const data = await res.json();
      const r = data.receipt || {};
      const c = data.contract || {};

      view.innerHTML = `
        <div class="card-detail">
          <h3>Task: ${data.task_id} (${data.status})</h3>
          <p><strong>Goal:</strong> ${c.goal || "N/A"}</p>
          <p><strong>Cost:</strong> $${data.cost_usd.toFixed(4)} | <strong>Tokens:</strong> ${data.tokens} | <strong>Calls:</strong> ${data.tool_calls}</p>
        </div>
        <div class="card-detail">
          <h4>Verification Results</h4>
          <pre>${JSON.stringify(r.verification_results || [], null, 2)}</pre>
        </div>
        <div class="card-detail">
          <h4>Execution Receipt</h4>
          <pre>${JSON.stringify(r, null, 2)}</pre>
        </div>
      `;
    } catch (e) {
      view.innerHTML = `<p style="color:var(--danger)">Error: ${e.message}</p>`;
    }
  }

  document.getElementById("btn-load-detail").addEventListener("click", () => {
    loadTaskDetail(document.getElementById("detail-task-id").value.trim());
  });

  document.getElementById("btn-stop-task").addEventListener("click", async () => {
    const taskId = document.getElementById("detail-task-id").value.trim();
    if (!taskId) return;
    await fetch(`/api/tasks/${taskId}/stop`, { method: "POST" });
    loadTaskDetail(taskId);
  });

  document.getElementById("refresh-tasks").addEventListener("click", loadTasks);

  // Load benchmarks
  async function loadBenchmarks() {
    const container = document.getElementById("benchmark-runs-list");
    container.innerHTML = "<p>Loading benchmark runs...</p>";
    try {
      const res = await fetch("/api/benchmarks");
      const runs = await res.json();
      if (!runs.length) {
        container.innerHTML = "<p>No benchmark reports found in reports/.</p>";
        return;
      }
      container.innerHTML = runs.map(run => `
        <div class="card-detail">
          <h3>${run.run_id} (${run.metadata.suite || "custom"})</h3>
          <p><strong>Timestamp:</strong> ${run.metadata.timestamp || "N/A"} | <strong>Seed:</strong> ${run.metadata.seed}</p>
          <pre>${JSON.stringify(run.aggregates, null, 2)}</pre>
        </div>
      `).join("");
    } catch (e) {
      container.innerHTML = `<p>Error loading benchmarks: ${e.message}</p>`;
    }
  }
  document.getElementById("refresh-benchmarks").addEventListener("click", loadBenchmarks);

  // Ollama health check
  async function checkOllamaHealth() {
    const card = document.getElementById("ollama-status-card");
    card.innerHTML = "<p>Probing Ollama instance at http://localhost:11434...</p>";
    try {
      const res = await fetch("/api/ollama/models");
      const health = await res.json();
      card.innerHTML = `
        <h3>Ollama Status: ${health.reachable ? "🟢 Connected" : "🔴 Unreachable"}</h3>
        <p><strong>Base URL:</strong> ${health.base_url}</p>
        <p><strong>Model:</strong> ${health.model} (${health.available ? "✅ Available" : "❌ Not found"})</p>
        <p><strong>Latency:</strong> ${health.latency_ms} ms</p>
        <p><strong>Message:</strong> ${health.message}</p>
        <p><strong>Installed Models:</strong> ${health.available_models ? health.available_models.join(", ") : "None"}</p>
      `;
    } catch (e) {
      card.innerHTML = `<p style="color:var(--danger)">Error: ${e.message}</p>`;
    }
  }
  document.getElementById("check-ollama-btn").addEventListener("click", checkOllamaHealth);

  // Initial load
  loadTasks();
});
