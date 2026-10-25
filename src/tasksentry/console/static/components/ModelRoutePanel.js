/**
 * ModelRoutePanel Component: Visualizes semantic routing decisions, lane classifications, and rationale.
 */
class ModelRoutePanel {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
  }

  update(routeData) {
    if (!this.container) return;
    const isReasoning = routeData.lane === 'reasoning';
    const badgeClass = isReasoning ? 'route-reasoning' : 'route-routine';

    this.container.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <span class="route-badge ${badgeClass}">
          ${isReasoning ? '🧠' : '⚡'} ${routeData.lane.toUpperCase()}
        </span>
        <span style="font-family: var(--font-mono); font-size: 0.82rem; font-weight: 600; color: var(--text-primary);">
          ${routeData.selected_model}
        </span>
      </div>
      <div class="route-explanation">
        <strong>Rationale:</strong> ${routeData.reason}
      </div>
      <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 6px;">
        Fallback: ${routeData.fallback_model || 'None'}
      </div>
    `;
  }

  reset() {
    if (this.container) {
      this.container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem;">Awaiting step execution...</div>';
    }
  }
}
window.ModelRoutePanel = ModelRoutePanel;
