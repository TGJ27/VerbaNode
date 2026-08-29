'use strict';

async function loadBootstrap() {
  const data = await api('/api/bootstrap');
  appState.data = data;
  appState.agents = data.agents || [];
  appState.knowledgeStatus = data.knowledge?.status || null;
  appState.knowledgeLibraries = data.knowledge?.libraries || [];
  appState.knowledgeDocuments = data.knowledge?.documents || [];
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
  appState.queueLoop = Boolean(data.queue_loop);
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
  renderKnowledge();
  renderPlugins();
  renderScripts();
  renderQueue();
  renderSettings();
  renderModels();
  renderRuntimeStatus(appState.data || {});
  loadAudioLibrary(false).catch(() => {});
  loadScriptDefaults().catch(() => {});
  loadTypeToTalk(true).catch(() => {});
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
  const language = agent.language === 'id' ? 'Bahasa Indonesia' : 'English';
  const stt = String(agent.stt_model || '').replace('iic/', '');
  const tts = String(agent.tts_mode || 'TTS').replaceAll('_', ' ');
  $('#chatAgentIdentity').innerHTML = `
    <div class="agent-avatar" style="background:${escapeHtml(agent.color)}">${escapeHtml(agent.avatar || 'VA')}</div>
    <div class="agent-identity-copy">
      <div class="agent-identity-title"><h3>${escapeHtml(agent.name)}</h3><span class="agent-context-chip">${escapeHtml(language)}</span></div>
      <div class="agent-context-row"><span>${escapeHtml(stt)}</span><span>${escapeHtml(tts)}</span><span>${escapeHtml(agent.llm_model)}</span></div>
    </div>`;
  document.documentElement.style.setProperty('--active-agent', agent.color || '#6c63ff');
}


const CHAT_AUTO_SCROLL_KEY = 'verbanode_chat_auto_scroll';

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

function renderKnowledge() {
  const summary = $('#knowledgeSummary');
  const list = $('#knowledgeLibraryList');
  if (!summary || !list) return;
  const status = appState.knowledgeStatus || {};
  const migration = status.legacy_information_migration || {};
  const counts = status.counts || {};
  summary.innerHTML = `
    <article class="card plugin-summary-card"><span>Libraries</span><strong>${Number(counts.libraries || appState.knowledgeLibraries.length || 0)}</strong><small>Agent-scoped collections</small></article>
    <article class="card plugin-summary-card"><span>Documents</span><strong>${Number(counts.documents || appState.knowledgeDocuments.length || 0)}</strong><small>Hybrid RAG sources</small></article>
    <article class="card plugin-summary-card"><span>Migrated</span><strong>${Number(migration.migrated_documents || 0)}</strong><small>Legacy Information documents</small></article>
    <article class="card plugin-summary-card"><span>Index</span><strong>${escapeHtml(String(migration.index_status || 'pending').toUpperCase())}</strong><small>BM25 always available; dense may be partial</small></article>`;
  const visible = appState.knowledgeLibraries.slice(0, 6);
  list.innerHTML = visible.length ? visible.map(library => {
    const docs = appState.knowledgeDocuments.filter(document => Number(document.library_id) === Number(library.id)).length;
    return `<div class="quick-script"><span><strong>${escapeHtml(library.name)}</strong><small>${docs} document${docs === 1 ? '' : 's'} · ${library.enabled ? 'enabled' : 'disabled'}</small></span><span class="chip">${Number(library.agent_count || 0)} agents</span></div>`;
  }).join('') : '<p class="tiny muted">No Knowledge Libraries yet.</p>';
  const hint = $('#knowledgeLibraryLimitHint');
  if (hint) hint.textContent = appState.knowledgeLibraries.length > visible.length
    ? `Showing ${visible.length} of ${appState.knowledgeLibraries.length} libraries. Full library/document management arrives in Phase 7.`
    : 'Phase 7 adds full document upload, search diagnostics, and library management to this page.';
  const migrationText = $('#knowledgeMigrationText');
  if (migrationText) {
    migrationText.textContent = migration.retired
      ? `Legacy Information retired successfully. ${Number(migration.migrated_documents || 0)} entries were converted into ${Number(migration.migrated_libraries || 0)} access-preserving libraries.`
      : 'Legacy migration status is unavailable.';
  }
  const badge = $('#knowledgeMigrationBadge');
  if (badge) badge.textContent = migration.retired ? 'Migrated' : 'Checking';
}

