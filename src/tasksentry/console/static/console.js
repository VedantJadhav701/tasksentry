/**
 * Main Console Orchestrator: Tab switching, Model Health loading, and Playground evaluation.
 */
class ConsoleApp {
  constructor() {
    this.chatController = new ChatController();
    this.timeline = new RunTimeline('timeline-inspector-body');
    this.healthPanel = new ModelHealthPanel('model-health-container');

    this._bindTabs();
    this.loadRecentTasks();
    this.loadModelsHealth();
    this._bindPlayground();
    this._bindGlobalDropdownDismissal();
  }

  _bindGlobalDropdownDismissal() {
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.ios-dropdown')) {
        document.querySelectorAll('.ios-dropdown').forEach(d => d.classList.remove('open'));
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.ios-dropdown').forEach(d => d.classList.remove('open'));
      }
    });
  }

  _bindTabs() {
    const tabs = document.querySelectorAll('.nav-tab');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');

        const view = tab.getAttribute('data-view');
        this.switchView(view);
      });
    });

    document.getElementById('btn-new-task-sidebar')?.addEventListener('click', () => {
      this.switchView('chat');
      document.querySelector('[data-view="chat"]')?.classList.add('active');
      document.getElementById('chat-input-text')?.focus();
    });

    document.querySelectorAll('.prompt-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const prompt = chip.getAttribute('data-prompt');
        const inputArea = document.getElementById('chat-input-text');
        if (inputArea && prompt) {
          inputArea.value = prompt;
          inputArea.focus();
        }
      });
    });
  }

  switchView(view) {
    const chatContainer = document.getElementById('chat-view-container');
    const playgroundContainer = document.getElementById('playground-view-container');
    const healthContainer = document.getElementById('health-view-container');

    if (chatContainer) chatContainer.style.display = view === 'chat' ? 'flex' : 'none';
    if (playgroundContainer) playgroundContainer.style.display = view === 'playground' ? 'flex' : 'none';
    if (healthContainer) healthContainer.style.display = view === 'models' ? 'block' : 'none';

    if (view === 'models') {
      this.loadModelsHealth();
    }
  }

  async loadRecentTasks() {
    const listEl = document.getElementById('recent-tasks-list');
    if (!listEl) return;

    try {
      const res = await fetch('/api/chat/tasks?limit=15');
      const data = await res.json();
      const tasks = data.tasks || [];

      if (tasks.length === 0) {
        listEl.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem; padding: 8px;">No tasks yet.</div>';
        return;
      }

      let html = '';
      for (const t of tasks) {
        const badgeClass = `status-${t.status || 'created'}`;
        html += `
          <div class="task-item" data-task-id="${t.task_id}">
            <div class="task-item-header">
              <span class="task-item-id">${t.task_id}</span>
              <span class="status-badge ${badgeClass}">${t.status}</span>
            </div>
            <div class="task-item-goal">${t.goal}</div>
          </div>
        `;
      }
      listEl.innerHTML = html;

      // Click task to inspect
      listEl.querySelectorAll('.task-item').forEach(item => {
        item.addEventListener('click', () => {
          const tid = item.getAttribute('data-task-id');
          this.inspectTask(tid);
        });
      });
    } catch (e) {
      console.error('Error loading tasks', e);
    }
  }

  async inspectTask(taskId) {
    try {
      const res = await fetch(`/api/chat/tasks/${taskId}`);
      const data = await res.json();
      if (!res.ok) return;

      this.switchView('chat');
      document.querySelector('[data-view="chat"]')?.classList.add('active');

      this.chatController.currentTaskId = taskId;
      this.chatController.chatWindow.clear();
      this.chatController.chatWindow.addSystemNotice(`Loaded Historical Task: ${taskId}`, `Goal: ${data.goal}`);

      // Replay events
      for (const evt of (data.events || [])) {
        if (evt.type === 'assistant_message') {
          this.chatController.chatWindow.addAssistantMessage(evt.data.action);
        } else if (evt.type === 'tool_call_started') {
          this.chatController.chatWindow.addToolCall(evt.data.tool, evt.data.arguments);
        } else if (evt.type === 'tool_call_completed') {
          this.chatController.chatWindow.addToolCall(evt.data.tool, {}, evt.data.observation);
        }
      }

      if (data.receipt) {
        this.chatController.receiptPanel.update(data.receipt);
        this.chatController.budgetPanel.update(
          data.receipt.tokens || 0,
          60000,
          data.receipt.tool_calls || 0,
          15,
          data.receipt.wall_time_seconds || 0,
          data.receipt.cost_usd || 0
        );
      }
    } catch (e) {
      console.error('Inspect failed', e);
    }
  }

  async loadModelsHealth() {
    try {
      const res = await fetch('/api/chat/models');
      const data = await res.json();
      this.healthPanel.render(data);

      const models = data.available_models || [];
      if (models.length > 0) {
        // Select smart defaults:
        // Routine: exact qwen2.5:3b > llama3.2:1b (exact/prefix) > gemma2:2b > models[0]
        const routineDefault = models.find(m => m === 'qwen2.5:3b')
          || models.find(m => m.startsWith('llama3.2:1b'))
          || models.find(m => m.startsWith('gemma2:2b'))
          || models[0];

        // Reasoning: qwen3:4b-instruct-2507-q4_K_M > ornith:latest > qwen3 prefix > routineDefault
        const reasoningDefault = models.find(m => m.startsWith('qwen3:4b-instruct'))
          || models.find(m => m === 'ornith:latest')
          || models.find(m => m.startsWith('qwen3:'))
          || routineDefault;

        // Initialize iOS Popover Picker for Routine Lane
        this.setupIosDropdown(
          'dropdown-routine-model',
          'btn-routine-model',
          'val-routine-model',
          'menu-routine-model',
          'select-routine-model',
          models,
          routineDefault
        );

        // Initialize iOS Popover Picker for Reasoning Lane
        this.setupIosDropdown(
          'dropdown-reasoning-model',
          'btn-reasoning-model',
          'val-reasoning-model',
          'menu-reasoning-model',
          'select-reasoning-model',
          models,
          reasoningDefault
        );
      }
    } catch (e) {
      console.error('Health load error', e);
    }
  }

  setupIosDropdown(dropdownId, triggerBtnId, valueElId, menuElId, inputId, models, defaultModel) {
    const dropdown = document.getElementById(dropdownId);
    const triggerBtn = document.getElementById(triggerBtnId);
    const valueEl = document.getElementById(valueElId);
    const menuEl = document.getElementById(menuElId);
    const hiddenInput = document.getElementById(inputId);

    if (!dropdown || !triggerBtn || !valueEl || !menuEl || !hiddenInput) return;

    let selectedModel = models.includes(defaultModel) ? defaultModel : (models[0] || '');
    hiddenInput.value = selectedModel;
    valueEl.textContent = selectedModel;

    // Render scrollable options list with Apple checkmark
    menuEl.innerHTML = models.map(m => `
      <div class="ios-dropdown-item ${m === selectedModel ? 'selected' : ''}" data-value="${m}">
        <span class="item-name">${m}</span>
        <span class="item-check">✓</span>
      </div>
    `).join('');

    // Toggle menu
    triggerBtn.onclick = (e) => {
      e.stopPropagation();
      const isOpen = dropdown.classList.contains('open');
      document.querySelectorAll('.ios-dropdown').forEach(d => d.classList.remove('open'));
      if (!isOpen) {
        dropdown.classList.add('open');
      }
    };

    // Option selection
    menuEl.querySelectorAll('.ios-dropdown-item').forEach(item => {
      item.onclick = (e) => {
        e.stopPropagation();
        const val = item.getAttribute('data-value');
        if (!val) return;
        selectedModel = val;
        hiddenInput.value = val;
        valueEl.textContent = val;

        menuEl.querySelectorAll('.ios-dropdown-item').forEach(i => i.classList.remove('selected'));
        item.classList.add('selected');
        dropdown.classList.remove('open');
      };
    });
  }

  _bindPlayground() {
    const evalBtn = document.getElementById('btn-eval-playground');
    const promptInput = document.getElementById('playground-prompt-input');

    evalBtn?.addEventListener('click', async () => {
      const prompt = promptInput?.value.trim();
      if (!prompt) return;

      const resultBox = document.getElementById('playground-results-container');
      if (resultBox) {
        resultBox.innerHTML = '<div style="color: var(--text-secondary);">Evaluating prompt across lanes via semantic router...</div>';
      }

      try {
        const res = await fetch('/api/chat/playground/compare', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt, mock_mode: false })
        });
        const data = await res.json();
        this.renderPlaygroundResult(data);
      } catch (err) {
        if (resultBox) {
          resultBox.innerHTML = `<div style="color: var(--accent-rose);">Error: ${err}</div>`;
        }
      }
    });
  }

  renderPlaygroundResult(res) {
    const resultBox = document.getElementById('playground-results-container');
    if (!resultBox) return;

    const rLane = res.routine_lane || {};
    const reLane = res.reasoning_lane || {};
    const routed = res.routed_response || {};

    resultBox.innerHTML = `
      <div style="background: var(--bg-card); padding: 16px; border-radius: 8px; border: 1px solid var(--border-color); margin-bottom: 16px;">
        <div style="font-weight: 700; color: var(--accent-primary); font-size: 1rem; margin-bottom: 6px;">
          Dynamic Routing Decision: <span class="route-badge ${res.lane_selected === 'reasoning' ? 'route-reasoning' : 'route-routine'}">${res.lane_selected.toUpperCase()}</span>
        </div>
        <div style="color: var(--text-secondary); font-size: 0.88rem; line-height: 1.5;">
          Selected Model: <strong>${res.selected_model}</strong> | Rationale: ${res.reason}
        </div>
        <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 6px;">
          Signals: complexity=${res.signals.complexity}, stagnant_steps=${res.signals.stagnant_steps}, open_failures=${res.signals.open_failures}
        </div>
      </div>

      <div class="playground-grid">
        <div class="playground-lane-card">
          <div class="playground-lane-title">
            <span>Routine Lane (Fast)</span>
            <span class="route-badge route-routine">${rLane.model || 'routine'}</span>
          </div>
          <div style="font-size: 0.8rem; color: var(--text-secondary);">Latency: ${rLane.latency_ms || 0}ms</div>
          <pre style="background: var(--bg-main); padding: 10px; border-radius: 4px; font-size: 0.82rem; white-space: pre-wrap; flex: 1;">${rLane.content || rLane.error || 'N/A'}</pre>
        </div>

        <div class="playground-lane-card">
          <div class="playground-lane-title">
            <span>Reasoning Lane (Deep)</span>
            <span class="route-badge route-reasoning">${reLane.model || 'reasoning'}</span>
          </div>
          <div style="font-size: 0.8rem; color: var(--text-secondary);">Latency: ${reLane.latency_ms || 0}ms</div>
          <pre style="background: var(--bg-main); padding: 10px; border-radius: 4px; font-size: 0.82rem; white-space: pre-wrap; flex: 1;">${reLane.content || reLane.error || 'N/A'}</pre>
        </div>

        <div class="playground-lane-card" style="border-color: var(--accent-primary);">
          <div class="playground-lane-title">
            <span>Routed Output</span>
            <span class="route-badge" style="background: rgba(16, 185, 129, 0.2); color: var(--accent-primary);">${routed.model || 'routed'}</span>
          </div>
          <div style="font-size: 0.8rem; color: var(--text-secondary);">Latency: ${routed.latency_ms || 0}ms</div>
          <pre style="background: var(--bg-main); padding: 10px; border-radius: 4px; font-size: 0.82rem; white-space: pre-wrap; flex: 1;">${routed.content || 'N/A'}</pre>
        </div>
      </div>
    `;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.consoleApp = new ConsoleApp();
});
