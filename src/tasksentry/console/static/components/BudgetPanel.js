/**
 * BudgetPanel Component: Displays real-time burn-down meters for tokens, tool calls, and budget limits.
 */
class BudgetPanel {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
  }

  update(tokens, maxTokens, toolCalls, maxToolCalls, wallTime, costUsd) {
    if (!this.container) return;

    const tokenPct = maxTokens ? Math.min(100, Math.round((tokens / maxTokens) * 100)) : 0;
    const toolPct = maxToolCalls ? Math.min(100, Math.round((toolCalls / maxToolCalls) * 100)) : 0;

    this.container.innerHTML = `
      <div class="progress-container">
        <div class="progress-label">
          <span>Tokens</span>
          <span>${tokens.toLocaleString()} / ${maxTokens ? maxTokens.toLocaleString() : '∞'} (${tokenPct}%)</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" style="width: ${tokenPct}%; ${tokenPct > 80 ? 'background-color: var(--accent-rose);' : ''}"></div>
        </div>
      </div>

      <div class="progress-container" style="margin-top: 10px;">
        <div class="progress-label">
          <span>Tool Calls</span>
          <span>${toolCalls} / ${maxToolCalls || '∞'} (${toolPct}%)</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" style="width: ${toolPct}%; background-color: var(--accent-blue);"></div>
        </div>
      </div>

      <div style="display: flex; justify-content: space-between; margin-top: 12px; font-size: 0.78rem; color: var(--text-secondary);">
        <span>Wall Time: <strong>${Math.round(wallTime)}s</strong></span>
        <span>Cost: <strong>$${(costUsd || 0).toFixed(4)}</strong></span>
      </div>
    `;
  }

  reset() {
    if (this.container) {
      this.container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem;">Budget tracking idle...</div>';
    }
  }
}
window.BudgetPanel = BudgetPanel;
