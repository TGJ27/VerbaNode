'use strict';

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
  if (resolved === 'devices' && appState.token) {
    loadTrustedDevices().catch(error => toast(error.message, 'error'));
  }
  if (resolved === 'data' && appState.token) {
    loadBackupStatus().catch(error => toast(error.message, 'error'));
  }
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

function whisperCacheEntry(modelName) {
  return appState.data?.stt?.whisper_cache?.models?.[modelName]
    || appState.lastRuntimeStatus?.stt?.whisper_cache?.models?.[modelName]
    || null;
}

function whisperCacheLabel(modelName) {
  const cached = whisperCacheEntry(modelName);
  if (!cached) return '';
  if (cached.downloaded) return ` · downloaded${cached.size_mb ? ` ${cached.size_mb} MB` : ''}`;
  return ' · not downloaded';
}

function setAsrControlsBusy(busy) {
  ['refreshAsrStatusBtn', 'testLanguageProfileBtn', 'runAsrBenchmarkBtn', 'reloadAsrModelBtn'].forEach(id => {
    const button = $(`#${id}`);
    if (button) button.disabled = Boolean(busy);
  });
  const input = $('#asrBenchmarkFile');
  if (input) input.disabled = Boolean(busy);
}

function renderAsrModelStatus(data) {
  const box = $('#asrModelStatusBox');
  const list = $('#asrModelStatusList');
  const cacheNode = $('#asrModelCache');
  if (!box || !list) return;
  const stt = data?.stt || {};
  const agent = data?.active_agent || appState.activeAgent || {};
  const aiAsr = data?.ai?.engine?.remote?.asr || {};
  const selected = agent.stt_model || stt.requested_model || stt.model || 'Unknown';
  const loaded = aiAsr.model || stt.model || 'Not loaded';
  const language = agent.language === 'id' ? 'Bahasa Indonesia' : 'English';
  const fallback = stt.fallback_model;
  const stateName = String(aiAsr.state || stt.state || 'unknown');
  const busy = ['loading', 'reloading'].includes(stateName.toLowerCase());
  box.innerHTML = `<strong>${escapeHtml(String(selected))}</strong><br><span class="muted">${escapeHtml(language)} · ${escapeHtml(stateName)}${fallback ? ` · fallback active: ${escapeHtml(String(fallback))}` : ''}</span>`;
  list.innerHTML = `
    <dt>Selected by agent</dt><dd>${escapeHtml(String(selected))}</dd>
    <dt>Actually loaded</dt><dd>${escapeHtml(String(loaded))}</dd>
    <dt>Model load</dt><dd>${aiAsr.model_load_ms != null ? `${aiAsr.model_load_ms} ms` : '—'}</dd>
    <dt>Last transcription</dt><dd>${aiAsr.last_latency_ms != null ? `${aiAsr.last_latency_ms} ms` : '—'}</dd>
    <dt>Completed jobs</dt><dd>${aiAsr.jobs_completed ?? 0}</dd>
    <dt>Fallback</dt><dd>${fallback ? `${escapeHtml(String(stt.requested_model || selected))} → ${escapeHtml(String(fallback))}` : 'Not used'}</dd>
    <dt>Last error</dt><dd>${escapeHtml(String(aiAsr.last_error || stt.last_error || stt.fallback_reason || 'None'))}</dd>`;

  if (cacheNode) {
    const cache = stt.whisper_cache || {};
    const models = cache.models || {};
    cacheNode.innerHTML = ['Whisper-base', 'Whisper-small'].map(model => {
      const item = models[model] || {};
      const ready = Boolean(item.downloaded);
      const name = model === 'Whisper-base' ? 'Whisper Base' : 'Whisper Small';
      return `<div class="asr-cache-item ${ready ? 'ready' : 'missing'}"><span>${escapeHtml(name)}</span><strong>${ready ? 'Downloaded' : 'Not downloaded'}</strong><small>${ready && item.size_mb ? `${item.size_mb} MB` : ready ? 'Ready for offline loading' : 'First use will download the model'}</small></div>`;
    }).join('');
  }
  setAsrControlsBusy(busy);
}

function renderRuntimeStatus(data) {
  const tts = data.tts || {};
  const stt = data.stt || {};
  appState.lastRuntimeStatus = data;
  if (appState.data) appState.data.stt = stt;
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
  renderAsrModelStatus(data);
}