async function refreshKnowledgeOverview() {
  const [status, libraries, documents] = await Promise.all([
    api('/api/knowledge/status'),
    api('/api/knowledge/libraries'),
    api('/api/knowledge/documents'),
  ]);
  appState.knowledgeStatus = status;
  appState.knowledgeLibraries = libraries || [];
  appState.knowledgeDocuments = documents || [];
  renderKnowledge();
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
  ['#queueLoopToggle', '#drawerQueueLoopToggle'].forEach(selector => { const node = $(selector); if (node) node.checked = Boolean(appState.queueLoop); });
  const html = count ? appState.queue.map((item, index) => `<div class="queue-item" draggable="true" data-queue-id="${item.id}">
    <span class="queue-drag" title="Drag to reorder">⋮⋮</span>
    <span class="queue-number">${index + 1}</span>
    <div class="queue-copy"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.status)} · pause after <input class="queue-pause-input" data-queue-pause="${item.id}" type="number" min="0" max="3600" step="0.5" value="${Number(item.pause_after_seconds || 0)}"> sec</small></div>
    <button class="icon-btn" data-remove-queue="${item.id}" title="Remove">×</button>
  </div>`).join('') : `<div class="queue-empty">Queue is empty.<br>Add scripts or use Run now.</div>`;
  $('#queueList').innerHTML = html;
  $('#drawerQueueList').innerHTML = html;
  wireQueueDragAndPause($('#queueList'));
  wireQueueDragAndPause($('#drawerQueueList'));
}

function wireQueueDragAndPause(container) {
  if (!container) return;
  let draggedId = null;
  container.querySelectorAll('.queue-item').forEach(node => {
    node.addEventListener('dragstart', event => { draggedId = Number(node.dataset.queueId); node.classList.add('dragging'); event.dataTransfer.effectAllowed = 'move'; });
    node.addEventListener('dragend', () => { node.classList.remove('dragging'); draggedId = null; });
    node.addEventListener('dragover', event => { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; });
    node.addEventListener('drop', async event => {
      event.preventDefault();
      const targetId = Number(node.dataset.queueId);
      if (!draggedId || draggedId === targetId) return;
      const ids = appState.queue.map(item => Number(item.id));
      const from = ids.indexOf(draggedId);
      const to = ids.indexOf(targetId);
      if (from < 0 || to < 0) return;
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      try { await api('/api/queue/reorder', { method: 'PUT', body: JSON.stringify({ ordered_ids: ids }) }); }
      catch (error) { toast(error.message, 'error'); }
    });
  });
  container.querySelectorAll('[data-queue-pause]').forEach(input => {
    input.addEventListener('change', async event => {
      const queueId = Number(event.currentTarget.dataset.queuePause);
      const value = Math.max(0, Math.min(3600, Number(event.currentTarget.value || 0)));
      try { await api(`/api/queue/${queueId}`, { method: 'PATCH', body: JSON.stringify({ pause_after_seconds: value }) }); }
      catch (error) { toast(error.message, 'error'); }
    });
    input.addEventListener('dragstart', event => event.stopPropagation());
  });
}

async function setQueueLoop(enabled) {
  try {
    const result = await api('/api/queue/settings', { method: 'PUT', body: JSON.stringify({ loop: Boolean(enabled) }) });
    appState.queueLoop = Boolean(result.loop);
    renderQueue();
  } catch (error) { toast(error.message, 'error'); renderQueue(); }
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
    case 'connected':
      appState.session = data?.session || appState.session;
      appState.backendVersion = data?.server_version || appState.backendVersion;
      setMode(data?.mode || 'idle');
      break;
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
    case 'queue_state': appState.queueState = data.state; appState.queueLoop = Boolean(data.loop); appState.queue = data.items || []; renderQueue(); break;
    case 'audio_library_changed': appState.audioLibrary = data.items || []; renderAudioLibrary(); break;
    case 'audio_library_state': appState.audioLibraryPlaying = data.name || null; appState.audioLibrary = data.items || appState.audioLibrary; renderAudioLibrary(); break;
    case 'type_to_talk_queue': appState.typeToTalkState = data.state || 'idle'; appState.typeToTalkItems = data.items || []; renderTypeToTalk(); break;
    case 'type_to_talk_settings': appState.typeToTalkSettings = data.settings || appState.typeToTalkSettings; renderTypeToTalkSettings(); break;
    case 'script_defaults_changed': appState.scriptDefaults = data || null; break;
    case 'agents_changed': appState.agents = data || []; renderAgents(); break;
    case 'knowledge_changed': refreshKnowledgeOverview().catch(error => toast(error.message, 'error')); break;
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
    case 'control_revoked': resetToLogin('Control was transferred to another device.'); break;
    case 'reload_required': location.reload(); break;
    case 'error': toast(data?.message || 'Runtime error', 'error'); setLiveStatus('idle', 'Ready', 'Waiting for input'); break;
    default: break;
  }
}

