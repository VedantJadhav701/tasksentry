/**
 * ReceiptPanel Component: Presents task receipt and allows instant JSON export.
 */
class ReceiptPanel {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.currentReceipt = null;
  }

  update(receipt) {
    this.currentReceipt = receipt;
    if (!this.container) return;

    this.container.innerHTML = `
      <div style="font-size: 0.82rem; color: var(--text-secondary); line-height: 1.5;">
        <div>Task ID: <strong style="font-family: var(--font-mono); color: var(--text-primary);">${receipt.task_id}</strong></div>
        <div>Status: <strong style="color: ${receipt.success ? 'var(--ios-green)' : 'var(--ios-red)'};">${receipt.status}</strong></div>
        <div>Total Tokens: <strong>${(receipt.tokens || 0).toLocaleString()}</strong></div>
        <div>Wall Time: <strong>${(receipt.wall_time_seconds || 0).toFixed(2)}s</strong></div>
      </div>
      <button class="btn-download-receipt" id="btn-dl-receipt">
        ⬇ Download Task Receipt (JSON)
      </button>
    `;

    document.getElementById('btn-dl-receipt')?.addEventListener('click', () => {
      this.downloadJson();
    });
  }

  downloadJson() {
    if (!this.currentReceipt) return;
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(this.currentReceipt, null, 2));
    const dlAnchor = document.createElement('a');
    dlAnchor.setAttribute('href', dataStr);
    dlAnchor.setAttribute('download', `${this.currentReceipt.task_id}_receipt.json`);
    document.body.appendChild(dlAnchor);
    dlAnchor.click();
    dlAnchor.remove();
  }

  reset() {
    this.currentReceipt = null;
    if (this.container) {
      this.container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem;">Receipt generated upon task completion.</div>';
    }
  }
}
window.ReceiptPanel = ReceiptPanel;
