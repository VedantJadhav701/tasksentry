/**
 * ModelHealthPanel Component: Inspects Ollama connectivity, loaded models, and context allocations.
 */
class ModelHealthPanel {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
  }

  render(healthData) {
    if (!this.container) return;

    const isReachable = healthData.reachable === true;
    let modelsHtml = '<div style="display: flex; flex-direction: column; gap: 8px; margin-top: 10px;">';
    for (const m of (healthData.models_metadata || [])) {
      const isReasoning = m.lane === 'reasoning';
      modelsHtml += `
        <div style="background: rgba(255, 255, 255, 0.04); border: 0.5px solid var(--ios-glass-stroke-subtle); padding: 12px; border-radius: 12px; transition: all 0.2s var(--apple-spring);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <strong style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--text-primary);">${m.name}</strong>
            <span class="route-badge ${isReasoning ? 'route-reasoning' : 'route-routine'}">${m.lane}</span>
          </div>
          <div style="font-size: 0.75rem; color: var(--text-secondary);">
            Context Window: <strong>${m.context_window}</strong> | Role: ${m.recommended_for}
          </div>
        </div>
      `;
    }
    modelsHtml += '</div>';

    this.container.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255, 255, 255, 0.04); padding: 10px 14px; border-radius: 12px; border: 0.5px solid var(--ios-glass-stroke-subtle);">
        <span>Ollama Server (${healthData.base_url})</span>
        <span style="font-weight: 600; font-size: 0.8rem; color: ${isReachable ? 'var(--ios-green)' : 'var(--ios-red)'};">
          ${isReachable ? `● Online (${Math.round(healthData.latency_ms)}ms)` : '○ Unreachable'}
        </span>
      </div>
      ${modelsHtml}
    `;
  }
}
window.ModelHealthPanel = ModelHealthPanel;
