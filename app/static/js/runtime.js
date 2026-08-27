'use strict';

const FRONTEND_VERSION = '0.10.0';
const CLIENT_API_VERSION = 1;
const WEBSOCKET_PROTOCOL_VERSION = 1;
const DIAGNOSTICS_MIN_BACKEND_VERSION = '0.5.2';

const appState = {
  token: sessionStorage.getItem('verbanode_token') || '',
  ws: null,
  reconnectTimer: null,
  reconnectAttempt: 0,
  heartbeatTimer: null,
  heartbeatWatchdogTimer: null,
  lastWebSocketActivityAt: 0,
  connectionGeneration: 0,
  data: null,
  agents: [],
  information: [],
  plugins: { plugins: [], summary: {} },
  scripts: [],
  queue: [],
  queueLoop: false,
  audioLibrary: [],
  audioLibraryPlaying: null,
  typeToTalkItems: [],
  typeToTalkState: 'idle',
  typeToTalkSettings: null,
  scriptDefaults: null,
  models: [],
  kokoroVoices: [],
  edgeVoices: { voices: [], source: 'built-in-fallback', error: null },
  audioDevices: { inputs: [], outputs: [], recommended_input: null, recommended_output: null },
  version: FRONTEND_VERSION,
  backendVersion: null,
  clientInfo: null,
  session: null,
  features: {},
  settingsPanel: localStorage.getItem('verbanode_settings_panel') || 'conversation',
  activeAgent: null,
  conversation: null,
  conversations: [],
  messages: [],
  chatAutoScroll: localStorage.getItem('verbanode_chat_auto_scroll') !== 'false',
  chatUnreadMessages: 0,
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

