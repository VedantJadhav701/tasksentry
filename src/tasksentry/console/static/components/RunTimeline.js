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
    item.style.cssText = 'border-left: 2px solid var(--border-highlight); padding-left: 10px; margin-bottom: 8px; font-size: 0.8rem;';
    
    const timeStr = new Date(event.timestamp * 1000).toLocaleTimeString();
    item.innerHTML = `
      <div style="display: flex; justify-content: space-between; color: var(--text-muted); font-size: 0.72rem;">
        <span>${event.type}</span>
        <span>${timeStr}</span>
      </div>
      <div style="color: var(--text-secondary); margin-top: 2px;">
        ${JSON.stringify(event.data || {})}
      </div>
    `;
    this.container.appendChild(item);
  }
}
window.RunTimeline = RunTimeline;
