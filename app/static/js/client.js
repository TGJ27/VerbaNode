'use strict';

const WS_CLOSE_UNAUTHORIZED = 4401;
const WS_CLOSE_ORIGIN_REJECTED = 4403;
const WS_CLOSE_PROTOCOL_UNSUPPORTED = 4406;
const WS_CLOSE_HEARTBEAT_TIMEOUT = 4408;

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

function clearWebSocketTimers() {
  clearTimeout(appState.reconnectTimer);
  clearInterval(appState.heartbeatTimer);
  clearInterval(appState.heartbeatWatchdogTimer);
  appState.reconnectTimer = null;
  appState.heartbeatTimer = null;
  appState.heartbeatWatchdogTimer = null;
}

function resetToLogin(message = '') {
  sessionStorage.removeItem('verbanode_token');
  appState.token = '';
  appState.session = null;
  appState.connectionGeneration += 1;
  clearWebSocketTimers();
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

async function loadClientInfo() {
  const response = await fetch('/api/client-info', { method: 'GET', cache: 'no-store' });
  if (!response.ok) throw new Error(`Client compatibility check failed (${response.status})`);
  const info = await response.json();
  appState.clientInfo = info;
  appState.backendVersion = info.server?.version || appState.backendVersion;
  const apiVersion = Number(info.api?.version || 0);
  const wsVersion = Number(info.websocket?.protocol_version || 0);
  if (apiVersion && apiVersion !== CLIENT_API_VERSION) {
    throw new Error(`Dashboard API v${CLIENT_API_VERSION} is incompatible with server API v${apiVersion}.`);
  }
  if (wsVersion && wsVersion !== WEBSOCKET_PROTOCOL_VERSION) {
    throw new Error(`Dashboard WebSocket v${WEBSOCKET_PROTOCOL_VERSION} is incompatible with server WebSocket v${wsVersion}.`);
  }
  return info;
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

async function validateStoredSession(clearOnNetworkError = true) {
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
    if (clearOnNetworkError) resetToLogin('Could not validate the saved session. Enter the PIN again.');
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

function heartbeatIntervalMs() {
  return Math.max(5000, Number(appState.clientInfo?.websocket?.heartbeat_interval_seconds || 15) * 1000);
}

function heartbeatTimeoutMs() {
  const configured = Number(appState.clientInfo?.websocket?.heartbeat_timeout_seconds || 45) * 1000;
  return Math.max(heartbeatIntervalMs() * 2, configured);
}

function noteWebSocketActivity() {
  appState.lastWebSocketActivityAt = Date.now();
}

function startWebSocketHeartbeat(ws) {
  clearInterval(appState.heartbeatTimer);
  clearInterval(appState.heartbeatWatchdogTimer);
  noteWebSocketActivity();
  appState.heartbeatTimer = setInterval(() => {
    if (appState.ws !== ws || ws.readyState !== WebSocket.OPEN) return;
    wsCommand('heartbeat', {}, { quiet: true });
  }, heartbeatIntervalMs());
  appState.heartbeatWatchdogTimer = setInterval(() => {
    if (appState.ws !== ws || ws.readyState !== WebSocket.OPEN) return;
    if (Date.now() - appState.lastWebSocketActivityAt > heartbeatTimeoutMs()) {
      try { ws.close(WS_CLOSE_HEARTBEAT_TIMEOUT, 'heartbeat timeout'); } catch (_) {}
    }
  }, Math.min(5000, heartbeatIntervalMs()));
}

function reconnectDelayMs() {
  const attempt = Math.max(0, appState.reconnectAttempt);
  const base = Math.min(10000, 500 * (2 ** Math.min(attempt, 5)));
  const jitter = Math.floor(Math.random() * 250);
  return base + jitter;
}

function scheduleWebSocketReconnect(delayOverride = null) {
  if (!appState.token) return;
  clearTimeout(appState.reconnectTimer);
  const delay = delayOverride === null ? reconnectDelayMs() : Math.max(0, Number(delayOverride));
  appState.reconnectAttempt += 1;
  $('#connectionDot').classList.remove('online');
  $('#connectionLabel').textContent = 'Reconnecting…';
  appState.reconnectTimer = setTimeout(reconnectWebSocketAfterValidation, delay);
}

async function reconnectWebSocketAfterValidation() {
  if (!appState.token) return;
  const valid = await validateStoredSession(false);
  if (!appState.token) return;
  if (!valid) {
    scheduleWebSocketReconnect();
    return;
  }
  connectWebSocket();
}

async function connectWebSocket() {
  if (!appState.token) return;
  const generation = ++appState.connectionGeneration;
  clearTimeout(appState.reconnectTimer);
  clearWebSocketTimers();
  const previousWs = appState.ws;
  appState.ws = null;
  if (previousWs) { try { previousWs.close(); } catch (_) {} }
  let ticketPayload;
  try {
    ticketPayload = await api('/api/auth/ws-ticket', { method: 'POST' });
  } catch (error) {
    if (!appState.token || generation !== appState.connectionGeneration) return;
    scheduleWebSocketReconnect();
    return;
  }
  if (!appState.token || !ticketPayload?.ticket || generation !== appState.connectionGeneration) return;
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${location.host}/ws?ticket=${encodeURIComponent(ticketPayload.ticket)}`);
  appState.ws = ws;
  ws.onopen = () => {
    if (appState.ws !== ws) return;
    appState.reconnectAttempt = 0;
    $('#connectionDot').classList.add('online');
    $('#connectionLabel').textContent = 'Connected';
    startWebSocketHeartbeat(ws);
  };
  ws.onclose = event => {
    if (appState.ws !== ws) return;
    appState.ws = null;
    clearInterval(appState.heartbeatTimer);
    clearInterval(appState.heartbeatWatchdogTimer);
    appState.heartbeatTimer = null;
    appState.heartbeatWatchdogTimer = null;
    $('#connectionDot').classList.remove('online');
    if (!appState.token) {
      $('#connectionLabel').textContent = 'Disconnected';
      return;
    }
    if (event.code === WS_CLOSE_PROTOCOL_UNSUPPORTED) {
      $('#connectionLabel').textContent = 'Update required';
      toast('Dashboard and backend WebSocket versions do not match. Restart VerbaNode after updating all files.', 'error');
      return;
    }
    if (event.code === WS_CLOSE_ORIGIN_REJECTED) {
      $('#connectionLabel').textContent = 'Connection blocked';
      toast('The server rejected this browser WebSocket origin.', 'error');
      return;
    }
    if (event.code === WS_CLOSE_UNAUTHORIZED) {
      scheduleWebSocketReconnect(500);
      return;
    }
    scheduleWebSocketReconnect();
  };
  ws.onerror = () => { try { ws.close(); } catch (_) {} };
  ws.onmessage = event => {
    noteWebSocketActivity();
    try { handleEvent(JSON.parse(event.data)); } catch (error) { console.error(error); }
  };
}

function wsCommand(command, data = {}, options = {}) {
  if (!appState.ws || appState.ws.readyState !== WebSocket.OPEN) {
    if (!options.quiet) toast('Live connection is not ready.', 'error');
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

async function initializeClientTransport() {
  try {
    await loadClientInfo();
  } catch (error) {
    const status = $('#loginStatus');
    if (status) {
      status.textContent = error.message;
      status.classList.remove('hidden');
    }
  }
  if (appState.token) {
    const status = $('#loginStatus');
    status.textContent = 'Checking saved controller session…';
    status.classList.remove('hidden');
    await completeLogin(appState.token, true);
  }
}
