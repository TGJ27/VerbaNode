'use strict';

const FRONTEND_VERSION = '0.7.0';
const DIAGNOSTICS_MIN_BACKEND_VERSION = '0.5.2';

const appState = {
  token: sessionStorage.getItem('verbanode_token') || '',
  ws: null,
  reconnectTimer: null,
  data: null,
  agents: [],
  information: [],
  plugins: { plugins: [], summary: {} },
  scripts: [],
  queue: [],
  models: [],
  kokoroVoices: [],
  edgeVoices: { voices: [], source: 'built-in-fallback', error: null },
  audioDevices: { inputs: [], outputs: [], recommended_input: null, recommended_output: null },
  version: FRONTEND_VERSION,
  backendVersion: null,
  features: {},
  settingsPanel: localStorage.getItem('verbanode_settings_panel') || 'conversation',
  activeAgent: null,
  conversation: null,
  conversations: [],
  messages: [],
  mode: 'idle',
  pipeline: { state: 'idle', latency_ms: {}, counters: {} },
  diagnostics: null,
  queueState: 'paused',
  streaming: new Map(),
  pttToggleActive: false,
  holdPttActive: false,
  browserPttHeld: false,
  browserPttStarting: false,
  browserPttActive: false,
  browserPttStream: null,
  browserPttContext: null,
  browserPttSource: null,
  browserPttProcessor: null,
  browserPttGain: null,
  browserPttChunks: [],
  browserPttSampleRate: 0,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const UI_TEXT_SIZE_KEY = 'verbanode_ui_text_size';
const UI_TEXT_SIZES = new Set(['small', 'medium', 'large']);
const EXPLORER_VIEW_MODES = new Set(['cards', 'list', 'details']);

function explorerViewKey(target) { return `verbanode_${target}_view`; }

function getExplorerView(target) {
  const stored = localStorage.getItem(explorerViewKey(target));
  return EXPLORER_VIEW_MODES.has(stored) ? stored : 'cards';
}

function applyExplorerView(target, mode, persist = true) {
  const resolved = EXPLORER_VIEW_MODES.has(mode) ? mode : 'cards';
  const content = document.querySelector(`[data-explorer-view="${target}"]`);
  if (content) {
    content.classList.remove('view-cards', 'view-list', 'view-details');
    content.classList.add(`view-${resolved}`);
  }
  document.querySelectorAll(`[data-view-target="${target}"]`).forEach(button => {
    const active = button.dataset.viewMode === resolved;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  const page = content?.closest('.page');
  page?.classList.toggle('explorer-details-active', resolved === 'details');
  if (persist) localStorage.setItem(explorerViewKey(target), resolved);
}

function initializeExplorerViews() {
  applyExplorerView('information', getExplorerView('information'), false);
  applyExplorerView('plugins', getExplorerView('plugins'), false);
}

function getStoredUiTextSize() {
  const stored = localStorage.getItem(UI_TEXT_SIZE_KEY);
  return UI_TEXT_SIZES.has(stored) ? stored : 'medium';
}

function applyUiTextSize(size, persist = true) {
  const resolved = UI_TEXT_SIZES.has(size) ? size : 'medium';
  document.documentElement.dataset.uiTextSize = resolved;
  appState.uiTextSize = resolved;
  if (persist) localStorage.setItem(UI_TEXT_SIZE_KEY, resolved);
  const select = $('#uiTextSizeSelect');
  if (select && select.value !== resolved) select.value = resolved;
}

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function bytesLabel(bytes = 0) {
  if (!bytes) return 'Unknown size';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function toast(message, type = '') {
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.textContent = message;
  $('#toastRoot').appendChild(node);
  setTimeout(() => node.remove(), 4300);
}

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
    try {
      const payload = await response.json();
      detail = payload.detail || payload.message || detail;
    } catch (_) {}
    const error = new Error(detail);
    error.status = response.status;
    error.path = path;
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

async function login(pin, clientName, forceTakeover = false) {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pin, client_name: clientName, force_takeover: forceTakeover }),
  });
  let payload = {};
  try { payload = await response.json(); } catch (_) {}
  if (response.status === 401) throw new Error('Incorrect PIN');
  if (!response.ok) throw new Error(payload.detail || 'Login failed');

  if (payload.takeover_required) {
    // Compatibility with older backends: a valid PIN transfers control
    // immediately without asking the current or incoming controller again.
    return login(pin, clientName, true);
  }

  if (!payload.token) throw new Error('Login failed');
  await completeLogin(payload.token);
  if (payload.takeover) toast(`Control transferred from ${payload.previous_client || 'the previous device'}.`);
}

async function waitForTakeover(requestId, activeClient) {
  const status = $('#loginStatus');
  status.classList.remove('hidden');
  status.textContent = `Waiting for ${activeClient || 'the active controller'} to approve takeover…`;
  const started = Date.now();
  while (Date.now() - started < 35000) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    const response = await fetch(`/api/auth/takeover/${requestId}`);
    const payload = await response.json();
    if (payload.status === 'approved' && payload.token) {
      await completeLogin(payload.token);
      return;
    }
    if (payload.status === 'rejected' || payload.status === 'not_found') {
      throw new Error('Takeover was rejected or timed out');
    }
  }
  throw new Error('Takeover request timed out');
}

async function validateStoredSession() {
  if (!appState.token) return false;
  try {
    const response = await fetch('/api/heartbeat', {
      method: 'POST',
      cache: 'no-store',
      headers: { 'X-Session-Token': appState.token },
    });
    if (response.status === 401) {
      resetToLogin('Your previous session expired. Enter the PIN again.');
      return false;
    }
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
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

function connectWebSocket() {
  if (!appState.token) return;
  if (appState.ws) { try { appState.ws.close(); } catch (_) {} }
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${location.host}/ws?token=${encodeURIComponent(appState.token)}`);
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
      resetToLogin('Your controller session expired. Enter the PIN again.');
      return;
    }
    $('#connectionLabel').textContent = 'Reconnecting…';
    clearTimeout(appState.reconnectTimer);
    // A WebSocket rejected before acceptance is reported by browsers as code
    // 1006, even when the server rejected an expired token with HTTP 403.
    // Validate the HTTP session before attempting another WebSocket so an old
    // token cannot create an endless 403 reconnect loop.
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
  appState.ws.send(JSON.stringify({ command, ...data }));
  return true;
}


function browserPttButtons() {
  return [$('#browserPttBtn'), $('#mobileBrowserPttBtn')].filter(Boolean);
}

function hostPttButtons() {
  return [$('#holdPttBtn'), $('#mobileHostPttBtn')].filter(Boolean);
}

function browserMicrophoneSupported() {
  return Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia && (window.AudioContext || window.webkitAudioContext));
}

function updateBrowserMicSupport() {
  const buttons = browserPttButtons();
  const hint = $('#browserMicHint');
  if (!buttons.length || !hint) return;
  const supported = browserMicrophoneSupported();
  buttons.forEach(button => { button.disabled = !supported; });
  if (supported) {
    hint.textContent = 'The recording is uploaded after you release. TTS still plays through the Windows host.';
  } else if (!window.isSecureContext) {
    hint.textContent = 'Device microphone requires HTTPS. Restart VerbaNode with run.bat, open the HTTPS address, trust the local certificate, then reload.';
  } else {
    hint.textContent = 'This browser does not provide microphone capture support.';
  }
}

function mergeFloat32Chunks(chunks) {
  const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  chunks.forEach(chunk => { merged.set(chunk, offset); offset += chunk.length; });
  return merged;
}

function downsampleMono(input, sourceRate, targetRate = 16000) {
  if (!input.length || sourceRate <= targetRate) return input;
  const ratio = sourceRate / targetRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outputLength);
  let inputOffset = 0;
  for (let index = 0; index < outputLength; index += 1) {
    const nextOffset = Math.min(input.length, Math.round((index + 1) * ratio));
    let sum = 0;
    let count = 0;
    for (; inputOffset < nextOffset; inputOffset += 1) { sum += input[inputOffset]; count += 1; }
    output[index] = count ? sum / count : 0;
  }
  return output;
}

function encodePcm16Wav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeText = (offset, text) => { for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index)); };
  writeText(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); writeText(8, 'WAVE');
  writeText(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  writeText(36, 'data'); view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  samples.forEach(sample => {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, clipped < 0 ? clipped * 32768 : clipped * 32767, true);
    offset += 2;
  });
  return new Blob([buffer], { type: 'audio/wav' });
}

async function cleanupBrowserPttCapture() {
  const processor = appState.browserPttProcessor;
  const source = appState.browserPttSource;
  const gain = appState.browserPttGain;
  const context = appState.browserPttContext;
  const stream = appState.browserPttStream;
  appState.browserPttProcessor = null;
  appState.browserPttSource = null;
  appState.browserPttGain = null;
  appState.browserPttContext = null;
  appState.browserPttStream = null;
  try { if (processor) { processor.onaudioprocess = null; processor.disconnect(); } } catch (_) {}
  try { source?.disconnect(); } catch (_) {}
  try { gain?.disconnect(); } catch (_) {}
  try { stream?.getTracks().forEach(track => track.stop()); } catch (_) {}
  try { if (context && context.state !== 'closed') await context.close(); } catch (_) {}
}

async function cancelBrowserPttCapture(showMessage = false) {
  appState.browserPttHeld = false;
  appState.browserPttStarting = false;
  appState.browserPttActive = false;
  browserPttButtons().forEach(button => button.classList.remove('active'));
  await cleanupBrowserPttCapture();
  try { await api('/api/browser-ptt/cancel', { method: 'POST' }); } catch (_) {}
  if (showMessage) toast('Dashboard microphone recording was cancelled.');
}

async function startBrowserPttCapture(event) {
  event?.preventDefault();
  if (appState.browserPttHeld || appState.browserPttStarting || appState.browserPttActive) return;
  if (!browserMicrophoneSupported()) {
    updateBrowserMicSupport();
    toast(window.isSecureContext ? 'This browser cannot capture its microphone.' : 'Phone microphone access requires HTTPS. Restart with run.bat and open the HTTPS address.', 'error');
    return;
  }
  appState.browserPttHeld = true;
  appState.browserPttStarting = true;
  browserPttButtons().forEach(button => button.classList.add('active'));
  try {
    await api('/api/browser-ptt/start', { method: 'POST' });
    const stream = await navigator.mediaDevices.getUserMedia({
      video: false,
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (!appState.browserPttHeld) {
      stream.getTracks().forEach(track => track.stop());
      await cancelBrowserPttCapture(false);
      return;
    }
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const context = new AudioContextClass();
    await context.resume();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const gain = context.createGain();
    gain.gain.value = 0;
    appState.browserPttChunks = [];
    appState.browserPttSampleRate = context.sampleRate;
    processor.onaudioprocess = audioEvent => {
      if (!appState.browserPttActive) return;
      appState.browserPttChunks.push(new Float32Array(audioEvent.inputBuffer.getChannelData(0)));
    };
    source.connect(processor);
    processor.connect(gain);
    gain.connect(context.destination);
    appState.browserPttStream = stream;
    appState.browserPttContext = context;
    appState.browserPttSource = source;
    appState.browserPttProcessor = processor;
    appState.browserPttGain = gain;
    appState.browserPttActive = true;
    setLiveStatus('recording', 'Dashboard device PTT', 'Recording this phone or browser microphone');
  } catch (error) {
    await cancelBrowserPttCapture(false);
    const permissionHint = error?.name === 'NotAllowedError' ? ' Microphone permission was denied.' : '';
    toast(`${error.message || 'Could not start dashboard microphone.'}${permissionHint}`, 'error');
  } finally {
    appState.browserPttStarting = false;
  }
}

async function stopBrowserPttCapture(event) {
  event?.preventDefault();
  if (!appState.browserPttHeld && !appState.browserPttActive) return;
  appState.browserPttHeld = false;
  browserPttButtons().forEach(button => button.classList.remove('active'));
  if (appState.browserPttStarting && !appState.browserPttActive) return;
  if (!appState.browserPttActive) return;
  appState.browserPttActive = false;
  const chunks = appState.browserPttChunks;
  const sourceRate = appState.browserPttSampleRate || 48000;
  appState.browserPttChunks = [];
  await cleanupBrowserPttCapture();
  const merged = mergeFloat32Chunks(chunks);
  const samples = downsampleMono(merged, sourceRate, 16000);
  if (samples.length < 1600) {
    await cancelBrowserPttCapture(false);
    toast('Hold the dashboard microphone button a little longer.', 'error');
    return;
  }
  setLiveStatus('thinking', 'Uploading speech', 'Sending dashboard microphone audio to the Windows host');
  const form = new FormData();
  form.append('file', encodePcm16Wav(samples, 16000), 'dashboard-ptt.wav');
  try {
    await api('/api/browser-ptt/audio', { method: 'POST', body: form });
  } catch (error) {
    try { await api('/api/browser-ptt/cancel', { method: 'POST' }); } catch (_) {}
    toast(error.message, 'error');
    setLiveStatus('idle', 'Ready', 'Waiting for input');
  }
}

async function loadBootstrap() {
  const data = await api('/api/bootstrap');
  appState.data = data;
  appState.agents = data.agents || [];
  appState.information = data.information || [];
  appState.plugins = data.plugins || { plugins: [], summary: {} };
  appState.scripts = data.scripts || [];
  appState.queue = data.queue || [];
  appState.models = data.models || [];
  appState.kokoroVoices = data.kokoro_voices || [];
  appState.edgeVoices = data.edge_voices || appState.edgeVoices;
  appState.audioDevices = data.audio_devices || appState.audioDevices;
  appState.backendVersion = data.version || null;
  appState.features = data.features || {};
  appState.version = data.version || appState.version;
  appState.activeAgent = data.active_agent;
  appState.conversation = data.conversation;
  appState.conversations = data.conversations || [];
  appState.messages = data.messages || [];
  appState.mode = data.mode || 'idle';
  appState.pipeline = data.pipeline || appState.pipeline;
  appState.queueState = data.queue_state || 'paused';
  renderAll();
  if (data.ollama_error) toast(data.ollama_error, 'error');
}

function renderAll() {
  const versionNode = $('#appVersion');
  if (versionNode) {
    const mismatch = Boolean(appState.backendVersion) && appState.backendVersion !== FRONTEND_VERSION;
    versionNode.textContent = mismatch ? `v${appState.backendVersion} / UI ${FRONTEND_VERSION}` : `v${appState.version}`;
    versionNode.classList.toggle('version-mismatch', mismatch);
    versionNode.title = mismatch ? 'The running backend and dashboard files do not match. Restart VerbaNode after updating all files.' : '';
  }
  renderActiveAgent();
  renderMessages();
  renderConversations();
  renderAgents();
  renderInformation();
  renderPlugins();
  renderScripts();
  renderQueue();
  renderSettings();
  renderModels();
  renderRuntimeStatus(appState.data || {});
  setMode(appState.mode);
  updateBrowserMicSupport();
}

function renderActiveAgent() {
  const agent = appState.activeAgent;
  if (!agent) return;
  $('#activeAgentMini').innerHTML = `
    <div class="agent-mini-row">
      <div class="agent-avatar" style="background:${escapeHtml(agent.color)}">${escapeHtml(agent.avatar || 'VA')}</div>
      <div><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.llm_model)}</small></div>
    </div>`;
  $('#chatAgentIdentity').innerHTML = `
    <div class="agent-avatar" style="background:${escapeHtml(agent.color)}">${escapeHtml(agent.avatar || 'VA')}</div>
    <div><h3>${escapeHtml(agent.name)}</h3><p>${escapeHtml(agent.role)} · ${escapeHtml(agent.llm_model)}</p></div>`;
  document.documentElement.style.setProperty('--active-agent', agent.color || '#6c63ff');
}


function messageListNearBottom(list = $('#messageList'), threshold = 96) {
  return list.scrollHeight - list.scrollTop - list.clientHeight <= threshold;
}

function scrollMessagesToBottom(force = false) {
  const list = $('#messageList');
  if (force || messageListNearBottom(list)) {
    requestAnimationFrame(() => { list.scrollTop = list.scrollHeight; });
  }
}

function rejectedTranscriptVisibilityEnabled() {
  const toggle = $('#showRejectedSttToggle');
  if (toggle) return toggle.checked;
  return appState.data?.runtime_settings?.show_rejected_stt_transcripts !== false;
}

function applyRejectedTranscriptVisibility() {
  const list = $('#messageList');
  if (!list) return;
  list.classList.toggle('hide-rejected-transcripts', !rejectedTranscriptVisibilityEnabled());
}

function compareVersions(left = '0.0.0', right = '0.0.0') {
  const a = String(left).split(/[^0-9]+/).filter(Boolean).slice(0, 3).map(Number);
  const b = String(right).split(/[^0-9]+/).filter(Boolean).slice(0, 3).map(Number);
  while (a.length < 3) a.push(0);
  while (b.length < 3) b.push(0);
  for (let index = 0; index < 3; index += 1) {
    if (a[index] > b[index]) return 1;
    if (a[index] < b[index]) return -1;
  }
  return 0;
}

function diagnosticsBackendSupported() {
  if (appState.features?.diagnostics === true) return true;
  return Boolean(appState.backendVersion) && compareVersions(appState.backendVersion, DIAGNOSTICS_MIN_BACKEND_VERSION) >= 0;
}

function setDiagnosticControlsDisabled(disabled) {
  [
    '#runDiagnosticSelfTestBtn', '#startSoakTestBtn', '#stopSoakTestBtn',
    '#refreshDiagnosticsBtn', '#clearDiagnosticLogsBtn', '#clearLatencyHistoryBtn',
    '#downloadDiagnosticsBtn', '#diagnosticLogLevel', '#soakDurationSelect', '#soakIntervalSelect',
  ].forEach(selector => {
    const node = $(selector);
    if (node) node.disabled = Boolean(disabled);
  });
}

function renderDiagnosticsUnavailable(detail = '') {
  const backend = appState.backendVersion || 'unknown';
  const versionMismatch = backend !== 'unknown' && compareVersions(backend, DIAGNOSTICS_MIN_BACKEND_VERSION) < 0;
  const explanation = versionMismatch
    ? `The dashboard files are v${FRONTEND_VERSION}, but the running backend is v${backend}. Stop the existing VerbaNode process completely, copy all update files, and start run.bat again.`
    : (detail || 'The diagnostics API is unavailable in the running backend. Restart VerbaNode after copying the complete update.');
  const container = $('#diagnosticHealthCards');
  if (container) {
    container.innerHTML = `<article class="card diagnostic-compatibility-card">
      <span class="diagnostic-state warn">!</span>
      <div><small>BACKEND UPDATE REQUIRED</small><strong>Diagnostics could not connect</strong><p>${escapeHtml(explanation)}</p><div class="diagnostic-card-metrics"><span>Frontend v${escapeHtml(FRONTEND_VERSION)}</span><span>Backend v${escapeHtml(backend)}</span></div></div>
    </article>`;
  }
  const list = $('#diagnosticLogList');
  if (list) list.innerHTML = '<div class="queue-empty">Diagnostics will load after the backend and dashboard versions match.</div>';
  setDiagnosticControlsDisabled(true);
}

function activateSettingsPanel(panelName, remember = true) {
  const available = new Set($$('[data-settings-panel-content]').map(node => node.dataset.settingsPanelContent));
  const resolved = available.has(panelName) ? panelName : 'conversation';
  appState.settingsPanel = resolved;
  $$('[data-settings-panel]').forEach(button => button.classList.toggle('active', button.dataset.settingsPanel === resolved));
  $$('[data-settings-panel-content]').forEach(panel => panel.classList.toggle('active', panel.dataset.settingsPanelContent === resolved));
  if (remember) localStorage.setItem('verbanode_settings_panel', resolved);
  if (resolved === 'diagnostics' && appState.token) {
    if (!diagnosticsBackendSupported()) renderDiagnosticsUnavailable();
    else loadDiagnostics().catch(error => { if (error.status !== 404) toast(error.message, 'error'); });
  }
}

function renderMessages() {
  const list = $('#messageList');
  appState.streaming.clear();
  if (!appState.messages.length) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">◉</div><h3>Start a conversation</h3><p>Use continuous mode, push to talk, or type below. Replies will be spoken by the Windows host.</p></div>`;
    return;
  }
  list.innerHTML = appState.messages.map(messageHtml).join('');
  applyRejectedTranscriptVisibility();
  scrollMessagesToBottom(true);
}

