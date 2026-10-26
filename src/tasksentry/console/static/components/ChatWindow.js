/**
 * ChatWindow Component: Manages chat message streams, tool cards, and approval dialogs.
 */
class ChatWindow {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
  }

  clear() {
    if (this.container) {
      this.container.innerHTML = '';
    }
  }

  addUserMessage(text) {
    const card = document.createElement('div');
    card.className = 'message-card message-user';
    card.innerHTML = `<div class="message-bubble">${this._escape(text)}</div>`;
    this.container.appendChild(card);
    this.scrollToBottom();
  }

  addSystemNotice(title, detail) {
    const card = document.createElement('div');
    card.className = 'message-card message-agent';
    card.innerHTML = `
      <div class="message-bubble" style="border-left: 3px solid var(--ios-blue);">
        <div style="font-weight: 600; color: var(--ios-blue); margin-bottom: 4px;">${this._escape(title)}</div>
        <div style="color: var(--text-secondary); font-size: 0.85rem;">${this._escape(detail)}</div>
      </div>
    `;
    this.container.appendChild(card);
    this.scrollToBottom();
  }

  addAssistantMessage(action) {
    const card = document.createElement('div');
    card.className = 'message-card message-agent';
    
    let contentHtml = '';
    if (action.type === 'complete_task') {
      contentHtml = `
        <div style="font-weight: 700; color: var(--ios-green); margin-bottom: 6px;">✓ Task Completion Declared</div>
        <div>${this._escape(action.answer || 'Goal satisfied and verified.')}</div>
      `;
    } else {
      contentHtml = `<div>${this._escape(JSON.stringify(action))}</div>`;
    }

    card.innerHTML = `<div class="message-bubble">${contentHtml}</div>`;
    this.container.appendChild(card);
    this.scrollToBottom();
  }

  appendToken(step, token) {
    let tokenHolder = document.getElementById(`streaming-tokens-${step}`);
    if (!tokenHolder) {
      const card = document.createElement('div');
      card.className = 'message-card message-agent';
      card.innerHTML = `
        <div class="message-bubble" style="font-style: italic; color: var(--text-secondary);">
          <span style="font-size: 0.75rem; text-transform: uppercase; color: var(--ios-purple); display: block; margin-bottom: 4px; font-weight: 600;">Step ${step} Reasoning Stream</span>
          <span id="streaming-tokens-${step}"></span>
        </div>
      `;
      this.container.appendChild(card);
      tokenHolder = document.getElementById(`streaming-tokens-${step}`);
    }
    if (tokenHolder) {
      tokenHolder.innerText += token;
    }
    this.scrollToBottom();
  }

  addToolCall(toolName, args, observation = null, isError = false) {
    const card = document.createElement('div');
    card.className = 'tool-card';
    card.innerHTML = `
      <div class="tool-card-header">
        <span>⚡ Tool Invocation: ${this._escape(toolName)}</span>
        <span style="font-size: 0.7rem; color: ${isError ? 'var(--ios-red)' : 'var(--text-secondary)'};">
          ${observation ? (isError ? 'FAILED' : 'SUCCESS') : 'RUNNING...'}
        </span>
      </div>
      <div class="tool-args">args: ${this._escape(JSON.stringify(args, null, 2))}</div>
      ${observation ? `<div style="margin-top: 6px; color: ${isError ? 'var(--ios-red)' : 'var(--ios-green)'};">output: ${this._escape(observation)}</div>` : ''}
    `;
    this.container.appendChild(card);
    this.scrollToBottom();
  }

  addApprovalPrompt(approvalId, taskId, tool, args, risk, reason, onApprove, onReject) {
    const card = document.createElement('div');
    card.className = 'approval-card';
    card.id = `approval-card-${approvalId}`;
    card.innerHTML = `
      <div class="approval-header">
        ⚠️ Human Approval Required (${this._escape(risk)})
      </div>
      <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 6px;">
        Agent wants to execute <strong>${this._escape(tool)}</strong>: ${this._escape(reason)}
      </div>
      <pre style="background: rgba(0, 0, 0, 0.4); border: 0.5px solid var(--ios-glass-stroke); border-radius: 8px; padding: 10px; font-size: 0.78rem; overflow-x: auto;">${this._escape(JSON.stringify(args, null, 2))}</pre>
      <div class="approval-actions" id="actions-${approvalId}">
        <button class="btn-approve" id="btn-appr-${approvalId}">Approve & Continue</button>
        <button class="btn-reject" id="btn-rej-${approvalId}">Reject Action</button>
      </div>
    `;
    this.container.appendChild(card);

    document.getElementById(`btn-appr-${approvalId}`)?.addEventListener('click', () => {
      document.getElementById(`actions-${approvalId}`).innerHTML = '<span style="color: var(--ios-green); font-weight: 600;">✓ Approved</span>';
      onApprove(approvalId, taskId);
    });

    document.getElementById(`btn-rej-${approvalId}`)?.addEventListener('click', () => {
      document.getElementById(`actions-${approvalId}`).innerHTML = '<span style="color: var(--ios-red); font-weight: 600;">✗ Rejected</span>';
      onReject(approvalId, taskId);
    });

    this.scrollToBottom();
  }

  scrollToBottom() {
    if (this.container) {
      this.container.scrollTop = this.container.scrollHeight;
    }
  }

  _escape(str) {
    if (typeof str !== 'string') return String(str);
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }
}
window.ChatWindow = ChatWindow;
