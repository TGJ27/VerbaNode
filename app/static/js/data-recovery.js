'use strict';

function formatByteCount(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let amount = bytes;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount >= 10 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

function renderBackupStatus(payload) {
  const node = $('#backupStatus');
  if (!node) return;
  const snapshots = payload?.recovery_backups || [];
  const latest = snapshots[0];
  const latestText = latest
    ? `${escapeHtml(latest.name)} · ${formatByteCount(latest.size_bytes)}`
    : 'No automatic recovery snapshots yet';
  node.innerHTML = `
    <div><small>Database schema</small><strong>v${escapeHtml(payload?.schema_version ?? '?')} / supported v${escapeHtml(payload?.current_schema_version ?? '?')}</strong></div>
    <div><small>Backup format</small><strong>v${escapeHtml(payload?.format_version ?? '?')}</strong></div>
    <div><small>Recovery snapshots</small><strong>${snapshots.length}</strong><span>${latestText}</span></div>`;
}

async function loadBackupStatus() {
  if (!appState.token) return null;
  const payload = await api('/api/backup/status');
  renderBackupStatus(payload);
  return payload;
}

function setRestoreStatus(message = '', kind = '') {
  const node = $('#restoreStatus');
  if (!node) return;
  node.textContent = message;
  node.dataset.kind = kind;
}

function bindDataRecoveryControls() {
  const backupButton = $('#backupDownloadBtn');
  const restoreInput = $('#restoreFileInput');
  if (backupButton) {
    backupButton.onclick = event => {
      event.preventDefault();
      downloadAuthenticated('/api/backup', 'verbanode-backup.zip');
    };
  }
  if (restoreInput) {
    restoreInput.onchange = async event => {
      const file = event.target.files?.[0];
      if (!file) return;
      if (!confirm('Restore this backup and replace the current database? VerbaNode creates a safety snapshot first.')) {
        event.target.value = '';
        return;
      }
      const body = new FormData();
      body.append('file', file);
      event.target.disabled = true;
      setRestoreStatus('Validating backup and creating a safety snapshot…', 'working');
      try {
        const result = await api('/api/restore', { method: 'POST', body });
        setRestoreStatus(`Restore complete. Safety snapshot: ${result.safety_backup || 'created'}. Reloading…`, 'success');
        toast('Backup restored safely. Reloading…', 'success');
        setTimeout(() => location.reload(), 1000);
      } catch (error) {
        const suffix = error.requestId ? ` Request ID: ${error.requestId}` : '';
        setRestoreStatus(`${error.message}${suffix}`, 'error');
        toast(error.message, 'error');
      } finally {
        event.target.disabled = false;
        event.target.value = '';
        loadBackupStatus().catch(() => {});
      }
    };
  }
}