function messageHtml(message) {
  const role = message.role === 'user' ? 'user' : 'assistant';
  const hasConfidence = message.stt_confidence !== null && message.stt_confidence !== undefined && message.stt_confidence !== '';
  const confidence = Number(message.stt_confidence);
  const confidenceLabel = role === 'user' && hasConfidence && Number.isFinite(confidence)
    ? ` · estimated STT ${Math.round(confidence * 100)}%`
    : '';
  const sourceLabel = role === 'user' && message.source === 'browser_ptt' ? ' · dashboard mic' : '';
  return `<article class="message ${role}" data-message-id="${message.id || ''}">
    <div class="message-bubble">${escapeHtml(message.content)}</div>
    <div class="message-meta">${role === 'user' ? 'You' : escapeHtml(appState.activeAgent?.name || 'Assistant')} · ${formatTime(message.created_at)}${sourceLabel}${confidenceLabel}</div>
  </article>`;
}

function appendRejectedTranscript(data) {
  const list = $('#messageList');
  if (!rejectedTranscriptVisibilityEnabled()) {
    setLiveStatus('idle', 'Ready', 'Low-confidence speech was filtered');
    return;
  }
  const stickToBottom = messageListNearBottom(list);
  $('.empty-state', list)?.remove();
  const confidence = Number(data.confidence_percent ?? Math.round(Number(data.confidence || 0) * 100));
  const threshold = Number(data.threshold_percent ?? Math.round(Number(data.threshold || 0) * 100));
  const node = document.createElement('article');
  node.className = 'message user rejected-transcript';
  node.innerHTML = `<div class="message-bubble"><span class="rejected-transcript-label">Filtered STT</span>${escapeHtml(data.text || '')}</div>
    <div class="message-meta">Not sent to agent · estimated STT ${confidence}% · threshold ${threshold}%</div>`;
  list.appendChild(node);
  const rejectedNodes = $$('.rejected-transcript', list);
  rejectedNodes.slice(0, Math.max(0, rejectedNodes.length - 100)).forEach(item => item.remove());
  applyRejectedTranscriptVisibility();
  if (stickToBottom) scrollMessagesToBottom(true);
  setLiveStatus('idle', 'Ready', 'Low-confidence transcript was not sent');
}

function appendMessage(message) {
  const list = $('#messageList');
  const stickToBottom = messageListNearBottom(list);
  $('.empty-state', list)?.remove();
  if ($(`[data-message-id="${message.id}"]`, list)) return;
  list.insertAdjacentHTML('beforeend', messageHtml(message));
  if (stickToBottom) scrollMessagesToBottom(true);
  appState.messages.push(message);
}

function beginAssistantStream(data) {
  const list = $('#messageList');
  $('.empty-state', list)?.remove();
  const node = document.createElement('article');
  node.className = 'message assistant';
  node.dataset.generationId = data.generation_id;
  node.innerHTML = `<div class="message-bubble typing-cursor"></div><div class="message-meta">${escapeHtml(appState.activeAgent?.name || 'Assistant')} · generating</div>`;
  list.appendChild(node);
  appState.streaming.set(data.generation_id, { node, text: '' });
  scrollMessagesToBottom(true);
  setLiveStatus('thinking', 'Generating reply', 'Ollama is producing a response');
}

function appendAssistantToken(data) {
  const stream = appState.streaming.get(data.generation_id);
  if (!stream) return;
  const list = $('#messageList');
  const stickToBottom = messageListNearBottom(list);
  stream.text += data.token || '';
  $('.message-bubble', stream.node).textContent = stream.text;
  if (stickToBottom) scrollMessagesToBottom(true);
}

function completeAssistantStream(data) {
  const stream = appState.streaming.get(data.generation_id);
  if (stream) {
    stream.node.dataset.messageId = data.message.id;
    $('.message-bubble', stream.node).textContent = data.message.content;
    $('.message-bubble', stream.node).classList.remove('typing-cursor');
    $('.message-meta', stream.node).textContent = `${appState.activeAgent?.name || 'Assistant'} · ${formatTime(data.message.created_at)}`;
    appState.streaming.delete(data.generation_id);
    appState.messages.push(data.message);
  } else {
    appendMessage(data.message);
  }
  setLiveStatus('idle', 'Ready', 'Waiting for input');
}

function renderConversations() {
  const select = $('#conversationSelect');
  select.innerHTML = appState.conversations.map(conversation => `<option value="${conversation.id}" ${conversation.id === appState.conversation?.id ? 'selected' : ''}>${escapeHtml(conversation.title)} (${conversation.message_count ?? 0})</option>`).join('');
}

function renderAgents() {
  const grid = $('#agentGrid');
  grid.innerHTML = appState.agents.map(agent => {
    const active = agent.id === appState.activeAgent?.id;
    return `<article class="card agent-card ${active ? 'active' : ''}" style="--agent-color:${escapeHtml(agent.color)}">
      <div class="agent-card-head"><div class="agent-avatar" style="background:${escapeHtml(agent.color)}">${escapeHtml(agent.avatar || 'VA')}</div><div><h3>${escapeHtml(agent.name)}</h3><p>${escapeHtml(agent.role)}</p></div></div>
      <div class="agent-card-body">${escapeHtml(agent.greeting)}</div>
      <div class="agent-card-meta"><span class="chip">${agent.language === 'id' ? 'Bahasa Indonesia' : 'English'}</span><span class="chip">${escapeHtml(agent.llm_model)}</span><span class="chip">${escapeHtml(agent.tts_mode)}</span><span class="chip">${escapeHtml(agent.kokoro_voice_name || 'Kokoro voice')}</span><span class="chip">${agent.info_ids?.length || 0} info</span></div>
      <div class="agent-card-actions">
        ${active ? '<button class="btn success compact" disabled>Active</button>' : `<button class="btn secondary compact" data-activate-agent="${agent.id}">Use agent</button>`}
        <button class="btn ghost compact" data-edit-agent="${agent.id}">Edit</button>
        <button class="btn danger-outline compact" data-delete-agent="${agent.id}">Delete</button>
      </div>
    </article>`;
  }).join('');
}

function renderInformation() {
  const list = $('#informationList');
  if (!appState.information.length) {
    list.innerHTML = `<div class="card queue-empty">No information entries yet.</div>`;
    return;
  }
  list.innerHTML = appState.information.map(item => `<article class="card info-item">
    <div class="info-header">
      <div class="enabled-pill ${item.enabled ? '' : 'off'}">● ${item.enabled ? 'Enabled' : 'Disabled'}</div>
      <h3>${escapeHtml(item.title)}</h3>
    </div>
    <div class="info-preview">${escapeHtml(item.content)}</div>
    <div class="item-actions"><button class="btn ghost compact" data-edit-info="${item.id}">Edit</button><button class="btn danger-outline compact" data-delete-info="${item.id}">Delete</button></div>
  </article>`).join('');
  applyExplorerView('information', getExplorerView('information'), false);
}

function pluginStatusLabel(plugin) {
  if (plugin.status === 'incompatible') return ['Incompatible', 'error'];
  if (plugin.status === 'invalid') return ['Invalid package', 'error'];
  if (plugin.status === 'load_error') return ['Load failed', 'error'];
  if (!plugin.enabled || plugin.status === 'disabled') return ['Disabled', 'disabled'];
  if (plugin.status === 'loading') return ['Loading', 'neutral'];
  if (plugin.status === 'reloading') return ['Reloading', 'neutral'];
  if (plugin.status === 'unhealthy') return ['Unhealthy', 'warning'];
  if (!plugin.healthy || plugin.status === 'error') return ['Error', 'error'];
  return ['Healthy', 'healthy'];
}

