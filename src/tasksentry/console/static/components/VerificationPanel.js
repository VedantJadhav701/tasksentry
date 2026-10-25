/**
 * VerificationPanel Component: Renders success criteria gates, verifier checks, and loop controllers.
 */
class VerificationPanel {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
  }

  update(criteriaList, loopMetrics = null) {
    if (!this.container) return;

    let html = '<div style="display: flex; flex-direction: column; gap: 6px;">';
    for (const c of (criteriaList || [])) {
      const isPassed = c.passed === true;
      html += `
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; background: var(--bg-card); padding: 6px 10px; border-radius: 4px;">
          <span>${c.criterion || c.id || 'Verifier gate'}</span>
          <span style="font-weight: 600; color: ${isPassed ? 'var(--accent-primary)' : 'var(--accent-amber)'};">
            ${isPassed ? '✓ PASSED' : 'PENDING'}
          </span>
        </div>
      `;
    }
    html += '</div>';

    if (loopMetrics) {
      html += `
        <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border-color); font-size: 0.78rem; color: var(--text-secondary);">
          <div>WindowGain: <strong>${loopMetrics.window_gain || '+0.0'}</strong></div>
          <div>Blocked Duplicates: <strong>${loopMetrics.blocked_duplicates || 0}</strong></div>
        </div>
      `;
    }

    this.container.innerHTML = html;
  }

  reset() {
    if (this.container) {
      this.container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem;">No active verifiers.</div>';
    }
  }
}
window.VerificationPanel = VerificationPanel;