function navigate(page) {
  $$('.page').forEach(node => node.classList.toggle('active', node.id === `page-${page}`));
  $$('.nav-item, .mobile-bottom-nav button').forEach(node => node.classList.toggle('active', node.dataset.page === page));
  const titles = { chat: ['VOICE WORKSPACE', 'Conversation'], agents: ['CONFIGURATION', 'Agents'], knowledge: ['KNOWLEDGE', 'Hybrid RAG'], plugins: ['CAPABILITIES', 'Plugins'], scripts: ['DIRECT SPEECH', 'Scripts & Queue'], speak: ['DIRECT TTS', 'Type to Talk'], audio: ['HOST MEDIA', 'Audio'], settings: ['SYSTEM', 'Settings'] };
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


const AGENT_LANGUAGE_PROFILES = {
  en: {
    label: 'English',
    sttModel: 'iic/SenseVoiceSmall',
    sttModels: [{ value: 'iic/SenseVoiceSmall', label: 'SenseVoiceSmall — fastest English' }],
    localePrefix: 'en-',
    defaultVoice: 'en-US-AriaNeural',
    preview: 'Hello. This is a preview of the selected English voice.',
  },
  id: {
    label: 'Bahasa Indonesia',
    sttModel: 'Whisper-base',
    sttModels: [
      { value: 'Whisper-base', label: 'Whisper Base — faster CPU' },
      { value: 'Whisper-small', label: 'Whisper Small — better accuracy' },
    ],
    localePrefix: 'id-',
    defaultVoice: 'id-ID-GadisNeural',
    preview: 'Halo. Ini adalah contoh suara Bahasa Indonesia yang dipilih.',
  },
};

function wireModalBasics() { $$('[data-close-modal]').forEach(node => node.onclick = closeModal); }

async function loadScriptDefaults() {
  if (!appState.token) return;
  appState.scriptDefaults = await api('/api/scripts/defaults');
}

function openScriptModal(item = null) {
  const fragment = $('#simpleModalTemplate').content.cloneNode(true);
  $('#modalRoot').replaceChildren(fragment);
  const form = $('#simpleModalForm');
  $('#simpleModalTitle').textContent = `${item ? 'Edit' : 'Create'} script`;
  const remembered = item || appState.scriptDefaults || {};
  const language = remembered.language || 'en';
  const profile = languageProfile(language);
  $('#simpleModalFields').innerHTML = `
    <label>Button title<input name="title" required value="${escapeHtml(item?.title || '')}"></label>
    <label>Spoken text<textarea name="text" rows="8" required>${escapeHtml(item?.text || '')}</textarea></label>
    <div class="form-grid two">
      <label>Language<select name="language"><option value="en">English</option><option value="id">Bahasa Indonesia</option></select></label>
      <label>TTS mode<select name="tts_mode"><option value="edge">Edge only</option><option value="kokoro">Kokoro local only</option><option value="edge_fallback">Edge → Kokoro fallback</option><option value="kokoro_fallback">Kokoro → Edge fallback</option></select></label>
      <label>Edge voice<select name="edge_voice" id="scriptEdgeVoiceSelect"></select></label>
      <label>Kokoro voice<select name="kokoro_voice_id" id="scriptKokoroVoiceSelect"></select></label>
      <label>Speech rate<input name="tts_rate" type="number" min="0.5" max="2" step="0.05" value="${Number(remembered.tts_rate ?? 1)}"></label>
      <label>Volume<input name="tts_volume" type="number" min="0" max="1" step="0.05" value="${Number(remembered.tts_volume ?? 1)}"></label>
    </div>
    <div id="scriptTtsCompatibilityHint" class="status-box"></div>
    <button type="button" id="previewScriptVoiceBtn" class="btn secondary">▶ Preview script voice</button>
    <p class="tiny muted">New scripts start with the speech configuration from the last script you saved. If there is no previous script configuration, VerbaNode uses the normal defaults.</p>
    <label class="toggle-row"><span><strong>Enabled</strong></span><input name="enabled" type="checkbox" ${item?.enabled !== 0 ? 'checked' : ''}><i></i></label>
    ${item ? '<button type="button" id="deleteSimpleItem" class="btn danger-outline">Delete</button>' : ''}`;
  form.elements.namedItem('language').value = language;
  form.elements.namedItem('tts_mode').value = remembered.tts_mode || 'edge';
  const populateScriptVoices = (forceDefault = false) => {
    const selectedLanguage = form.elements.namedItem('language').value || 'en';
    const selectedProfile = languageProfile(selectedLanguage);
    const preferredVoice = forceDefault
      ? selectedProfile.defaultVoice
      : (remembered.edge_voice || selectedProfile.defaultVoice);
    renderStandaloneEdgeVoiceSelect($('#scriptEdgeVoiceSelect'), selectedLanguage, preferredVoice);
    applyLanguageTtsAvailability(form.elements.namedItem('tts_mode'), selectedLanguage);
    const kokoroSelect = $('#scriptKokoroVoiceSelect');
    if (kokoroSelect) kokoroSelect.disabled = selectedLanguage === 'id';
    const compatibility = $('#scriptTtsCompatibilityHint');
    if (compatibility) compatibility.textContent = selectedLanguage === 'id'
      ? 'Bahasa Indonesia scripts use Edge TTS only. Kokoro is disabled for this language profile.'
      : 'English scripts can use Edge, Kokoro, or either fallback mode.';
  };
  populateScriptVoices(false);
  form.elements.namedItem('language').onchange = () => populateScriptVoices(true);
  const scriptKokoro = $('#scriptKokoroVoiceSelect');
  const scriptVoices = appState.kokoroVoices.length ? appState.kokoroVoices : [{ id: 0, name: 'af_maple', category: 'American female' }];
  scriptKokoro.innerHTML = scriptVoices.map(voice => `<option value="${voice.id}">${escapeHtml(voice.name)} — ${escapeHtml(voice.category)}</option>`).join('');
  scriptKokoro.value = String(remembered.kokoro_voice_id ?? 0);
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
  wireModalBasics();
  if (item && $('#deleteSimpleItem')) $('#deleteSimpleItem').onclick = async () => {
    if (!confirm(`Delete ${item.title}?`)) return;
    try {
      await api(`/api/scripts/${item.id}`, { method: 'DELETE' });
      closeModal();
      appState.scripts = await api('/api/scripts'); renderScripts();
    } catch (error) { toast(error.message, 'error'); }
  };
  form.onsubmit = async event => {
    event.preventDefault();
    const fd = new FormData(form);
    const payload = {
      title: fd.get('title'), text: fd.get('text'), enabled: Boolean(form.elements.namedItem('enabled').checked),
      language: fd.get('language'), tts_mode: fd.get('tts_mode'), edge_voice: fd.get('edge_voice'),
      kokoro_voice_id: Number(fd.get('kokoro_voice_id') || 0), tts_rate: Number(fd.get('tts_rate') || 1),
      tts_volume: Number(fd.get('tts_volume') || 1),
    };
    if (payload.language === 'id' && payload.tts_mode !== 'edge') {
      toast('Bahasa Indonesia scripts must use Edge TTS.', 'error');
      return;
    }
    if (payload.language === 'id' && !String(payload.edge_voice || '').toLowerCase().startsWith('id-')) {
      toast('Choose an Indonesian Edge voice for this script.', 'error');
      return;
    }
    if (payload.language === 'en' && String(payload.edge_voice || '').toLowerCase().startsWith('id-')) {
      toast('Choose an English Edge voice for this script.', 'error');
      return;
    }
    try {
      await api(item ? `/api/scripts/${item.id}` : '/api/scripts', { method: item ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      closeModal();
      appState.scripts = await api('/api/scripts');
      await loadScriptDefaults();
      renderScripts();
      toast('Script saved.', 'success');
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
  $('#autoScrollToggle').onclick = () => setChatAutoScroll(!appState.chatAutoScroll);
  $('#newMessagesBtn').onclick = jumpToNewestMessages;
  $('#messageList').addEventListener('scroll', clearChatUnreadIfAtBottom, { passive: true });
  updateChatAutoScrollUi();
  $('#showRejectedSttToggle').onchange = applyRejectedTranscriptVisibility;
  $('#uiTextSizeSelect').onchange = event => applyUiTextSize(event.currentTarget.value);
  $('#mobileMenuBtn').onclick = openMobileNav; $('#mobileCloseNav').onclick = closeMobileNav; $('#sidebarBackdrop').onclick = closeMobileNav;
  $('#queueQuickBtn').onclick = openQueueDrawer; $$('[data-close-drawer]').forEach(node => node.onclick = closeQueueDrawer);
  $('#drawerPlayQueue').onclick = () => queueAction('play'); $('#drawerClearQueue').onclick = () => queueAction('clear');
  $('#queueLoopToggle').onchange = event => setQueueLoop(event.currentTarget.checked);
  $('#drawerQueueLoopToggle').onchange = event => setQueueLoop(event.currentTarget.checked);

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
  const refreshKnowledgeBtn = $('#refreshKnowledgeBtn'); if (refreshKnowledgeBtn) refreshKnowledgeBtn.onclick = () => refreshKnowledgeOverview().catch(error => toast(error.message, 'error')); $('#addScriptBtn').onclick = () => openScriptModal();
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
    const target = event.target.closest('[data-edit-agent],[data-activate-agent],[data-delete-agent],[data-edit-script],[data-run-script],[data-queue-script],[data-remove-queue],[data-toggle-plugin],[data-reset-plugin],[data-reload-plugin],[data-recover-plugin]');
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
    } else if (target.dataset.editScript) openScriptModal(appState.scripts.find(item => item.id === Number(target.dataset.editScript)));
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
  $('#refreshAsrStatusBtn').onclick = async () => {
    try {
      const status = await api('/api/status');
      renderRuntimeStatus(status);
      toast('ASR status refreshed.', 'success');
    } catch (error) { toast(error.message, 'error'); }
  };
  $('#testLanguageProfileBtn').onclick = async () => {
    const button = $('#testLanguageProfileBtn');
    setAsrControlsBusy(true);
    button.textContent = 'Testing…';
    try {
      const result = await api('/api/ai/test-language-profile', { method: 'POST' });
      const status = await api('/api/status');
      renderRuntimeStatus(status);
      toast(`${result.language === 'id' ? 'Indonesian' : 'English'} profile ready: ${result.model} + ${result.voice}.`, 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally {
      setAsrControlsBusy(false);
      button.textContent = 'Test active language profile';
    }
  };
  $('#runAsrBenchmarkBtn').onclick = async () => {
    const file = $('#asrBenchmarkFile').files?.[0];
    if (!file) { toast('Choose a PCM WAV sample first.', 'error'); return; }
    const button = $('#runAsrBenchmarkBtn');
    const status = $('#asrBenchmarkStatus');
    setAsrControlsBusy(true); button.textContent = 'Benchmarking…';
    status.textContent = 'Loading and testing Whisper Base and Whisper Small. The first run can take longer if a model must be downloaded.';
    const body = new FormData(); body.append('file', file);
    try {
      const result = await api('/api/ai/benchmark-asr', { method: 'POST', body });
      const rows = result.results || [];
      $('#asrBenchmarkRows').innerHTML = rows.map(item => item.ok
        ? `<tr><td>${escapeHtml(item.model)}</td><td>${item.load_ms} ms</td><td>${item.transcription_ms} ms</td><td>${item.rtf}</td><td>${Math.round(Number(item.confidence || 0) * 100)}%</td></tr>`
        : `<tr><td>${escapeHtml(item.model)}</td><td colspan="4">${escapeHtml(item.error || 'Failed')}</td></tr>`).join('') || '<tr><td colspan="5">No result.</td></tr>';
      const fastest = rows.filter(item => item.ok).sort((a,b) => Number(a.transcription_ms) - Number(b.transcription_ms))[0];
      status.textContent = `${result.audio_seconds}s Indonesian sample tested.${fastest ? ` Fastest transcription: ${fastest.model} at ${fastest.transcription_ms} ms (RTF ${fastest.rtf}).` : ''} Active model restored to ${result.restored_model}.`;
      renderRuntimeStatus(await api('/api/status'));
    } catch (error) {
      status.textContent = error.message;
      toast(error.message, 'error');
    } finally {
      setAsrControlsBusy(false); button.textContent = 'Benchmark Base vs Small';
    }
  };
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
    setAsrControlsBusy(true); button.textContent = 'Loading…';
    try {
      await api('/api/ai/reload-asr', { method: 'POST' });
      renderRuntimeStatus(await api('/api/status'));
      toast('The active ASR model was reloaded inside the AI Engine.', 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { setAsrControlsBusy(false); button.textContent = 'Reload active ASR'; }
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
  bindDataRecoveryControls();
  bindAudioLibraryControls();
  bindTypeToTalkControls();
  setInterval(() => {
    if (appState.token && appState.settingsPanel === 'diagnostics' && $('#page-settings')?.classList.contains('active')) {
      loadDiagnostics(false).catch(() => {});
    }
  }, 5000);

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
initializeClientTransport();