function pluginMetric(value, suffix = '') {
  const number = Number(value || 0);
  return `${Number.isInteger(number) ? number : number.toFixed(2)}${suffix}`;
}

function createPluginElement(tagName, className = '', text = '') {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== '') node.textContent = String(text);
  return node;
}

function createPluginMetricElement(label, value) {
  const metric = createPluginElement('div', 'plugin-metric');
  metric.append(
    createPluginElement('span', '', label),
    createPluginElement('strong', '', value),
  );
  return metric;
}

function createPluginCard(plugin) {
  const [statusLabel, statusClass] = pluginStatusLabel(plugin);
  const failedLoad = ['load_error', 'incompatible', 'invalid'].includes(plugin.status);
  const card = createPluginElement('article', `card plugin-card${plugin.enabled ? '' : ' plugin-disabled'}${failedLoad ? ' plugin-load-error' : ''}`);
  card.dataset.pluginCard = String(plugin.id || '');

  const head = createPluginElement('div', 'plugin-card-head');
  const title = createPluginElement('div', 'plugin-card-title');
  const eyebrow = createPluginElement('div', 'plugin-title-meta');
  eyebrow.append(
    createPluginElement('span', 'eyebrow', plugin.category || 'General'),
    createPluginElement('span', `plugin-source ${plugin.external ? 'external' : 'builtin'}`, plugin.external ? 'External' : 'Built-in'),
  );
  title.append(
    eyebrow,
    createPluginElement('h3', '', plugin.name || plugin.id || 'Plugin'),
    createPluginElement('small', '', `${plugin.declared_id || plugin.id || 'unknown'} · v${plugin.version || '0.0.0'} · SDK ${plugin.sdk_version || '1'}`),
  );
  head.append(title, createPluginElement('span', `plugin-status ${statusClass}`, statusLabel));

  const body = createPluginElement('div', 'plugin-card-body');
  body.append(createPluginElement('p', 'plugin-description', plugin.description || plugin.tool_description || ''));

  const permissions = createPluginElement('div', 'plugin-permissions');
  const permissionList = Array.isArray(plugin.permissions) ? plugin.permissions : [];
  if (permissionList.length) {
    permissionList.forEach(permission => {
      permissions.append(createPluginElement('span', 'chip plugin-permission', permission));
    });
  } else {
    permissions.append(createPluginElement('span', 'chip plugin-permission neutral', 'No declared permissions'));
  }
  body.append(permissions);

  if (!failedLoad) {
    const metrics = createPluginElement('div', 'plugin-metrics');
    metrics.append(
      createPluginMetricElement('Executions', pluginMetric(plugin.executions)),
      createPluginMetricElement('Errors', pluginMetric(plugin.errors)),
      createPluginMetricElement('Timeouts', pluginMetric(plugin.timeouts)),
      createPluginMetricElement('Failure streak', `${pluginMetric(plugin.consecutive_failures)} / ${pluginMetric(plugin.failure_threshold)}`),
      createPluginMetricElement('Average', pluginMetric(plugin.average_latency_ms, ' ms')),
      createPluginMetricElement('Active', pluginMetric(plugin.active_executions)),
    );
    body.append(metrics);

    const assignment = createPluginElement('div', 'plugin-agent-use');
    assignment.append(
      createPluginElement('span', '', 'Assigned to agents'),
      createPluginElement('strong', '', `${Number(plugin.agent_count || 0)} / ${Number(plugin.agent_total || 0)}`),
    );
    body.append(assignment);
  }

  if (plugin.last_error) {
    const errorBox = createPluginElement('div', 'plugin-error');
    errorBox.append(
      createPluginElement('strong', '', failedLoad ? 'Package error' : 'Last execution error'),
      createPluginElement('span', '', plugin.last_error),
    );
    body.append(errorBox);
  }
  if (plugin.last_reload_error) {
    const reloadErrorBox = createPluginElement('div', 'plugin-error plugin-reload-error');
    reloadErrorBox.append(
      createPluginElement('strong', '', 'Last reload kept the previous version'),
      createPluginElement('span', '', plugin.last_reload_error),
    );
    body.append(reloadErrorBox);
  }

  if (plugin.external && plugin.plugin_path) {
    const pathBox = createPluginElement('div', 'plugin-path');
    pathBox.title = plugin.plugin_path;
    pathBox.append(
      createPluginElement('span', '', 'Folder'),
      createPluginElement('code', '', plugin.plugin_path),
    );
    body.append(pathBox);
  }

  const footer = createPluginElement('div', 'plugin-card-footer');
  footer.append(createPluginElement('span', 'plugin-author', plugin.author || 'Unknown author'));

  const actions = createPluginElement('div', 'plugin-card-actions');
  if (!failedLoad) {
    const resetButton = createPluginElement('button', 'plugin-action plugin-action-reset', 'Reset metrics');
    resetButton.type = 'button';
    resetButton.dataset.resetPlugin = String(plugin.id || '');
    resetButton.disabled = !Number(plugin.executions || 0) && !Number(plugin.errors || 0);
    actions.append(resetButton);
  }

  if (plugin.external && plugin.reloadable) {
    const reloadButton = createPluginElement('button', 'plugin-action plugin-action-reload', failedLoad || plugin.status === 'unhealthy' ? 'Repair / reload' : 'Reload');
    reloadButton.type = 'button';
    reloadButton.dataset.reloadPlugin = String(plugin.id || '');
    actions.append(reloadButton);
  } else if (plugin.status === 'unhealthy') {
    const recoverButton = createPluginElement('button', 'plugin-action plugin-action-reload', 'Recover');
    recoverButton.type = 'button';
    recoverButton.dataset.recoverPlugin = String(plugin.id || '');
    actions.append(recoverButton);
  }

  if (!failedLoad) {
    const toggleButton = createPluginElement(
      'button',
      `plugin-action ${plugin.enabled ? 'plugin-action-disable' : 'plugin-action-enable'}`,
      plugin.enabled ? 'Disable' : 'Enable',
    );
    toggleButton.type = 'button';
    toggleButton.dataset.togglePlugin = String(plugin.id || '');
    toggleButton.dataset.enabled = plugin.enabled ? 'true' : 'false';
    actions.append(toggleButton);
  }

  footer.append(actions);
  card.append(head, body, footer);
  return card;
}

function renderPlugins() {
  const payload = appState.plugins || { plugins: [], summary: {} };
  const plugins = Array.isArray(payload.plugins) ? payload.plugins : [];
  const summary = payload.summary || {};
  const summaryNode = $('#pluginSummary');
  const grid = $('#pluginGrid');
  if (!summaryNode || !grid) return;

  const healthLabel = Number(summary.errors || 0) > 0
    ? `${summary.errors} issue${Number(summary.errors) === 1 ? '' : 's'}`
    : 'All clear';

  const summaryCards = [
    ['Discovered', Number(summary.total || plugins.length), `${Number(summary.loaded || 0)} loaded`],
    ['Sources', `${Number(summary.builtin || 0)} + ${Number(summary.external || 0)}`, 'Built-in + external'],
    ['Executions', Number(summary.executions || 0), `${Number(summary.agent_assignments || 0)} agent assignments`],
    ['Health', healthLabel, `${Number(summary.failed_loads || 0)} failed to load`],
  ].map(([label, value, detail]) => {
    const card = createPluginElement('div', 'card plugin-summary-card');
    card.append(
      createPluginElement('span', '', label),
      createPluginElement('strong', '', value),
      createPluginElement('small', '', detail),
    );
    return card;
  });
  summaryNode.replaceChildren(...summaryCards);

  const folder = $('#externalPluginDirectory');
  if (folder) folder.textContent = payload.external_plugins_directory || 'plugins/';

  if (!plugins.length) {
    grid.replaceChildren(createPluginElement('div', 'card queue-empty plugin-empty-state', 'No plugins were reported by the backend.'));
    return;
  }

  grid.replaceChildren(...plugins.map(createPluginCard));
  applyExplorerView('plugins', getExplorerView('plugins'), false);
}

async function refreshPlugins(showToast = false) {
  const payload = await api('/api/plugins');
  appState.plugins = payload;
  if (appState.data) appState.data.plugins = payload;
  renderPlugins();
  if (showToast) toast('Plugin status refreshed.');
  return payload;
}

function renderScripts() {
  const grid = $('#scriptGrid');
  if (!appState.scripts.length) grid.innerHTML = `<div class="card queue-empty">No scripts yet.</div>`;
  else grid.innerHTML = appState.scripts.map(script => `<article class="card script-card">
    <div class="card-title-row"><h3>${escapeHtml(script.title)}</h3><span class="enabled-pill ${script.enabled ? '' : 'off'}">● ${script.enabled ? 'Ready' : 'Disabled'}</span></div>
    <p>${escapeHtml(script.text)}</p>
    <div class="agent-card-meta"><span class="chip">${script.language === 'id' ? 'Bahasa Indonesia' : 'English'}</span><span class="chip">${escapeHtml(script.tts_mode || 'edge')}</span><span class="chip">${escapeHtml(script.edge_voice || '')}</span></div>
    <div class="script-actions"><button class="btn success compact" data-run-script="${script.id}" ${script.enabled ? '' : 'disabled'}>▶ Run now</button><button class="btn secondary compact" data-queue-script="${script.id}" ${script.enabled ? '' : 'disabled'}>＋ Queue</button><button class="icon-btn" data-edit-script="${script.id}" title="Edit">✎</button></div>
  </article>`).join('');
  $('#quickScripts').innerHTML = appState.scripts.filter(script => script.enabled).slice(0, 4).map(script => `<div class="quick-script"><span>${escapeHtml(script.title)}</span><button class="btn secondary compact" data-run-script="${script.id}">▶</button></div>`).join('') || '<p class="tiny muted">No enabled scripts.</p>';
}

function renderQueue() {
  const count = appState.queue.length;
  $('#queueBadge').textContent = count;
  $('#queueBadge').classList.toggle('hidden', count === 0);
  $('#queueStateChip').textContent = appState.queueState === 'playing' ? 'Playing' : 'Paused';
  const html = count ? appState.queue.map((item, index) => `<div class="queue-item">
    <span class="queue-number">${index + 1}</span><div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.status)}</small></div><button class="icon-btn" data-remove-queue="${item.id}" title="Remove">×</button>
  </div>`).join('') : `<div class="queue-empty">Queue is empty.<br>Add scripts or use Run now.</div>`;
  $('#queueList').innerHTML = html;
  $('#drawerQueueList').innerHTML = html;
}

function renderSettings() {
  const settings = appState.data?.runtime_settings || {};
  $('#interruptionToggle').checked = Boolean(settings.interruption_enabled);
  $('#silenceInput').value = settings.silence_ms || 900;
  $('#maxRecordInput').value = settings.max_record_seconds || 30;
  $('#sttConfidenceFilterToggle').checked = settings.stt_confidence_filter_enabled !== false;
  $('#sttConfidenceThresholdInput').value = Math.round(Number(settings.stt_confidence_threshold ?? 0.70) * 100);
  $('#showRejectedSttToggle').checked = settings.show_rejected_stt_transcripts !== false;
  applyUiTextSize(appState.uiTextSize || getStoredUiTextSize(), false);
  renderAudioDevices();
  applyRejectedTranscriptVisibility();
  activateSettingsPanel(appState.settingsPanel, false);
}

function audioDeviceLabel(device, direction) {
  const channels = direction === 'input' ? device.max_input_channels : device.max_output_channels;
  const flags = [];
  if ((direction === 'input' && device.recommended_input) || (direction === 'output' && device.recommended_output)) flags.push('recommended');
  if ((direction === 'input' && device.is_default_input) || (direction === 'output' && device.is_default_output)) flags.push('Windows default');
  const suffix = flags.length ? ` · ${flags.join(', ')}` : '';
  return `${device.name} · ${device.hostapi} · ${channels} ch${suffix}`;
}

function renderAudioDevices() {
  const inputs = appState.audioDevices?.inputs || [];
  const outputs = appState.audioDevices?.outputs || [];
  const settings = appState.data?.runtime_settings || {};
  const savedInput = settings.input_device;
  const savedOutput = settings.output_device;
  const selectedInput = savedInput ?? appState.audioDevices?.recommended_input ?? '';
  const selectedOutput = savedOutput ?? appState.audioDevices?.recommended_output ?? '';

  const inputSelect = $('#inputDeviceSelect');
  const outputSelect = $('#outputDeviceSelect');
  if (!inputSelect || !outputSelect) return;

  inputSelect.innerHTML = `<option value="">Use Windows default input</option>${inputs.map(device => `<option value="${device.id}">${escapeHtml(audioDeviceLabel(device, 'input'))}</option>`).join('')}`;
  outputSelect.innerHTML = `<option value="">Use Windows default output</option>${outputs.map(device => `<option value="${device.id}">${escapeHtml(audioDeviceLabel(device, 'output'))}</option>`).join('')}`;
  inputSelect.value = selectedInput === null || selectedInput === undefined ? '' : String(selectedInput);
  outputSelect.value = selectedOutput === null || selectedOutput === undefined ? '' : String(selectedOutput);

  updateAudioDeviceHints();
}

function updateAudioDeviceHints() {
  const inputs = appState.audioDevices?.inputs || [];
  const outputs = appState.audioDevices?.outputs || [];
  const inputSelect = $('#inputDeviceSelect');
  const outputSelect = $('#outputDeviceSelect');
  if (!inputSelect || !outputSelect) return;
  const input = inputs.find(device => String(device.id) === inputSelect.value);
  const output = outputs.find(device => String(device.id) === outputSelect.value);
  $('#inputDeviceHint').textContent = input
    ? `Selected: ${input.name} through ${input.hostapi}.${input.recommended_input ? ' Recommended input detected.' : ''}`
    : 'Using the Windows default input. Select a specific device to make reconnect behavior more predictable.';
  $('#outputDeviceHint').textContent = output
    ? `Selected: ${output.name} through ${output.hostapi}.${output.recommended_output ? ' Recommended output detected.' : ''}`
    : 'Using the Windows default output. Select a specific device to make reconnect behavior more predictable.';
}

