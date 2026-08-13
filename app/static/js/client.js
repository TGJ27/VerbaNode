'use strict';

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (appState.token) headers.set('X-Session-Token', appState.token);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    resetToLogin('Your controller session ended.');
    throw new Error('Controller session ended');
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    let payload = null;
    try {
      payload = await response.json();
      detail = payload.error?.message || payload.detail || payload.message || detail;
    } catch (_) {}
    const error = new Error(detail);
    error.status = response.status;
    error.path = path;
    error.code = payload?.error?.code || null;
    error.requestId = payload?.error?.request_id || response.headers.get('X-Request-ID') || null;
    error.details = payload?.error?.details || null;
    throw error;
  }
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return response.json();
  return response;
}

function resetToLogin(message = '') {
  sessionStorage.removeItem('verbanode_token');
  appState.token = '';
  if (appState.ws) { try { appState.ws.close(); } catch (_) {} }
  try { appState.browserPttStream?.getTracks().forEach(track => track.stop()); } catch (_) {}
  appState.browserPttStream = null;
  appState.ws = null;
  $('#appShell').classList.add('hidden');
  $('#loginView').classList.remove('hidden');
  if (message) {
    $('#loginStatus').textContent = message;
    $('#loginStatus').classList.remove('hidden');
  }
}

async function login(pin, clientName) {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pin, client_name: clientName, client_type: 'web', client_version: FRONTEND_VERSION, api_version: CLIENT_API_VERSION }),
  });
  let payload = {};
  try { payload = await response.json(); } catch (_) {}
  if (response.status === 401) {
    const retry = Number(payload.retry_after_seconds || 0);
    throw new Error(retry ? `Incorrect PIN. Try again in ${retry}s.` : 'Incorrect PIN');
  }
  if (response.status === 429) {
    const retry = Number(payload.retry_after_seconds || 1);
    throw new Error(`Too many PIN attempts. Try again in ${retry}s.`);
  }
  if (!response.ok) throw new Error(payload.error?.message || payload.detail || payload.message || 'Login failed');
  if (!payload.token) throw new Error('Login failed');
  appState.session = payload.session || null;
  appState.backendVersion = payload.server_version || appState.backendVersion;
  await completeLogin(payload.token);
  if (payload.takeover) toast(`Control transferred from ${payload.previous_client || 'the previous device'}.`);
}

async function validateStoredSession() {
  if (!appState.token) return false;
  try {
    const response = await fetch('/api/session', {
      method: 'GET',
      cache: 'no-store',
      headers: { 'X-Session-Token': appState.token },
    });
    if (response.status === 401) {
      resetToLogin('Your previous session expired. Enter the PIN again.');
      return false;
    }
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const payload = await response.json();
    appState.session = payload.session || null;
    appState.backendVersion = payload.server_version || appState.backendVersion;
    return true;
  } catch (error) {
    resetToLogin('Could not validate the saved session. Enter the PIN again.');
    return false;
  }
}

async function completeLogin(token, validateFirst = false) {
  appState.token = token;
  sessionStorage.setItem('verbanode_token', token);
  if (validateFirst && !(await validateStoredSession())) return;
  $('#loginView').classList.add('hidden');
  $('#appShell').classList.remove('hidden');
  $('#loginStatus').classList.add('hidden');
  connectWebSocket();
  try {
    await loadBootstrap();
  } catch (error) {
    toast(error.message, 'error');
    resetToLogin('Could not load application data.');
  }
}

async function reconnectWebSocketAfterValidation() {
  if (!appState.token) return;
  if (!(await validateStoredSession())) return;
  connectWebSocket();
}

async function connectWebSocket() {
  if (!appState.token) return;
  if (appState.ws) { try { appState.ws.close(); } catch (_) {} }
  let ticketPayload;
  try {
    ticketPayload = await api('/api/auth/ws-ticket', { method: 'POST' });
  } catch (error) {
    if (!appState.token) return;
    $('#connectionDot').classList.remove('online');
    $('#connectionLabel').textContent = 'Reconnecting…';
    clearTimeout(appState.reconnectTimer);
    appState.reconnectTimer = setTimeout(reconnectWebSocketAfterValidation, 1500);
    return;
  }
  if (!appState.token || !ticketPayload?.ticket) return;
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${location.host}/ws?ticket=${encodeURIComponent(ticketPayload.ticket)}`);
  appState.ws = ws;
  ws.onopen = () => {
    $('#connectionDot').classList.add('online');
    $('#connectionLabel').textContent = 'Connected';
  };
  ws.onclose = event => {
    $('#connectionDot').classList.remove('online');
    if (!appState.token) {
      $('#connectionLabel').textContent = 'Disconnected';
      return;
    }
    if (event.code === 4401) {
      $('#connectionLabel').textContent = 'Reconnecting…';
      clearTimeout(appState.reconnectTimer);
      appState.reconnectTimer = setTimeout(reconnectWebSocketAfterValidation, 500);
      return;
    }
    $('#connectionLabel').textContent = 'Reconnecting…';
    clearTimeout(appState.reconnectTimer);
    appState.reconnectTimer = setTimeout(reconnectWebSocketAfterValidation, 1500);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = event => {
    try { handleEvent(JSON.parse(event.data)); } catch (error) { console.error(error); }
  };
}

function wsCommand(command, data = {}) {
  if (!appState.ws || appState.ws.readyState !== WebSocket.OPEN) {
    toast('Live connection is not ready.', 'error');
    return false;
  }
  const requestId = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`);
  appState.ws.send(JSON.stringify({
    protocol: WEBSOCKET_PROTOCOL_VERSION,
    type: `command.${command}`,
    request_id: requestId,
    data,
  }));
  return true;
}


