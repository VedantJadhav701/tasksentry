/**
 * Chat Controller: Manages live task submission, SSE streaming, and event dispatching.
 */
class ChatController {
  constructor() {
    this.chatWindow = new ChatWindow('chat-messages-container');
    this.routePanel = new ModelRoutePanel('route-inspector-body');
    this.budgetPanel = new BudgetPanel('budget-inspector-body');
    this.verifPanel = new VerificationPanel('verif-inspector-body');
    this.receiptPanel = new ReceiptPanel('receipt-inspector-body');
    this.currentTaskId = null;
    this.eventSource = null;

    this.activeBudget = { tokens: 0, maxTokens: 60000, toolCalls: 0, maxTools: 15, wallTime: 0, cost: 0 };
    this.criteria = [];

    this._bindEvents();
  }

  _bindEvents() {
    const sendBtn = document.getElementById('btn-send-task');
    const inputArea = document.getElementById('chat-input-text');

    sendBtn?.addEventListener('click', () => this.sendTask());
    inputArea?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendTask();
      }
    });
  }

  async sendTask() {
    const inputArea = document.getElementById('chat-input-text');
    const msg = inputArea?.value.trim();
    if (!msg) return;

    inputArea.value = '';
    this.chatWindow.addUserMessage(msg);

    const routineSel = document.getElementById('select-routine-model');
    const reasoningSel = document.getElementById('select-reasoning-model');
    const allowWritesCheck = document.getElementById('check-allow-writes');

    const payload = {
      message: msg,
      agent: 'semantic-router',
      routine_model: routineSel ? routineSel.value : 'qwen2.5:3b',
      reasoning_model: reasoningSel ? reasoningSel.value : 'qwen3:4b-instruct-2507-q4_K_M',
      allow_writes: allowWritesCheck ? allowWritesCheck.checked : false,
      budget: {
        max_tokens: 60000,
        max_tool_calls: 15,
        max_cost_usd: 0.50,
        max_wall_time_seconds: 300
      }
    };

    try {
      const res = await fetch('/api/chat/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        this.chatWindow.addSystemNotice('Submission Failed', data.detail || 'Error creating task.');
        return;
      }

      this.currentTaskId = data.task_id;
      this.routePanel.reset();
      this.budgetPanel.reset();
      this.verifPanel.reset();
      this.receiptPanel.reset();

      this.activeBudget = { tokens: 0, maxTokens: 60000, toolCalls: 0, maxTools: 15, wallTime: 0, cost: 0 };
      this.criteria = [];

      this.chatWindow.addSystemNotice(`Task Initiated: ${data.task_id}`, `Goal: ${data.goal}`);
      this.startStreaming(data.task_id);

      if (window.consoleApp) {
        window.consoleApp.loadRecentTasks();
      }
    } catch (err) {
      this.chatWindow.addSystemNotice('Network Error', String(err));
    }
  }

  startStreaming(taskId) {
    if (this.eventSource) {
      this.eventSource.close();
    }

    const t0 = Date.now();
    this.eventSource = new EventSource(`/api/chat/tasks/${taskId}/stream`);

    this.eventSource.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data);
        this._handleStreamEvent(payload, t0);
      } catch (err) {
        console.error('SSE JSON error', err, e.data);
      }
    };

    this.eventSource.onerror = () => {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }
    };
  }

  _handleStreamEvent(event, t0) {
    const type = event.type;
    const data = event.data || {};

    if (type === 'stream_end') {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }
      return;
    }

    // Update active timeline component
    if (window.consoleApp && window.consoleApp.timeline) {
      window.consoleApp.timeline.addEvent(event);
    }

    switch (type) {
      case 'model_selected':
        this.routePanel.update(data);
        break;

      case 'assistant_token':
        this.chatWindow.appendToken(data.step, data.token);
        break;

      case 'assistant_message':
        this.chatWindow.addAssistantMessage(data.action);
        break;

      case 'tool_call_started':
        this.activeBudget.toolCalls += 1;
        this.chatWindow.addToolCall(data.tool, data.arguments);
        this.budgetPanel.update(
          this.activeBudget.tokens,
          this.activeBudget.maxTokens,
          this.activeBudget.toolCalls,
          this.activeBudget.maxTools,
          (Date.now() - t0) / 1000,
          this.activeBudget.cost
        );
        break;

      case 'tool_call_completed':
        this.chatWindow.addToolCall(data.tool, {}, data.observation, false);
        break;

      case 'tool_call_failed':
        this.chatWindow.addToolCall(data.tool, {}, data.error, true);
        break;

      case 'approval_required':
        this.chatWindow.addApprovalPrompt(
          data.approval_id,
          event.task_id,
          data.tool,
          data.arguments,
          data.risk,
          data.reason,
          (apprId, tId) => this.approveAction(apprId, tId),
          (apprId, tId) => this.rejectAction(apprId, tId)
        );
        break;

      case 'verification_started':
        this.criteria.push({ criterion: data.criterion, passed: false });
        this.verifPanel.update(this.criteria);
        break;

      case 'verification_passed':
        for (const c of this.criteria) {
          if (c.criterion === data.criterion) c.passed = true;
        }
        this.verifPanel.update(this.criteria);
        break;

      case 'task_completed':
      case 'task_stopped':
        if (data.receipt) {
          this.activeBudget.tokens = data.receipt.tokens || this.activeBudget.tokens;
          this.activeBudget.cost = data.receipt.cost_usd || 0;
          this.budgetPanel.update(
            this.activeBudget.tokens,
            this.activeBudget.maxTokens,
            this.activeBudget.toolCalls,
            this.activeBudget.maxTools,
            data.receipt.wall_time_seconds || ((Date.now() - t0) / 1000),
            this.activeBudget.cost
          );
          this.receiptPanel.update(data.receipt);
        }
        if (window.consoleApp) {
          window.consoleApp.loadRecentTasks();
        }
        break;
    }
  }

  async approveAction(approvalId, taskId) {
    try {
      await fetch(`/api/chat/tasks/${taskId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approval_id: approvalId })
      });
    } catch (e) {
      console.error('Approve failed', e);
    }
  }

  async rejectAction(approvalId, taskId) {
    try {
      await fetch(`/api/chat/tasks/${taskId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approval_id: approvalId, reason: 'Rejected from chat UI' })
      });
    } catch (e) {
      console.error('Reject failed', e);
    }
  }
}
window.ChatController = ChatController;
