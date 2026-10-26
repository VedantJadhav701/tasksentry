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
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; background: rgba(255, 255, 255, 0.04); border: 0.5px solid var(--ios-glass-stroke-subtle); padding: 7px 10px; border-radius: 8px;">
          <span>${c.criterion || c.id || 'Verifier gate'}</span>
          <span style="font-weight: 600; font-size: 0.74rem; padding: 2px 6px; border-radius: 9999px; ${isPassed ? 'background: rgba(48, 209, 88, 0.16); color: var(--ios-green);' : 'background: rgba(255, 159, 10, 0.16); color: var(--ios-orange);'}">
            ${isPassed ? '✓ PASSED' : 'PENDING'}
          </span>
        </div>
      `;
    }
    html += '</div>';

    if (loopMetrics) {
      html += `
        <div style="margin-top: 10px; padding-top: 8px; border-top: 0.5px solid var(--ios-glass-stroke-subtle); font-size: 0.78rem; color: var(--text-secondary);">
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