function selectedAudioDeviceId(selector) {
  const value = $(selector)?.value ?? '';
  return value === '' ? null : Number(value);
}

function renderModels() {
  const box = $('#ollamaStatusBox');
  if (appState.data?.ollama_error) box.innerHTML = `<strong>Ollama unavailable</strong><br>${escapeHtml(appState.data.ollama_error)}`;
  else box.innerHTML = `<strong>Ollama connected</strong><br>${appState.models.length} local model${appState.models.length === 1 ? '' : 's'} available.`;
  $('#modelList').innerHTML = appState.models.map(model => `<div class="model-item"><div><strong>${escapeHtml(model.name || model.model)}</strong><small>${escapeHtml(model.details?.parameter_size || '')} ${escapeHtml(model.details?.quantization_level || '')}</small></div><span class="chip">${bytesLabel(model.size)}</span></div>`).join('') || '<div class="queue-empty">No local models reported.</div>';
}

function renderRuntimeStatus(data) {
  const tts = data.tts || {};
  const stt = data.stt || {};
  const hardware = data.hardware || {};
  const audio = data.audio || {};
  const audioEngine = audio.engine || {};
  const ai = data.ai || {};
  const aiEngine = ai.engine || {};
  const aiRemote = aiEngine.remote || {};
  const aiAsr = aiRemote.asr || {};
  const aiKokoro = aiRemote.kokoro || {};
  const pipeline = data.pipeline || appState.pipeline || {};
  const latency = pipeline.latency_ms || {};
  const counters = pipeline.counters || {};
  appState.pipeline = pipeline;
  const pipelinePanel = $('#pipelineStatusPanel');
  if (pipelinePanel) {
    const stage = String(pipeline.state || 'idle').replaceAll('_', ' ');
    const turn = pipeline.turn_id ? ` · turn ${String(pipeline.turn_id).slice(0, 8)}` : '';
    const timing = [
      latency.stt_total != null ? `STT ${latency.stt_total} ms` : null,
      latency.llm_total != null ? `LLM ${latency.llm_total} ms` : null,
      latency.tts_total != null ? `TTS ${latency.tts_total} ms` : null,
      latency.turn_total != null ? `Total ${latency.turn_total} ms` : null,
    ].filter(Boolean).join(' · ');
    pipelinePanel.innerHTML = `<strong>Pipeline: ${escapeHtml(stage)}</strong>${escapeHtml(turn)}<br><span class="muted">${escapeHtml(timing || 'No completed timing sample yet.')}</span>`;
  }
  const edgeHealth = tts.provider_health?.edge || {};
  const kokoroHealth = tts.provider_health?.kokoro || {};
  $('#runtimeStatusList').innerHTML = `
    <dt>CPU threads</dt><dd>${hardware.cpu_count ?? 'Unknown'}</dd>
    <dt>Total RAM</dt><dd>${hardware.ram_total_gb ?? 'Unknown'} GB</dd>
    <dt>Available RAM</dt><dd>${hardware.ram_available_gb ?? 'Unknown'} GB</dd>
    <dt>FunASR</dt><dd>${stt.installed ? 'Installed' : 'Missing'}</dd>
    <dt>STT model</dt><dd>${escapeHtml(stt.model || '')}</dd>
    <dt>Edge TTS</dt><dd>${edgeHealth.circuit_open ? 'Fallback active' : (tts.edge_installed ? 'Ready' : 'Missing')}</dd>
    <dt>Kokoro</dt><dd>${kokoroHealth.circuit_open ? 'Recovering' : (tts.kokoro_model_ready ? (tts.kokoro_loaded ? 'Loaded' : 'Model available') : 'Not downloaded')}</dd>
    <dt>AI Engine</dt><dd>${aiEngine.mode === 'isolated_process' ? (aiEngine.alive ? `Process ${aiEngine.pid} active` : 'Process unavailable') : 'In-process compatibility mode'}</dd>
    <dt>AI state</dt><dd>${escapeHtml(String(aiRemote.coordinator_state || 'idle'))}</dd>
    <dt>Active ASR state</dt><dd>${escapeHtml(String(aiAsr.state || stt.state || 'unknown'))}${aiAsr.last_latency_ms != null ? ` · ${aiAsr.last_latency_ms} ms` : ''}</dd>
    <dt>Kokoro state</dt><dd>${escapeHtml(String(aiKokoro.state || tts.kokoro_status?.state || 'unknown'))}${aiKokoro.last_latency_ms != null ? ` · ${aiKokoro.last_latency_ms} ms` : ''}</dd>
    <dt>AI queues</dt><dd>ASR ${aiEngine.inflight?.asr ?? 0}/${aiEngine.queue_limits?.asr ?? '-'} · TTS ${aiEngine.inflight?.kokoro ?? 0}/${aiEngine.queue_limits?.kokoro ?? '-'}</dd>
    <dt>AI restarts</dt><dd>${aiEngine.restart_count ?? 0}</dd>
    <dt>Audio Engine</dt><dd>${audioEngine.mode === 'isolated_process' ? (audioEngine.alive ? `Process ${audioEngine.pid} active` : 'Process unavailable') : 'In-process compatibility mode'}</dd>
    <dt>Audio state</dt><dd>${escapeHtml(String(audioEngine.remote?.coordinator_state || 'idle'))}</dd>
    <dt>Audio restarts</dt><dd>${audioEngine.restart_count ?? 0}</dd>
    <dt>Device refreshes</dt><dd>${audioEngine.device_refresh_count ?? 0}</dd>
    <dt>Hot-plug recoveries</dt><dd>${audioEngine.device_recovery_count ?? 0}</dd>
    <dt>Microphone lock</dt><dd>${audio.input_locked ? 'Locked and active' : 'Released'}</dd>
    <dt>Speaker lock</dt><dd>${audio.output_locked ? 'Locked and active' : 'Not opened yet'}</dd>
    <dt>Completed turns</dt><dd>${counters.turns_completed ?? 0}</dd>
    <dt>STT timeouts</dt><dd>${counters.stt_timeouts ?? 0}</dd>
    <dt>Provider failures</dt><dd>${counters.tts_provider_failures ?? 0}</dd>`;
  $('#ttsProviderStatus').textContent = appState.activeAgent?.kokoro_voice_name || appState.activeAgent?.tts_mode || 'TTS';
}

function durationLabel(seconds = 0) {
  const total = Math.max(0, Number(seconds) || 0);
  if (total < 60) return `${Math.round(total)}s`;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = Math.floor(total % 60);
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m ${secs}s`;
}

function metricValue(value, suffix = '') {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(Number(value) >= 100 ? 0 : 1)}${suffix}`;
}

function diagnosticCard(label, state, title, detail, metrics = '') {
  const safeState = ['good', 'warn', 'bad', 'neutral'].includes(state) ? state : 'neutral';
  return `<article class="card diagnostic-health-card">
    <span class="diagnostic-state ${safeState}">${safeState === 'good' ? '✓' : safeState === 'warn' ? '!' : safeState === 'bad' ? '×' : '…'}</span>
    <div><small>${escapeHtml(label)}</small><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p>${metrics ? `<div class="diagnostic-card-metrics">${metrics}</div>` : ''}</div>
  </article>`;
}

