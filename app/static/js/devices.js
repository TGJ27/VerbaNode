'use strict';

let devicePairingPollTimer = null;
let devicePairingObjectUrl = null;

function clearDevicePairingUi() {
  clearInterval(devicePairingPollTimer);
  devicePairingPollTimer = null;
  if (devicePairingObjectUrl) URL.revokeObjectURL(devicePairingObjectUrl);
  devicePairingObjectUrl = null;
  appState.devicePairingId = null;
  $('#devicePairingBox')?.classList.add('hidden');
  const qr = $('#devicePairingQr');
  if (qr) qr.removeAttribute('src');
}

function deviceMetadataLabel(device) {
  const meta = device.metadata || {};
  return [device.device_type, meta.platform, meta.device_version].filter(Boolean).join(' · ') || 'trusted controller';
}

async function loadTrustedDevices() {
  const [devicePayload, discovery] = await Promise.all([
    api('/api/devices'),
    api('/api/discovery/status').catch(() => null),
  ]);
  const devices = devicePayload.devices || [];
  const list = $('#trustedDevicesList');
  if (list) {
    list.innerHTML = devices.length ? devices.map(device => `
      <article class="trusted-device-row ${device.trusted ? '' : 'revoked'}" data-device-id="${escapeHtml(device.device_id)}">
        <div class="trusted-device-icon">${device.device_type === 'mobile' ? '▣' : '◇'}</div>
        <div class="trusted-device-copy">
          <div><strong>${escapeHtml(device.name)}</strong>${device.active_controller ? '<span class="badge success">Active controller</span>' : ''}${!device.trusted ? '<span class="badge">Revoked</span>' : ''}</div>
          <small>${escapeHtml(deviceMetadataLabel(device))}</small>
          <small>Last seen: ${escapeHtml(device.last_seen_at || 'Never')} · Paired: ${escapeHtml(device.created_at || '')}</small>
        </div>
        <div class="trusted-device-actions">
          ${device.trusted ? `<button class="btn ghost compact" data-device-rename="${escapeHtml(device.device_id)}">Rename</button><button class="btn danger-outline compact" data-device-revoke="${escapeHtml(device.device_id)}">Revoke</button>` : `<button class="btn danger-outline compact" data-device-delete="${escapeHtml(device.device_id)}">Delete</button>`}
        </div>
      </article>`).join('') : '<div class="empty-state compact">No trusted devices yet.</div>';
  }
  const status = $('#deviceDiscoveryStatus');
  if (status) {
    if (!discovery) status.textContent = 'Discovery status unavailable.';
    else if (discovery.enabled) status.innerHTML = `<strong>mDNS active</strong><br>${escapeHtml(discovery.service_name || discovery.service_type)} · port ${Number(discovery.port || 0)}`;
    else status.innerHTML = '<strong>mDNS not active</strong><br>Manual address connection still works.';
  }
}

async function fetchPairingQr(pairingId) {
  const response = await api(`/api/devices/pairing/${encodeURIComponent(pairingId)}/qr`);
  const blob = await response.blob();
  if (devicePairingObjectUrl) URL.revokeObjectURL(devicePairingObjectUrl);
  devicePairingObjectUrl = URL.createObjectURL(blob);
  $('#devicePairingQr').src = devicePairingObjectUrl;
}

async function pollDevicePairing() {
  if (!appState.devicePairingId) return;
  try {
    const status = await api(`/api/devices/pairing/${encodeURIComponent(appState.devicePairingId)}`);
    const node = $('#devicePairingStatus');
    if (node) node.textContent = status.claimed ? 'Paired successfully.' : `Expires in ${status.expires_in_seconds}s`;
    if (status.claimed) {
      clearInterval(devicePairingPollTimer);
      devicePairingPollTimer = null;
      toast('Android device paired successfully.');
      await loadTrustedDevices();
      setTimeout(clearDevicePairingUi, 1200);
    } else if (Number(status.expires_in_seconds || 0) <= 0) {
      clearDevicePairingUi();
      toast('Pairing code expired.', 'error');
    }
  } catch (error) {
    if (error.status === 404) clearDevicePairingUi();
  }
}

async function startDevicePairing() {
  clearDevicePairingUi();
  const payload = await api('/api/devices/pairing/start', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  appState.devicePairingId = payload.pairing_id;
  $('#devicePairingBox').classList.remove('hidden');
  $('#devicePairingCode').textContent = `Code: ${payload.short_code}`;
  $('#devicePairingStatus').textContent = `Expires in ${payload.expires_in_seconds}s · ${payload.server_url}`;
  await fetchPairingQr(payload.pairing_id);
  devicePairingPollTimer = setInterval(pollDevicePairing, 1500);
}

async function cancelDevicePairing() {
  const pairingId = appState.devicePairingId;
  clearDevicePairingUi();
  if (pairingId) await api(`/api/devices/pairing/${encodeURIComponent(pairingId)}`, { method: 'DELETE' }).catch(() => {});
}

document.addEventListener('click', async event => {
  const target = event.target.closest('[data-device-rename],[data-device-revoke],[data-device-delete]');
  if (!target) return;
  try {
    if (target.dataset.deviceRename) {
      const current = target.closest('.trusted-device-row')?.querySelector('strong')?.textContent || '';
      const name = prompt('Device name', current);
      if (!name?.trim()) return;
      await api(`/api/devices/${encodeURIComponent(target.dataset.deviceRename)}`, { method: 'PATCH', body: JSON.stringify({ name: name.trim() }) });
    } else if (target.dataset.deviceRevoke) {
      if (!confirm('Revoke this device? It will need to be paired again.')) return;
      await api(`/api/devices/${encodeURIComponent(target.dataset.deviceRevoke)}/revoke`, { method: 'POST' });
    } else if (target.dataset.deviceDelete) {
      if (!confirm('Delete this revoked device record?')) return;
      await api(`/api/devices/${encodeURIComponent(target.dataset.deviceDelete)}`, { method: 'DELETE' });
    }
    await loadTrustedDevices();
  } catch (error) { toast(error.message, 'error'); }
});

document.addEventListener('DOMContentLoaded', () => {
  $('#startDevicePairingBtn')?.addEventListener('click', () => startDevicePairing().catch(error => toast(error.message, 'error')));
  $('#cancelDevicePairingBtn')?.addEventListener('click', () => cancelDevicePairing().catch(error => toast(error.message, 'error')));
  $('#refreshDevicesBtn')?.addEventListener('click', () => loadTrustedDevices().catch(error => toast(error.message, 'error')));
});
