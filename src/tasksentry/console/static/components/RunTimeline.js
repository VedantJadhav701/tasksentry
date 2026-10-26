/**
 * RunTimeline Component: Displays sequenced execution events, planner milestones, and recovery actions.
 */
class RunTimeline {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
  }

  clear() {
    if (this.container) {
      this.container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem;">No events recorded.</div>';
    }
  }

  addEvent(event) {
    if (!this.container) return;
    if (this.container.innerHTML.includes('No events recorded.')) {
      this.container.innerHTML = '';
    }

    const item = document.createElement('div');
    item.style.cssText = 'border-left: 2px solid var(--ios-blue); background: rgba(255, 255, 255, 0.03); padding: 8px 10px; margin-bottom: 8px; border-radius: 6px; font-size: 0.8rem;';
    
    const timeStr = new Date(event.timestamp * 1000).toLocaleTimeString();
    item.innerHTML = `
      <div style="display: flex; justify-content: space-between; color: var(--text-tertiary); font-size: 0.72rem; font-weight: 500;">
        <span style="color: var(--ios-blue); font-weight: 600;">${event.type}</span>
        <span>${timeStr}</span>
      </div>
      <div style="color: var(--text-secondary); margin-top: 4px; font-size: 0.78rem; word-break: break-all;">
        ${JSON.stringify(event.data || {})}
      </div>
    `;
    this.container.appendChild(item);
  }
}
window.RunTimeline = RunTimeline;