function averageLatency(turns, key) {
  const values = turns.map(turn => Number(turn.latency_ms?.[key])).filter(value => Number.isFinite(value));
  if (!values.length) return null;
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

function renderDiagnosticSelfTest(result) {
  const badge = $('#diagnosticSelfTestBadge');
  const list = $('#diagnosticSelfTestResults');
  if (!badge || !list) return;
  if (!result) {
    badge.textContent = 'Not run';
    badge.className = 'chip';
    list.innerHTML = '<div class="queue-empty">Run the self-test to validate the current installation.</div>';
    return;
  }
  badge.textContent = result.overall === 'pass' ? 'Passed' : result.overall === 'warn' ? 'Warnings' : 'Failed';
  badge.className = `chip diagnostic-chip-${result.overall}`;
  list.innerHTML = (result.checks || []).map(check => `<div class="diagnostic-test-item ${escapeHtml(check.status)}">
    <span>${check.status === 'pass' ? '✓' : check.status === 'warn' ? '!' : '×'}</span>
    <div><strong>${escapeHtml(check.name)}</strong><small>${escapeHtml(check.detail)} · ${Number(check.duration_ms || 0)} ms</small></div>
  </div>`).join('') || '<div class="queue-empty">No test results.</div>';
}

function renderSoakStatus(soak = {}) {
  const active = Boolean(soak.active);
  const duration = Number(soak.duration_seconds || 0);
  const elapsed = Number(soak.elapsed_seconds || 0);
  const percent = duration > 0 ? Math.min(100, Math.round((elapsed / duration) * 100)) : 0;
  $('#soakStateBadge').textContent = active ? 'Running' : soak.completed_at ? 'Complete' : 'Idle';
  $('#soakStateBadge').className = `chip ${active ? 'diagnostic-chip-warn' : soak.completed_at ? 'diagnostic-chip-pass' : ''}`;
  $('#soakProgressBar').style.width = `${percent}%`;
  $('#startSoakTestBtn').disabled = active;
  $('#stopSoakTestBtn').disabled = !active;
  const summary = soak.summary || {};
  if (active) {
    $('#soakStatusText').innerHTML = `<strong>${percent}% complete</strong><br>${durationLabel(elapsed)} elapsed · ${durationLabel(soak.remaining_seconds)} remaining · ${soak.sample_count || 0} samples.`;
  } else if (soak.completed_at) {
    $('#soakStatusText').innerHTML = `<strong>${escapeHtml(soak.stop_reason === 'stopped_by_user' ? 'Soak test stopped' : 'Soak test completed')}</strong><br>${soak.sample_count || 0} samples · Audio restarts ${summary.audio_restart_delta ?? 0} · AI restarts ${summary.ai_restart_delta ?? 0} · Pipeline errors ${summary.pipeline_error_delta ?? 0}.`;
  } else {
    $('#soakStatusText').textContent = 'No soak test is running.';
  }
}

function renderDiagnostics(data) {
  appState.diagnostics = data;
  setDiagnosticControlsDisabled(false);
  const snapshot = data?.snapshot || {};
  const resources = snapshot.resources || {};
  const processes = resources.processes || {};
  const system = resources.system || {};
  const audio = snapshot.audio || {};
  const audioEngine = audio.engine || {};
  const aiEngine = snapshot.ai?.engine || {};
  const pipeline = snapshot.pipeline || {};
  const coreProcess = processes.core || {};
  const audioProcess = processes.audio || {};
  const aiProcess = processes.ai || {};
  const audioHeartbeat = audioEngine.seconds_since_heartbeat;
  const aiHeartbeat = aiEngine.heartbeat_age_seconds;
  const cards = [
    diagnosticCard('CORE', coreProcess.available ? 'good' : 'warn', coreProcess.available ? `Process ${coreProcess.pid}` : 'Resource metrics unavailable', `Uptime ${durationLabel(snapshot.environment?.uptime_seconds || 0)} · Pipeline ${pipeline.state || 'unknown'}`, `<span>CPU ${metricValue(coreProcess.cpu_percent, '%')}</span><span>RAM ${metricValue(coreProcess.rss_mb, ' MB')}</span><span>${coreProcess.threads ?? '—'} threads</span>`),
    diagnosticCard('AUDIO ENGINE', audioEngine.alive ? (audioHeartbeat != null && Number(audioHeartbeat) > 10 ? 'warn' : 'good') : 'bad', audioEngine.alive ? `Process ${audioEngine.pid}` : 'Process unavailable', `${audio.input?.input_locked ? 'Mic locked' : 'Mic released'} · ${audio.output?.output_locked ? 'Speaker locked' : 'Speaker released'} · ${audioEngine.restart_count ?? 0} restarts`, `<span>CPU ${metricValue(audioProcess.cpu_percent, '%')}</span><span>RAM ${metricValue(audioProcess.rss_mb, ' MB')}</span><span>Heartbeat ${audioHeartbeat == null ? '—' : `${audioHeartbeat}s`}</span>`),
    diagnosticCard('AI ENGINE', aiEngine.alive ? (aiHeartbeat != null && Number(aiHeartbeat) > 10 ? 'warn' : 'good') : 'bad', aiEngine.alive ? `Process ${aiEngine.pid}` : 'Process unavailable', `ASR ${aiEngine.remote?.asr?.state || 'unknown'} · Kokoro ${aiEngine.remote?.kokoro?.state || 'unknown'} · ${aiEngine.restart_count ?? 0} restarts`, `<span>CPU ${metricValue(aiProcess.cpu_percent, '%')}</span><span>RAM ${metricValue(aiProcess.rss_mb, ' MB')}</span><span>Heartbeat ${aiHeartbeat == null ? '—' : `${aiHeartbeat}s`}</span>`),
    diagnosticCard('SYSTEM', system.available ? (Number(system.ram_percent || 0) > 90 || Number(system.disk_percent || 0) > 90 ? 'warn' : 'good') : 'neutral', system.available ? `${metricValue(system.cpu_percent, '%')} CPU` : 'System metrics unavailable', `${metricValue(system.ram_used_gb, ' GB')} / ${metricValue(system.ram_total_gb, ' GB')} RAM · ${metricValue(system.disk_free_gb, ' GB')} disk free`, `<span>RAM ${metricValue(system.ram_percent, '%')}</span><span>Disk ${metricValue(system.disk_percent, '%')}</span><span>${system.cpu_count ?? '—'} threads</span>`),
  ];
  $('#diagnosticHealthCards').innerHTML = cards.join('');

  const turns = data?.recent_turns || [];
  const summaryItems = [
    ['STT avg', averageLatency(turns, 'stt_total')],
    ['LLM avg', averageLatency(turns, 'llm_total')],
    ['TTS avg', averageLatency(turns, 'tts_total')],
    ['Total avg', averageLatency(turns, 'turn_total')],
  ];
  $('#diagnosticLatencySummary').innerHTML = summaryItems.map(([label, value]) => `<div><small>${label}</small><strong>${value == null ? '—' : `${value} ms`}</strong></div>`).join('');
  $('#diagnosticLatencyRows').innerHTML = turns.length ? [...turns].reverse().slice(0, 12).map(turn => `<tr class="${turn.cancelled ? 'cancelled' : ''}"><td>${escapeHtml(turn.source || 'unknown')}</td><td>${turn.latency_ms?.stt_total ?? '—'}</td><td>${turn.latency_ms?.llm_total ?? '—'}</td><td>${turn.latency_ms?.tts_total ?? '—'}</td><td>${turn.latency_ms?.turn_total ?? '—'}</td></tr>`).join('') : '<tr><td colspan="5">No completed turns yet.</td></tr>';

  const requestedLevel = $('#diagnosticLogLevel')?.value || '';
  const logs = (data?.recent_logs || []).filter(entry => {
    if (!requestedLevel) return true;
    const ranks = { INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };
    return (ranks[entry.level] || 0) >= (ranks[requestedLevel] || 0);
  });
  $('#diagnosticLogList').innerHTML = logs.length ? [...logs].reverse().slice(0, 80).map(entry => `<div class="diagnostic-log-entry level-${String(entry.level || '').toLowerCase()}"><span>${escapeHtml(entry.level || 'INFO')}</span><div><strong>${escapeHtml(entry.logger || '')}</strong><p>${escapeHtml(entry.message || '')}</p><small>${escapeHtml(entry.timestamp || '')} · ${escapeHtml(entry.process || '')}</small></div></div>`).join('') : '<div class="queue-empty">No logs match this filter.</div>';
  renderDiagnosticSelfTest(data?.self_test);
  renderSoakStatus(data?.soak || {});
}

async function loadDiagnostics(showToast = false) {
  if (!diagnosticsBackendSupported()) {
    renderDiagnosticsUnavailable();
    return null;
  }
  try {
    const data = await api('/api/diagnostics');
    setDiagnosticControlsDisabled(false);
    renderDiagnostics(data);
    if (showToast) toast('Diagnostics refreshed.');
    return data;
  } catch (error) {
    if (error.status === 404) {
      renderDiagnosticsUnavailable('The diagnostics API returned 404 Not Found. The running Python backend is older than the dashboard files or was not restarted after the update.');
      return null;
    }
    throw error;
  }
}

function setMode(mode) {
  appState.mode = mode || 'idle';
  const active = mode !== 'idle';
  $('#modeBadge').textContent = mode.toUpperCase();
  $('#modeBadge').classList.toggle('active', active);
  $('#togglePttBtn').textContent = appState.pttToggleActive ? 'Stop host push to talk' : 'Start host push to talk';
  const mobileMode = $('#mobileConversationBtn');
  if (mobileMode) {
    const running = mode === 'conversation';
    mobileMode.innerHTML = running ? '<span>■</span><b>Stop mode</b>' : '<span>▶</span><b>Start mode</b>';
    mobileMode.classList.toggle('active', running);
  }
  if (mode === 'conversation') setLiveStatus('listening', 'Conversation mode', 'Listening on the Windows host');
  else if (mode === 'ptt') setLiveStatus('recording', 'Host push to talk', 'Recording the Windows host microphone');
  else if (mode === 'browser_ptt') setLiveStatus('recording', 'Dashboard device PTT', 'Recording this phone or browser microphone');
  else if (mode === 'processing') setLiveStatus('thinking', 'Processing speech', 'The Windows host is transcribing the dashboard recording');
  else setLiveStatus('idle', 'Ready', 'Waiting for input');
}

function setLiveStatus(kind, title, detail) {
  const box = $('#liveStatus');
  box.className = `live-status ${kind}`;
  $('#liveStatusTitle').textContent = title;
  $('#liveStatusDetail').textContent = detail;
}

function setSpeaking(active, text = '', meta = {}) {
  $('.audio-bars').classList.toggle('active', active);
  $('#nowSpeakingText').textContent = active ? (text || 'Preparing speech…') : 'Nothing is playing.';
  if (active) {
    const provider = meta.provider || (meta.phase === 'preparing' ? 'preparing' : appState.activeAgent?.tts_mode || 'TTS');
    const suffix = meta.cached ? ' · cached' : '';
    $('#ttsProviderStatus').textContent = `${provider}${suffix}`;
    const detail = meta.phase === 'generating' ? 'Generating the next sentence on the Windows host' : 'Audio is playing through the Windows host';
    setLiveStatus('speaking', meta.phase === 'generating' ? 'Preparing speech' : 'Speaking', detail);
  } else {
    $('#ttsProviderStatus').textContent = appState.activeAgent?.kokoro_voice_name || appState.activeAgent?.tts_mode || 'TTS';
    if (appState.mode === 'conversation') setLiveStatus('listening', 'Conversation mode', 'Listening on the Windows host');
    else setLiveStatus('idle', 'Ready', 'Waiting for input');
  }
}

function handleEvent(message) {
  const { event, data } = message;
  switch (event) {
    case 'connected': setMode(data?.mode || 'idle'); break;
    case 'mode_changed':
      if (data?.recording === false) {
        appState.pttToggleActive = false; appState.holdPttActive = false; hostPttButtons().forEach(button => button.classList.remove('active'));
        if (data?.input_source === 'browser') { appState.browserPttHeld = false; appState.browserPttActive = false; browserPttButtons().forEach(button => button.classList.remove('active')); }
      }
      setMode(data?.mode || 'idle');
      break;
    case 'listening':
      if (data?.active) setLiveStatus('listening', 'Listening', 'Waiting for speech on the Windows host');
      break;
    case 'stt_started': setLiveStatus('thinking', 'Transcribing', 'FunASR is processing speech'); break;
    case 'assistant_start': beginAssistantStream(data); break;
    case 'assistant_token': appendAssistantToken(data); break;
    case 'assistant_complete': completeAssistantStream(data); break;
    case 'message_added': appendMessage(data); break;
    case 'tts_started': setSpeaking(true, data?.text, { phase: data?.phase || 'preparing' }); break;
    case 'tts_chunk_generating': setSpeaking(true, data?.text, { phase: 'generating' }); break;
    case 'tts_chunk': setSpeaking(true, data?.text, { phase: 'playing', provider: data?.provider, cached: data?.cached }); break;
    case 'tts_stopped': setSpeaking(false); break;
    case 'transcript':
      if (data?.accepted === false) appendRejectedTranscript(data);
      else toast(`Heard (${data?.confidence_percent ?? '?'}% estimated): ${data.text}`);
      break;
    case 'pipeline_state':
      appState.pipeline = data || appState.pipeline;
      if (appState.data) appState.data.pipeline = appState.pipeline;
      renderRuntimeStatus({ ...(appState.data || {}), pipeline: appState.pipeline });
      break;
    case 'queue_state': appState.queueState = data.state; appState.queue = data.items || []; renderQueue(); break;
    case 'agents_changed': appState.agents = data || []; renderAgents(); break;
    case 'information_changed': appState.information = data || []; renderInformation(); break;
    case 'plugins_changed': appState.plugins = data || { plugins: [], summary: {} }; if (appState.data) appState.data.plugins = appState.plugins; renderPlugins(); break;
    case 'scripts_changed': appState.scripts = data || []; renderScripts(); break;
    case 'agent_changed':
      appState.activeAgent = data.agent; appState.conversation = data.conversation;
      refreshAgentWorkspace();
      break;
    case 'conversation_changed':
      appState.conversation = data;
      refreshConversationsAndMessages();
      break;
    case 'conversation_cleared':
      if (data.conversation_id === appState.conversation?.id) { appState.messages = []; renderMessages(); }
      break;
    case 'models_changed': appState.models = data || []; appState.data.ollama_error = null; renderModels(); break;
    case 'model_pull': toast(`${data.model}: ${data.status}`); break;
    case 'runtime_settings_changed': appState.data.runtime_settings = data; renderSettings(); break;
    case 'audio_lock_changed':
      appState.data.audio = { ...(appState.data.audio || {}), ...(data || {}) };
      $('#audioDeviceStatus').textContent = data?.input_locked
        ? 'Persistent audio lock active: microphone and speaker streams are both open.'
        : (data?.output_locked ? 'Microphone released; speaker output remains locked for scripts and TTS.' : 'Audio locks released.');
      renderRuntimeStatus(appState.data);
      break;
    case 'takeover_request': showTakeoverModal(data); break;
    case 'control_revoked': resetToLogin('Control was transferred to another device.'); break;
    case 'reload_required': location.reload(); break;
    case 'error': toast(data?.message || 'Runtime error', 'error'); setLiveStatus('idle', 'Ready', 'Waiting for input'); break;
    default: break;
  }
}

async function refreshAgentWorkspace() {
  try {
    const data = await api('/api/bootstrap');
    appState.data = data;
    appState.agents = data.agents;
    appState.activeAgent = data.active_agent;
    appState.conversation = data.conversation;
    appState.conversations = data.conversations;
    appState.messages = data.messages;
    appState.information = data.information;
    appState.plugins = data.plugins || appState.plugins;
    appState.scripts = data.scripts;
    appState.queue = data.queue;
    appState.models = data.models;
    appState.kokoroVoices = data.kokoro_voices || appState.kokoroVoices;
    appState.version = data.version || appState.version;
    appState.pipeline = data.pipeline || appState.pipeline;
    renderAll();
    navigate('chat');
  } catch (error) { toast(error.message, 'error'); }
}

async function refreshConversationsAndMessages() {
  try {
    const conversations = await api(`/api/agents/${appState.activeAgent.id}/conversations`);
    appState.conversations = conversations;
    const result = await api(`/api/conversations/${appState.conversation.id}`);
    appState.messages = result.messages;
    renderConversations(); renderMessages();
  } catch (error) { toast(error.message, 'error'); }
}

function navigate(page) {
  $$('.page').forEach(node => node.classList.toggle('active', node.id === `page-${page}`));
  $$('.nav-item, .mobile-bottom-nav button').forEach(node => node.classList.toggle('active', node.dataset.page === page));
  const titles = { chat: ['VOICE WORKSPACE', 'Conversation'], agents: ['CONFIGURATION', 'Agents'], information: ['KNOWLEDGE', 'Information'], plugins: ['CAPABILITIES', 'Plugins'], scripts: ['DIRECT SPEECH', 'Scripts & Queue'], settings: ['SYSTEM', 'Settings'] };
  $('#pageEyebrow').textContent = titles[page]?.[0] || '';
  $('#pageTitle').textContent = titles[page]?.[1] || page;
  closeMobileNav();
}

function openMobileNav() {
  $('#sidebar').classList.add('open');
  $('#sidebarBackdrop').classList.remove('hidden');
}
function closeMobileNav() {
  $('#sidebar').classList.remove('open');
  $('#sidebarBackdrop').classList.add('hidden');
}

function closeModal() { $('#modalRoot').innerHTML = ''; }

function showTakeoverModal(data) {
  const root = $('#modalRoot');
  root.innerHTML = `<div class="modal-shell"><div class="modal-backdrop"></div><div class="modal-card"><div class="modal-header"><h3>Controller takeover request</h3></div><p><strong>${escapeHtml(data.client_name || 'Another device')}</strong> entered the correct PIN and wants control.</p><p class="muted">Approving will disconnect this browser as the controller.</p><div class="modal-footer"><button id="rejectTakeover" class="btn ghost">Reject</button><button id="approveTakeover" class="btn danger">Approve takeover</button></div></div></div>`;
  $('#rejectTakeover').onclick = () => respondTakeover(data.request_id, false);
  $('#approveTakeover').onclick = () => respondTakeover(data.request_id, true);
}

async function respondTakeover(requestId, approve) {
  try {
    await api('/api/auth/takeover/respond', { method: 'POST', body: JSON.stringify({ request_id: requestId, approve }) });
    closeModal();
    if (approve) resetToLogin('Control was transferred.');
    else toast('Takeover rejected.');
  } catch (error) { toast(error.message, 'error'); closeModal(); }
}

const AGENT_LANGUAGE_PROFILES = {
  en: { label: 'English', sttModel: 'iic/SenseVoiceSmall', localePrefix: 'en-', defaultVoice: 'en-US-AriaNeural', preview: 'Hello. This is a preview of the selected English voice.' },
  id: { label: 'Bahasa Indonesia', sttModel: 'Whisper-base', localePrefix: 'id-', defaultVoice: 'id-ID-GadisNeural', preview: 'Halo. Ini adalah contoh suara Bahasa Indonesia yang dipilih.' },
};

function languageProfile(language = 'en') {
  return AGENT_LANGUAGE_PROFILES[language] || AGENT_LANGUAGE_PROFILES.en;
}

function edgeVoicesForLanguage(language = 'en') {
  const profile = languageProfile(language);
  const voices = appState.edgeVoices?.voices || [];
  return voices.filter(voice => String(voice.locale || '').toLowerCase().startsWith(profile.localePrefix));
}

function applyLanguageTtsAvailability(select, language = 'en') {
  if (!select) return;
  const indonesian = language === 'id';
  [...select.options].forEach(option => {
    option.disabled = indonesian && option.value !== 'edge';
  });
  if (indonesian) select.value = 'edge';
}

function renderStandaloneEdgeVoiceSelect(select, language = 'en', selectedVoice = '') {
  if (!select) return;
  const profile = languageProfile(language);
  const voices = edgeVoicesForLanguage(language);
  const available = [...voices];
  if (selectedVoice && !available.some(voice => voice.short_name === selectedVoice)) {
    const selected = (appState.edgeVoices?.voices || []).find(voice => voice.short_name === selectedVoice);
    if (selected) available.unshift(selected);
  }
  if (!available.length) {
    available.push({ short_name: profile.defaultVoice, name: profile.defaultVoice, locale: language === 'id' ? 'id-ID' : 'en-US', gender: 'Unknown' });
  }
  select.innerHTML = available.map(voice => `<option value="${escapeHtml(voice.short_name)}">${escapeHtml(edgeVoiceLabel(voice))}</option>`).join('');
  select.value = selectedVoice && available.some(voice => voice.short_name === selectedVoice) ? selectedVoice : profile.defaultVoice;
  if (!select.value) select.selectedIndex = 0;
}

function edgeVoiceLabel(voice) {
  const name = voice.name || voice.short_name || 'Voice';
  const locale = voice.locale || 'unknown locale';
  const gender = voice.gender || 'Unknown';
  return `${name} — ${locale} · ${gender}`;
}

function renderEdgeVoiceOptions(selectedVoice = '', language = 'en') {
  const select = $('#edgeVoiceSelect');
  const localeFilter = $('#edgeVoiceLocaleFilter');
  if (!select || !localeFilter) return;
  const allVoices = appState.edgeVoices?.voices || [];
  const profile = languageProfile(language);
  const voices = allVoices.filter(voice => String(voice.locale || '').toLowerCase().startsWith(profile.localePrefix));
  const locales = [...new Set(voices.map(voice => voice.locale).filter(Boolean))].sort();
  const currentLocale = localeFilter.value;
  localeFilter.innerHTML = `<option value="">All locales</option>${locales.map(locale => `<option value="${escapeHtml(locale)}">${escapeHtml(locale)}</option>`).join('')}`;
  localeFilter.value = locales.includes(currentLocale) ? currentLocale : '';
  const filtered = localeFilter.value ? voices.filter(voice => voice.locale === localeFilter.value) : voices;
  const available = [...filtered];
  if (selectedVoice && !available.some(voice => voice.short_name === selectedVoice)) {
    const selected = allVoices.find(voice => voice.short_name === selectedVoice);
    available.unshift(selected || { short_name: selectedVoice, name: selectedVoice, locale: 'custom', gender: 'Unknown' });
  }
  select.innerHTML = available.map(voice => `<option value="${escapeHtml(voice.short_name)}">${escapeHtml(edgeVoiceLabel(voice))}</option>`).join('');
  if (!available.length) {
    select.innerHTML = `<option value="${escapeHtml(profile.defaultVoice)}">${escapeHtml(profile.defaultVoice)}</option>`;
  }
  select.value = selectedVoice || available[0]?.short_name || profile.defaultVoice;
  if (!select.value) select.value = profile.defaultVoice;
  const status = $('#edgeVoiceStatus');
  if (status) {
    const source = appState.edgeVoices?.source === 'live' || appState.edgeVoices?.source === 'live-cache' ? 'online catalogue' : 'bundled fallback list';
    status.textContent = `${voices.length || 1} voices loaded from the ${source}.${appState.edgeVoices?.error ? ` Last refresh: ${appState.edgeVoices.error}` : ''}`;
  }
}

async function loadEdgeVoices(refresh = false, selectedVoice = '', language = 'en') {
  const payload = await api(`/api/tts/edge-voices?refresh=${refresh ? 'true' : 'false'}`);
  appState.edgeVoices = payload || appState.edgeVoices;
  renderEdgeVoiceOptions(selectedVoice || $('#edgeVoiceSelect')?.value || '', language);
  return payload;
}

function agentDefaults() {
  return {
    name: 'New Agent', color: '#6c63ff', avatar: 'NA', role: 'General voice assistant',
    system_prompt: 'You are a friendly, clear, and concise voice assistant. Describe your identity, domain, personality, tone, and speaking style here.',
    greeting: 'Hello. How can I help you?', llm_model: appState.models.find(model => model.name === 'qwen3.5:0.8b')?.name || appState.models[0]?.name || 'qwen3.5:0.8b',
    temperature: 0.2, top_p: 0.8, max_tokens: 224, context_size: 4096, language: 'en', tts_mode: 'edge_fallback',
    edge_voice: 'en-US-AriaNeural', kokoro_voice_id: 0, tts_rate: 1.0, tts_volume: 1.0,
    stt_model: 'iic/SenseVoiceSmall', tools_enabled: ['get_current_time','get_location','get_weather','handle_exit_intent'], info_ids: [],
  };
}

function openAgentModal(agentId = null) {
  const agent = agentId ? appState.agents.find(item => item.id === Number(agentId)) : agentDefaults();
  if (!agent) return;
  const fragment = $('#agentModalTemplate').content.cloneNode(true);
  $('#modalRoot').replaceChildren(fragment);
  $('#agentModalTitle').textContent = agentId ? `Edit ${agent.name}` : 'Create agent';
  const form = $('#agentForm');
  for (const [key, value] of Object.entries(agent)) {
    const field = form.elements.namedItem(key);
    if (field && !['tools_enabled','info_ids'].includes(key)) field.value = value ?? '';
  }
  const modelSelect = form.elements.namedItem('llm_model');
  const modelNames = [...new Set([agent.llm_model, ...appState.models.map(model => model.name || model.model)].filter(Boolean))];
  modelSelect.innerHTML = modelNames.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
  modelSelect.value = agent.llm_model;
  const languageSelect = form.elements.namedItem('language');
  const sttModelInput = form.elements.namedItem('stt_model');
  const applyAgentLanguage = (forceDefaultVoice = false) => {
    const language = languageSelect.value || 'en';
    const profile = languageProfile(language);
    sttModelInput.value = profile.sttModel;
    const currentVoice = forceDefaultVoice ? profile.defaultVoice : (form.elements.namedItem('edge_voice').value || profile.defaultVoice);
    renderEdgeVoiceOptions(currentVoice, language);
    applyLanguageTtsAvailability(form.elements.namedItem('tts_mode'), language);
  };
  applyAgentLanguage(false);
  languageSelect.onchange = () => applyAgentLanguage(true);
  $('#edgeVoiceLocaleFilter').onchange = () => renderEdgeVoiceOptions($('#edgeVoiceSelect').value, languageSelect.value);
  $('#refreshEdgeVoicesBtn').onclick = async () => {
    const button = $('#refreshEdgeVoicesBtn');
    button.disabled = true; button.textContent = 'Refreshing…';
    try {
      const payload = await loadEdgeVoices(true, $('#edgeVoiceSelect').value, languageSelect.value);
      toast(payload.source === 'live' ? 'Edge voice catalogue refreshed.' : 'Using the bundled Edge voice list.', payload.error ? 'error' : 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = '↻ Refresh Edge voices'; }
  };
  $('#previewEdgeVoiceBtn').onclick = async () => {
    const button = $('#previewEdgeVoiceBtn');
    button.disabled = true; button.textContent = 'Playing…';
    try {
      await api('/api/tts/edge-voice-preview', {
        method: 'POST',
        body: JSON.stringify({
          voice: $('#edgeVoiceSelect').value,
          rate: Number(form.elements.namedItem('tts_rate').value || 1),
          volume: Number(form.elements.namedItem('tts_volume').value || 1),
          text: languageSelect.value === 'id' ? `Halo. Ini adalah ${agent.name || 'VerbaNode'} menggunakan suara Edge yang dipilih.` : `Hello. This is ${agent.name || 'VerbaNode'} using the selected Edge voice.`,
        }),
      });
      toast('Edge voice preview completed.', 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = '▶ Preview selected voice'; }
  };
  loadEdgeVoices(false, agent.edge_voice || languageProfile(agent.language).defaultVoice, agent.language || 'en').catch(() => {});
  const voiceSelect = form.elements.namedItem('kokoro_voice_id');
  const voices = appState.kokoroVoices.length ? appState.kokoroVoices : [
    { id: 0, name: 'af_maple', category: 'American female' },
    { id: 1, name: 'af_sol', category: 'American female' },
    { id: 2, name: 'bf_vale', category: 'British female' },
  ];
  voiceSelect.innerHTML = voices.map(voice => `<option value="${voice.id}">${escapeHtml(voice.name)} — ${escapeHtml(voice.category)}</option>`).join('');
  voiceSelect.value = String(agent.kokoro_voice_id ?? 0);
  const reportedPlugins = appState.plugins?.plugins || [];
  const fallbackTools = [
    { id: 'get_current_time', name: 'Current time', enabled: true },
    { id: 'get_location', name: 'Configured location', enabled: true },
    { id: 'get_weather', name: 'Weather', enabled: true },
    { id: 'handle_exit_intent', name: 'Stop conversation intent', enabled: true },
  ];
  const usablePlugins = reportedPlugins.filter(plugin => plugin.status !== 'load_error');
  const tools = usablePlugins.length ? usablePlugins : fallbackTools;
  $('#toolCheckboxes').innerHTML = tools.map(plugin => `<label class="check-item ${plugin.enabled ? '' : 'tool-globally-disabled'}"><input type="checkbox" name="tool" value="${escapeHtml(plugin.id)}" ${(agent.tools_enabled || []).includes(plugin.id) ? 'checked' : ''} ${plugin.enabled ? '' : 'disabled'}><span><strong>${escapeHtml(plugin.name)}</strong><small>${escapeHtml(plugin.id)}${plugin.enabled ? '' : ' · globally disabled'}</small></span></label>`).join('');
  $('#agentInfoCheckboxes').innerHTML = appState.information.map(item => `<label class="check-item"><input type="checkbox" name="info" value="${item.id}" ${(agent.info_ids || []).includes(item.id) ? 'checked' : ''}><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.content.slice(0,130))}</small></span></label>`).join('') || '<div class="queue-empty">Create global information entries first.</div>';
  const conversations = agentId ? appState.conversations.filter(() => agent.id === appState.activeAgent?.id) : [];
  $('#agentMemoryStats').innerHTML = agentId ? `<strong>${conversations.length || 'Saved'} conversation workspace</strong><br>Complete history is stored, but VerbaNode only sends a short recent selection and summary when the request explicitly needs prior context.` : 'Save the agent before managing memory.';
  $('#backupAgentBtn').disabled = !agentId;
  $('#clearAgentMemoryBtn').disabled = !agentId;
  wireModalBasics();
  $$('#agentTabs button').forEach(button => button.onclick = () => {
    $$('#agentTabs button').forEach(item => item.classList.toggle('active', item === button));
    $$('.tab-panel', form).forEach(panel => panel.classList.toggle('active', panel.dataset.panel === button.dataset.tab));
  });
  $('#generateRoleBtn').onclick = async () => {
    const description = $('#roleDescription').value.trim();
    if (!description) return toast('Describe the agent first.', 'error');
    const button = $('#generateRoleBtn'); button.disabled = true; button.textContent = 'Generating…';
    try {
      const result = await api('/api/agents/generate-role', { method: 'POST', body: JSON.stringify({ description, model: modelSelect.value }) });
      form.elements.namedItem('role').value = result.role;
      form.elements.namedItem('system_prompt').value = result.system_prompt;
      form.elements.namedItem('greeting').value = result.greeting;
      toast('Role configuration generated.', 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = 'Generate identity, character, and greeting'; }
  };
  $('#backupAgentBtn').onclick = () => downloadAuthenticated(`/api/agents/${agent.id}/backup`, `agent-${agent.id}-backup.json`);
  $('#clearAgentMemoryBtn').onclick = async () => {
    if (!confirm(`Clear all conversations and summaries for ${agent.name}?`)) return;
    try { await api(`/api/agents/${agent.id}/memory`, { method: 'DELETE' }); toast('Agent memory cleared.', 'success'); closeModal(); await refreshAgentWorkspace(); }
    catch (error) { toast(error.message, 'error'); }
  };
  form.onsubmit = async event => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form).entries());
    const payload = {
      name: values.name, color: values.color, avatar: values.avatar, role: values.role,
      system_prompt: values.system_prompt, greeting: values.greeting, llm_model: values.llm_model,
      temperature: Number(values.temperature), top_p: Number(values.top_p), max_tokens: Number(values.max_tokens), context_size: Number(values.context_size),
      language: values.language, tts_mode: values.tts_mode, edge_voice: values.edge_voice, kokoro_voice_id: Number(values.kokoro_voice_id),
      tts_rate: Number(values.tts_rate), tts_volume: Number(values.tts_volume), stt_model: values.stt_model,
      tools_enabled: $$('input[name="tool"]:checked', form).map(input => input.value),
      info_ids: $$('input[name="info"]:checked', form).map(input => Number(input.value)),
    };
    try {
      if (agentId) await api(`/api/agents/${agentId}`, { method: 'PUT', body: JSON.stringify(payload) });
      else await api('/api/agents', { method: 'POST', body: JSON.stringify(payload) });
      closeModal();
      appState.agents = await api('/api/agents');
      renderAgents();
      toast(`Agent ${agentId ? 'updated' : 'created'}.`, 'success');
    } catch (error) { toast(error.message, 'error'); }
  };
}

function wireModalBasics() { $$('[data-close-modal]').forEach(node => node.onclick = closeModal); }

function openSimpleModal(kind, item = null) {
  const fragment = $('#simpleModalTemplate').content.cloneNode(true);
  $('#modalRoot').replaceChildren(fragment);
  const form = $('#simpleModalForm');
  const title = kind === 'info' ? `${item ? 'Edit' : 'Add'} information` : `${item ? 'Edit' : 'Create'} script`;
  $('#simpleModalTitle').textContent = title;
  if (kind === 'info') {
    $('#simpleModalFields').innerHTML = `<label>Title<input name="title" required value="${escapeHtml(item?.title || '')}"></label><label>Full text<textarea name="content" rows="10" required>${escapeHtml(item?.content || '')}</textarea></label><label class="toggle-row"><span><strong>Enabled</strong></span><input name="enabled" type="checkbox" ${item?.enabled !== 0 ? 'checked' : ''}><i></i></label>`;
  } else {
    const language = item?.language || 'en';
    const profile = languageProfile(language);
    $('#simpleModalFields').innerHTML = `
      <label>Button title<input name="title" required value="${escapeHtml(item?.title || '')}"></label>
      <label>Spoken text<textarea name="text" rows="8" required>${escapeHtml(item?.text || '')}</textarea></label>
      <div class="form-grid two">
        <label>Language<select name="language"><option value="en">English</option><option value="id">Bahasa Indonesia</option></select></label>
        <label>TTS mode<select name="tts_mode"><option value="edge">Edge only</option><option value="kokoro">Kokoro local only</option><option value="edge_fallback">Edge → Kokoro fallback</option><option value="kokoro_fallback">Kokoro → Edge fallback</option></select></label>
        <label>Edge voice<select name="edge_voice" id="scriptEdgeVoiceSelect"></select></label>
        <label>Kokoro voice<select name="kokoro_voice_id" id="scriptKokoroVoiceSelect"></select></label>
        <label>Speech rate<input name="tts_rate" type="number" min="0.5" max="2" step="0.05" value="${Number(item?.tts_rate ?? 1)}"></label>
        <label>Volume<input name="tts_volume" type="number" min="0" max="1" step="0.05" value="${Number(item?.tts_volume ?? 1)}"></label>
      </div>
      <button type="button" id="previewScriptVoiceBtn" class="btn secondary">▶ Preview script voice</button>
      <label class="toggle-row"><span><strong>Enabled</strong></span><input name="enabled" type="checkbox" ${item?.enabled !== 0 ? 'checked' : ''}><i></i></label>
      ${item ? '<button type="button" id="deleteSimpleItem" class="btn danger-outline">Delete</button>' : ''}`;
    form.elements.namedItem('language').value = language;
    form.elements.namedItem('tts_mode').value = item?.tts_mode || 'edge';
    const populateScriptVoices = (forceDefault = false) => {
      const selectedLanguage = form.elements.namedItem('language').value || 'en';
      const selectedProfile = languageProfile(selectedLanguage);
      renderStandaloneEdgeVoiceSelect(
        $('#scriptEdgeVoiceSelect'),
        selectedLanguage,
        forceDefault ? selectedProfile.defaultVoice : (item?.edge_voice || selectedProfile.defaultVoice),
      );
      applyLanguageTtsAvailability(form.elements.namedItem('tts_mode'), selectedLanguage);
    };
    populateScriptVoices(false);
    form.elements.namedItem('language').onchange = () => populateScriptVoices(true);
    const scriptKokoro = $('#scriptKokoroVoiceSelect');
    const scriptVoices = appState.kokoroVoices.length ? appState.kokoroVoices : [{ id: 0, name: 'af_maple', category: 'American female' }];
    scriptKokoro.innerHTML = scriptVoices.map(voice => `<option value="${voice.id}">${escapeHtml(voice.name)} — ${escapeHtml(voice.category)}</option>`).join('');
    scriptKokoro.value = String(item?.kokoro_voice_id ?? 0);
    $('#previewScriptVoiceBtn').onclick = async () => {
      const button = $('#previewScriptVoiceBtn');
      button.disabled = true; button.textContent = 'Playing…';
      try {
        await api('/api/tts/script-preview', {
          method: 'POST',
          body: JSON.stringify({
            text: form.elements.namedItem('text').value.trim() || languageProfile(form.elements.namedItem('language').value).preview,
            language: form.elements.namedItem('language').value,
            tts_mode: form.elements.namedItem('tts_mode').value,
            edge_voice: form.elements.namedItem('edge_voice').value,
            kokoro_voice_id: Number(form.elements.namedItem('kokoro_voice_id').value || 0),
            tts_rate: Number(form.elements.namedItem('tts_rate').value || 1),
            tts_volume: Number(form.elements.namedItem('tts_volume').value || 1),
          }),
        });
      } catch (error) { toast(error.message, 'error'); }
      finally { button.disabled = false; button.textContent = '▶ Preview script voice'; }
    };
  }
  wireModalBasics();
  if (item && $('#deleteSimpleItem')) $('#deleteSimpleItem').onclick = async () => {
    if (!confirm(`Delete ${item.title}?`)) return;
    try {
      await api(`/api/${kind === 'info' ? 'information' : 'scripts'}/${item.id}`, { method: 'DELETE' });
      closeModal();
      if (kind === 'info') { appState.information = await api('/api/information'); renderInformation(); }
      else { appState.scripts = await api('/api/scripts'); renderScripts(); }
    } catch (error) { toast(error.message, 'error'); }
  };
  form.onsubmit = async event => {
    event.preventDefault();
    const fd = new FormData(form);
    const payload = kind === 'info'
      ? { title: fd.get('title'), content: fd.get('content'), enabled: Boolean(form.elements.namedItem('enabled').checked) }
      : {
          title: fd.get('title'), text: fd.get('text'), enabled: Boolean(form.elements.namedItem('enabled').checked),
          language: fd.get('language'), tts_mode: fd.get('tts_mode'), edge_voice: fd.get('edge_voice'),
          kokoro_voice_id: Number(fd.get('kokoro_voice_id') || 0), tts_rate: Number(fd.get('tts_rate') || 1),
          tts_volume: Number(fd.get('tts_volume') || 1),
        };
    const base = kind === 'info' ? '/api/information' : '/api/scripts';
    try {
      await api(item ? `${base}/${item.id}` : base, { method: item ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      closeModal();
      if (kind === 'info') { appState.information = await api('/api/information'); renderInformation(); }
      else { appState.scripts = await api('/api/scripts'); renderScripts(); }
      toast(`${kind === 'info' ? 'Information' : 'Script'} saved.`, 'success');
    } catch (error) { toast(error.message, 'error'); }
  };
}

async function runScript(id) {
  try { await api(`/api/scripts/${id}/run-now`, { method: 'POST' }); toast('Running script now. Queue cleared.', 'success'); }
  catch (error) { toast(error.message, 'error'); }
}
async function queueScript(id) {
  try { await api(`/api/scripts/${id}/queue`, { method: 'POST' }); toast('Script added to queue.', 'success'); }
  catch (error) { toast(error.message, 'error'); }
}
async function queueAction(action) {
  const method = action === 'clear' ? 'DELETE' : 'POST';
  const path = action === 'clear' ? '/api/queue' : `/api/queue/${action}`;
  try { await api(path, { method }); }
  catch (error) { toast(error.message, 'error'); }
}

async function downloadAuthenticated(url, filename) {
  try {
    const response = await api(url);
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = href; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(href), 2000);
  } catch (error) { toast(error.message, 'error'); }
}

function openQueueDrawer() { $('#queueDrawer').classList.remove('hidden'); }
function closeQueueDrawer() { $('#queueDrawer').classList.add('hidden'); }

function bindEvents() {
  $('#loginForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = $('button[type="submit"]', event.currentTarget);
    button.disabled = true; button.textContent = 'Connecting…';
    try { await login($('#pinInput').value, $('#clientName').value || 'Browser'); }
    catch (error) { $('#loginStatus').textContent = error.message; $('#loginStatus').classList.remove('hidden'); }
    finally { button.disabled = false; button.textContent = 'Connect'; }
  });
  $('#logoutBtn').onclick = async () => { try { await api('/api/auth/logout', { method: 'POST' }); } catch (_) {} resetToLogin(); };
  $$('.nav-item, .mobile-bottom-nav button').forEach(node => node.onclick = () => navigate(node.dataset.page));
  $$('[data-nav]').forEach(node => node.onclick = () => navigate(node.dataset.nav));
  $$('[data-settings-panel]').forEach(node => node.onclick = () => activateSettingsPanel(node.dataset.settingsPanel));
  $$('[data-view-target]').forEach(node => node.onclick = () => applyExplorerView(node.dataset.viewTarget, node.dataset.viewMode));
  $('#showRejectedSttToggle').onchange = applyRejectedTranscriptVisibility;
  $('#uiTextSizeSelect').onchange = event => applyUiTextSize(event.currentTarget.value);
  $('#mobileMenuBtn').onclick = openMobileNav; $('#mobileCloseNav').onclick = closeMobileNav; $('#sidebarBackdrop').onclick = closeMobileNav;
  $('#queueQuickBtn').onclick = openQueueDrawer; $$('[data-close-drawer]').forEach(node => node.onclick = closeQueueDrawer);
  $('#drawerPlayQueue').onclick = () => queueAction('play'); $('#drawerClearQueue').onclick = () => queueAction('clear');

  const stopTts = async () => { try { await api('/api/tts/stop', { method: 'POST' }); } catch (error) { toast(error.message, 'error'); } };
  $('#stopTtsTopBtn').onclick = stopTts; $('#stopTtsBtn').onclick = stopTts;
  $('#startConversationBtn').onclick = async () => { try { await api('/api/conversation/start', { method: 'POST' }); } catch (error) { toast(error.message, 'error'); } };
  $('#stopConversationBtn').onclick = async () => { try { await api('/api/conversation/stop', { method: 'POST' }); } catch (error) { toast(error.message, 'error'); } };

  const startHold = event => { event.preventDefault(); if (appState.holdPttActive) return; appState.holdPttActive = true; hostPttButtons().forEach(button => button.classList.add('active')); wsCommand('ptt_start'); };
  const stopHold = event => { event?.preventDefault(); if (!appState.holdPttActive) return; appState.holdPttActive = false; hostPttButtons().forEach(button => button.classList.remove('active')); wsCommand('ptt_stop'); };
  hostPttButtons().forEach(hold => {
    hold.addEventListener('pointerdown', startHold);
    hold.addEventListener('pointerup', stopHold);
    hold.addEventListener('pointercancel', stopHold);
    hold.addEventListener('pointerleave', event => { if (event.buttons === 0) stopHold(event); });
    hold.addEventListener('contextmenu', event => event.preventDefault());
  });
  $('#togglePttBtn').onclick = () => {
    appState.pttToggleActive = !appState.pttToggleActive;
    wsCommand(appState.pttToggleActive ? 'ptt_start' : 'ptt_stop');
    $('#togglePttBtn').textContent = appState.pttToggleActive ? 'Stop host push to talk' : 'Start host push to talk';
  };

  browserPttButtons().forEach(browserPtt => {
    browserPtt.addEventListener('pointerdown', startBrowserPttCapture);
    browserPtt.addEventListener('pointerup', stopBrowserPttCapture);
    browserPtt.addEventListener('pointercancel', () => cancelBrowserPttCapture(false));
    browserPtt.addEventListener('contextmenu', event => event.preventDefault());
  });
  $('#mobileConversationBtn').onclick = async () => {
    try {
      await api(appState.mode === 'conversation' ? '/api/conversation/stop' : '/api/conversation/start', { method: 'POST' });
    } catch (error) { toast(error.message, 'error'); }
  };

  $('#chatForm').onsubmit = async event => {
    event.preventDefault();
    const text = $('#chatInput').value.trim();
    if (!text) return;
    $('#chatInput').value = ''; autoResizeChatInput();
    try { await api('/api/chat/send', { method: 'POST', body: JSON.stringify({ text, conversation_id: appState.conversation?.id }) }); }
    catch (error) { toast(error.message, 'error'); }
  };
  $('#chatInput').addEventListener('input', autoResizeChatInput);
  $('#chatInput').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#chatForm').requestSubmit(); } });
  $('#newChatBtn').onclick = async () => { try { appState.conversation = await api('/api/conversations', { method: 'POST', body: JSON.stringify({ title: null }) }); appState.messages = []; await refreshConversationsAndMessages(); } catch (error) { toast(error.message, 'error'); } };
  $('#conversationSelect').onchange = async event => {
    try { const result = await api(`/api/conversations/${event.target.value}`); appState.conversation = result.conversation; appState.messages = result.messages; renderMessages(); renderConversations(); }
    catch (error) { toast(error.message, 'error'); }
  };

  $('#addAgentBtn').onclick = () => openAgentModal(); $('#quickAddAgent').onclick = () => openAgentModal();
  $('#addInfoBtn').onclick = () => openSimpleModal('info'); $('#addScriptBtn').onclick = () => openSimpleModal('script');
  $('#refreshPluginsBtn').onclick = async () => { try { await refreshPlugins(true); } catch (error) { toast(error.message, 'error'); } };
  $('#reloadExternalPluginsBtn').onclick = async () => {
    const button = $('#reloadExternalPluginsBtn');
    button.disabled = true;
    try {
      appState.plugins = await api('/api/plugins/reload', { method: 'POST' });
      if (appState.data) appState.data.plugins = appState.plugins;
      renderPlugins();
      toast('External plugin folders reloaded.', 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; }
  };
  $('#resetAllPluginMetricsBtn').onclick = async () => {
    if (!confirm('Reset execution, error, and latency metrics for all loaded plugins?')) return;
    try {
      appState.plugins = await api('/api/plugins/reset-metrics', { method: 'POST' });
      if (appState.data) appState.data.plugins = appState.plugins;
      renderPlugins();
      toast('All plugin metrics reset.');
    } catch (error) { toast(error.message, 'error'); }
  };

  document.addEventListener('click', async event => {
    const target = event.target.closest('[data-edit-agent],[data-activate-agent],[data-delete-agent],[data-edit-info],[data-delete-info],[data-edit-script],[data-run-script],[data-queue-script],[data-remove-queue],[data-toggle-plugin],[data-reset-plugin],[data-reload-plugin],[data-recover-plugin]');
    if (!target) return;
    if (target.dataset.editAgent) openAgentModal(Number(target.dataset.editAgent));
    else if (target.dataset.activateAgent) {
      try { await api(`/api/agents/${target.dataset.activateAgent}/activate`, { method: 'POST' }); }
      catch (error) { toast(error.message, 'error'); }
    } else if (target.dataset.deleteAgent) {
      const agent = appState.agents.find(item => item.id === Number(target.dataset.deleteAgent));
      if (!confirm(`Delete ${agent?.name || 'this agent'} and all of its memory?`)) return;
      try { await api(`/api/agents/${target.dataset.deleteAgent}`, { method: 'DELETE' }); appState.agents = await api('/api/agents'); renderAgents(); }
      catch (error) { toast(error.message, 'error'); }
    } else if (target.dataset.editInfo) openSimpleModal('info', appState.information.find(item => item.id === Number(target.dataset.editInfo)));
    else if (target.dataset.deleteInfo) {
      const item = appState.information.find(value => value.id === Number(target.dataset.deleteInfo)); if (!confirm(`Delete ${item?.title || 'this information'}?`)) return;
      try { await api(`/api/information/${target.dataset.deleteInfo}`, { method: 'DELETE' }); appState.information = await api('/api/information'); renderInformation(); }
      catch (error) { toast(error.message, 'error'); }
    } else if (target.dataset.editScript) openSimpleModal('script', appState.scripts.find(item => item.id === Number(target.dataset.editScript)));
    else if (target.dataset.togglePlugin) {
      const pluginId = target.dataset.togglePlugin;
      const currentlyEnabled = target.dataset.enabled === 'true';
      const verb = currentlyEnabled ? 'disable' : 'enable';
      if (currentlyEnabled && !confirm(`Disable ${pluginId} globally? Agents assigned to it will not be able to call it until it is enabled again.`)) return;
      target.disabled = true;
      try {
        appState.plugins = await api(`/api/plugins/${encodeURIComponent(pluginId)}`, { method: 'PUT', body: JSON.stringify({ enabled: !currentlyEnabled }) });
        if (appState.data) appState.data.plugins = appState.plugins;
        renderPlugins();
        toast(`Plugin ${verb}d.`, 'success');
      } catch (error) { toast(error.message, 'error'); target.disabled = false; }
    } else if (target.dataset.reloadPlugin) {
      target.disabled = true;
      try {
        appState.plugins = await api(`/api/plugins/${encodeURIComponent(target.dataset.reloadPlugin)}/reload`, { method: 'POST' });
        if (appState.data) appState.data.plugins = appState.plugins;
        renderPlugins();
        toast('External plugin reloaded.', 'success');
      } catch (error) { toast(error.message, 'error'); target.disabled = false; }
    } else if (target.dataset.recoverPlugin) {
      target.disabled = true;
      try {
        appState.plugins = await api(`/api/plugins/${encodeURIComponent(target.dataset.recoverPlugin)}/recover`, { method: 'POST' });
        if (appState.data) appState.data.plugins = appState.plugins;
        renderPlugins();
        toast('Plugin recovered.', 'success');
      } catch (error) { toast(error.message, 'error'); target.disabled = false; }
    } else if (target.dataset.resetPlugin) {
      try {
        appState.plugins = await api(`/api/plugins/${encodeURIComponent(target.dataset.resetPlugin)}/reset-metrics`, { method: 'POST' });
        if (appState.data) appState.data.plugins = appState.plugins;
        renderPlugins();
        toast('Plugin metrics reset.');
      } catch (error) { toast(error.message, 'error'); }
    }
    else if (target.dataset.runScript) runScript(Number(target.dataset.runScript));
    else if (target.dataset.queueScript) queueScript(Number(target.dataset.queueScript));
    else if (target.dataset.removeQueue) { try { await api(`/api/queue/${target.dataset.removeQueue}`, { method: 'DELETE' }); } catch (error) { toast(error.message, 'error'); } }
  });

  $('#playQueueBtn').onclick = () => queueAction('play'); $('#pauseQueueBtn').onclick = () => queueAction('pause'); $('#stopQueueBtn').onclick = () => queueAction('stop'); $('#clearQueueBtn').onclick = () => queueAction('clear');
  $('#inputDeviceSelect').onchange = updateAudioDeviceHints;
  $('#outputDeviceSelect').onchange = updateAudioDeviceHints;
  $('#refreshAudioDevicesBtn').onclick = async () => {
    const status = $('#audioDeviceStatus');
    status.textContent = 'Refreshing Windows audio devices…';
    try {
      const result = await api('/api/audio/refresh', { method: 'POST' });
      appState.audioDevices = result;
      if (appState.data?.runtime_settings && result.recovery) {
        appState.data.runtime_settings.input_device = result.recovery.input_device;
        appState.data.runtime_settings.output_device = result.recovery.output_device;
      }
      renderAudioDevices();
      status.textContent = `Windows audio refreshed. Found ${appState.audioDevices.inputs.length} input and ${appState.audioDevices.outputs.length} output entries.`;
    } catch (error) {
      status.textContent = error.message;
      toast(error.message, 'error');
    }
  };
  $('#testInputDeviceBtn').onclick = async () => {
    const status = $('#audioDeviceStatus');
    status.textContent = 'Recording the selected microphone for 1.5 seconds… Speak now.';
    try {
      const result = await api('/api/audio/test-input', {
        method: 'POST',
        body: JSON.stringify({ input_device: selectedAudioDeviceId('#inputDeviceSelect'), output_device: null }),
      });
      status.textContent = `Microphone OK: ${result.device_name} (${result.hostapi}). Peak ${result.peak_percent}%, RMS ${result.rms_percent}%.`;
      toast('Microphone test completed.', 'success');
    } catch (error) {
      status.textContent = error.message;
      toast(error.message, 'error');
    }
  };
  $('#testOutputDeviceBtn').onclick = async () => {
    const status = $('#audioDeviceStatus');
    status.textContent = 'Playing a short tone through the selected speaker…';
    try {
      const result = await api('/api/audio/test-output', {
        method: 'POST',
        body: JSON.stringify({ input_device: null, output_device: selectedAudioDeviceId('#outputDeviceSelect') }),
      });
      status.textContent = `Speaker OK: ${result.device_name} (${result.hostapi}).`;
      toast('Speaker test completed.', 'success');
    } catch (error) {
      status.textContent = error.message;
      toast(error.message, 'error');
    }
  };
  $('#testDuplexLockBtn').onclick = async () => {
    const status = $('#audioDeviceStatus');
    status.textContent = 'Opening the selected speaker and microphone, then playing a tone while both streams stay active…';
    try {
      const result = await api('/api/audio/test-duplex-lock', {
        method: 'POST',
        body: JSON.stringify({
          input_device: selectedAudioDeviceId('#inputDeviceSelect'),
          output_device: selectedAudioDeviceId('#outputDeviceSelect'),
        }),
      });
      status.textContent = `Duplex lock OK: ${result.output.name} stayed active while ${result.input.name} was open.`;
      toast('Both audio devices stayed locked.', 'success');
    } catch (error) {
      status.textContent = error.message;
      toast(error.message, 'error');
    }
  };
  const saveRuntimeSettings = async () => {
    const thresholdPercent = Math.max(0, Math.min(100, Number($('#sttConfidenceThresholdInput').value)));
    const payload = {
      interruption_enabled: $('#interruptionToggle').checked,
      silence_ms: Number($('#silenceInput').value),
      max_record_seconds: Number($('#maxRecordInput').value),
      stt_confidence_filter_enabled: $('#sttConfidenceFilterToggle').checked,
      stt_confidence_threshold: thresholdPercent / 100,
      show_rejected_stt_transcripts: $('#showRejectedSttToggle').checked,
      input_device: selectedAudioDeviceId('#inputDeviceSelect'),
      output_device: selectedAudioDeviceId('#outputDeviceSelect'),
    };
    applyUiTextSize($('#uiTextSizeSelect').value);
    try {
      appState.data.runtime_settings = await api('/api/conversation/settings', { method: 'PUT', body: JSON.stringify(payload) });
      renderSettings();
      $('#audioDeviceStatus').textContent = 'Audio devices saved. Conversation mode will keep the selected microphone and speaker streams open together.';
      toast('Conversation and audio settings saved.', 'success');
    } catch (error) {
      $('#audioDeviceStatus').textContent = error.message;
      toast(error.message, 'error');
    }
  };
  $('#saveRuntimeSettingsBtn').onclick = saveRuntimeSettings;
  $('#saveAudioDevicesBtn').onclick = saveRuntimeSettings;
  $('#pullModelForm').onsubmit = async event => {
    event.preventDefault(); const model = $('#pullModelInput').value.trim(); if (!model) return;
    try { await api(`/api/models/pull/${encodeURIComponent(model)}`, { method: 'POST' }); toast(`Started pulling ${model}.`); }
    catch (error) { toast(error.message, 'error'); }
  };
  $('#refreshStatusBtn').onclick = async () => { try { const status = await api('/api/status'); renderRuntimeStatus(status); toast('Status refreshed.'); } catch (error) { toast(error.message, 'error'); } };
  $('#refreshDiagnosticsBtn').onclick = async () => { try { await loadDiagnostics(true); } catch (error) { toast(error.message, 'error'); } };
  $('#diagnosticLogLevel').onchange = () => { if (appState.diagnostics) renderDiagnostics(appState.diagnostics); };
  $('#runDiagnosticSelfTestBtn').onclick = async () => {
    const button = $('#runDiagnosticSelfTestBtn');
    button.disabled = true; button.textContent = 'Running checks…';
    try {
      const result = await api('/api/diagnostics/self-test', { method: 'POST' });
      appState.diagnostics = appState.diagnostics || {};
      appState.diagnostics.self_test = result;
      renderDiagnosticSelfTest(result);
      toast(result.overall === 'pass' ? 'System self-test passed.' : 'System self-test completed with attention required.', result.overall === 'fail' ? 'error' : 'success');
      await loadDiagnostics(false);
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = 'Run system self-test'; }
  };
  $('#startSoakTestBtn').onclick = async () => {
    const payload = { duration_minutes: Number($('#soakDurationSelect').value), interval_seconds: Number($('#soakIntervalSelect').value) };
    try {
      const soak = await api('/api/diagnostics/soak/start', { method: 'POST', body: JSON.stringify(payload) });
      appState.diagnostics = appState.diagnostics || {}; appState.diagnostics.soak = soak; renderSoakStatus(soak);
      toast('Diagnostics soak test started.', 'success');
    } catch (error) { toast(error.message, 'error'); }
  };
  $('#stopSoakTestBtn').onclick = async () => {
    try {
      const soak = await api('/api/diagnostics/soak/stop', { method: 'POST' });
      appState.diagnostics = appState.diagnostics || {}; appState.diagnostics.soak = soak; renderSoakStatus(soak);
      toast('Soak test stopped.');
    } catch (error) { toast(error.message, 'error'); }
  };
  $('#clearDiagnosticLogsBtn').onclick = async () => {
    if (!confirm('Clear the in-memory diagnostics log view? Terminal logs and saved reports are not deleted.')) return;
    try { await api('/api/diagnostics/logs', { method: 'DELETE' }); await loadDiagnostics(false); toast('Diagnostics log view cleared.'); } catch (error) { toast(error.message, 'error'); }
  };
  $('#clearLatencyHistoryBtn').onclick = async () => {
    try { await api('/api/diagnostics/turns', { method: 'DELETE' }); await loadDiagnostics(false); toast('Latency history cleared.'); } catch (error) { toast(error.message, 'error'); }
  };
  $('#downloadDiagnosticsBtn').onclick = () => downloadAuthenticated('/api/diagnostics/export', 'verbanode-diagnostics.zip');
  $('#restartAudioEngineBtn').onclick = async () => {
    if (!confirm('Restart the isolated Audio Engine? Active conversation and script playback will stop.')) return;
    const button = $('#restartAudioEngineBtn');
    button.disabled = true;
    button.textContent = 'Restarting…';
    try {
      const health = await api('/api/audio/restart-engine', { method: 'POST' });
      const status = await api('/api/status');
      renderRuntimeStatus(status);
      toast(`Audio Engine restarted in process ${health.pid}.`, 'success');
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      button.disabled = false;
      button.textContent = 'Restart Audio Engine';
    }
  };
  $('#restartAiEngineBtn').onclick = async () => {
    if (!confirm('Restart the isolated AI Engine? Active conversation and local model jobs will stop.')) return;
    const button = $('#restartAiEngineBtn');
    button.disabled = true; button.textContent = 'Restarting…';
    try {
      const health = await api('/api/ai/restart-engine', { method: 'POST' });
      renderRuntimeStatus(await api('/api/status'));
      toast(`AI Engine restarted in process ${health.pid}.`, 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = 'Restart AI Engine'; }
  };
  $('#reloadAsrModelBtn').onclick = async () => {
    const button = $('#reloadAsrModelBtn');
    button.disabled = true; button.textContent = 'Loading…';
    try {
      await api('/api/ai/reload-asr', { method: 'POST' });
      renderRuntimeStatus(await api('/api/status'));
      toast('The active ASR model was reloaded inside the AI Engine.', 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = 'Reload active ASR'; }
  };
  $('#reloadKokoroModelBtn').onclick = async () => {
    const button = $('#reloadKokoroModelBtn');
    button.disabled = true; button.textContent = 'Loading…';
    try {
      await api('/api/ai/reload-kokoro', { method: 'POST' });
      renderRuntimeStatus(await api('/api/status'));
      toast('Kokoro reloaded inside the AI Engine.', 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = 'Reload Kokoro'; }
  };
  $('#backupDownloadBtn').onclick = event => { event.preventDefault(); downloadAuthenticated('/api/backup', 'verbanode-backup.zip'); };
  $('#restoreFileInput').onchange = async event => {
    const file = event.target.files[0]; if (!file) return;
    if (!confirm('Restore this backup and replace the current database?')) { event.target.value = ''; return; }
    const body = new FormData(); body.append('file', file);
    try { await api('/api/restore', { method: 'POST', body }); toast('Backup restored. Reloading…', 'success'); setTimeout(() => location.reload(), 1000); }
    catch (error) { toast(error.message, 'error'); }
  };

  setInterval(() => {
    if (appState.token && appState.settingsPanel === 'diagnostics' && $('#page-settings')?.classList.contains('active')) {
      loadDiagnostics(false).catch(() => {});
    }
  }, 5000);

  setInterval(() => {
    // Use one heartbeat transport at a time. Sending WebSocket and HTTPS
    // heartbeats together caused repeated WinError 10054 cleanup noise on
    // Windows Proactor event loops.
    if (appState.ws?.readyState === WebSocket.OPEN) {
      wsCommand('heartbeat');
    } else if (appState.token) {
      api('/api/heartbeat', { method: 'POST' }).catch(() => {});
    }
  }, 15000);
}

function autoResizeChatInput() {
  const input = $('#chatInput'); input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 130)}px`;
}

window.addEventListener('beforeunload', () => {
  try { appState.browserPttStream?.getTracks().forEach(track => track.stop()); } catch (_) {}
});

applyUiTextSize(getStoredUiTextSize(), false);
initializeExplorerViews();
bindEvents();
updateBrowserMicSupport();
if (appState.token) {
  const status = $('#loginStatus');
  status.textContent = 'Checking saved controller session…';
  status.classList.remove('hidden');
  completeLogin(appState.token, true);
}
