'use strict';

function renderAgents() {
  const grid = $('#agentGrid');
  grid.innerHTML = appState.agents.map(agent => {
    const active = agent.id === appState.activeAgent?.id;
    return `<article class="card agent-card ${active ? 'active' : ''}" style="--agent-color:${escapeHtml(agent.color)}">
      <div class="agent-card-head"><div class="agent-avatar" style="background:${escapeHtml(agent.color)}">${escapeHtml(agent.avatar || 'VA')}</div><div><h3>${escapeHtml(agent.name)}</h3><p>${escapeHtml(agent.role)}</p></div></div>
      <div class="agent-card-body">${escapeHtml(agent.greeting)}</div>
      <div class="agent-card-meta"><span class="chip">${agent.language === 'id' ? 'Bahasa Indonesia' : 'English'}</span><span class="chip">${escapeHtml(agent.llm_model)}</span><span class="chip">${escapeHtml(agent.tts_mode)}</span><span class="chip">${escapeHtml(agent.kokoro_voice_name || 'Kokoro voice')}</span><span class="chip">${agent.knowledge_library_ids?.length || 0} libraries</span></div>
      <div class="agent-card-actions">
        ${active ? '<button class="btn success compact" disabled>Active</button>' : `<button class="btn secondary compact" data-activate-agent="${agent.id}">Use agent</button>`}
        <button class="btn ghost compact" data-edit-agent="${agent.id}">Edit</button>
        <button class="btn danger-outline compact" data-delete-agent="${agent.id}">Delete</button>
      </div>
    </article>`;
  }).join('');
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
      appState.knowledgeStatus = data.knowledge?.status || appState.knowledgeStatus;
    appState.knowledgeLibraries = data.knowledge?.libraries || appState.knowledgeLibraries;
    appState.knowledgeDocuments = data.knowledge?.documents || appState.knowledgeDocuments;
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
    stt_model: 'iic/SenseVoiceSmall', tools_enabled: ['get_current_time','get_location','get_weather','handle_exit_intent'], info_ids: [], knowledge_library_ids: [],
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
    if (field && !['tools_enabled','info_ids','knowledge_library_ids'].includes(key)) field.value = value ?? '';
  }
  const modelSelect = form.elements.namedItem('llm_model');
  const modelNames = [...new Set([agent.llm_model, ...appState.models.map(model => model.name || model.model)].filter(Boolean))];
  modelSelect.innerHTML = modelNames.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
  modelSelect.value = agent.llm_model;
  const languageSelect = form.elements.namedItem('language');
  const sttModelSelect = form.elements.namedItem('stt_model');
  const applyAgentLanguage = (forceDefaults = false) => {
    const language = languageSelect.value || 'en';
    const profile = languageProfile(language);
    const currentStt = forceDefaults ? profile.sttModel : (sttModelSelect.value || agent.stt_model || profile.sttModel);
    sttModelSelect.innerHTML = (profile.sttModels || [{ value: profile.sttModel, label: profile.sttModel }])
      .map(model => `<option value="${escapeHtml(model.value)}">${escapeHtml(model.label + (model.value.startsWith('Whisper-') ? whisperCacheLabel(model.value) : ''))}</option>`).join('');
    sttModelSelect.value = [...sttModelSelect.options].some(option => option.value === currentStt) ? currentStt : profile.sttModel;
    sttModelSelect.disabled = false;
    const hint = $('#agentSttModelHint');
    if (hint) {
      const selectedModel = sttModelSelect.value;
      const cacheText = selectedModel.startsWith('Whisper-')
        ? (whisperCacheEntry(selectedModel)?.downloaded ? ' The selected model is already downloaded.' : ' The selected model is not cached yet; first use will download it.')
        : '';
      hint.textContent = language === 'id'
        ? `Whisper Base is faster on CPU. Whisper Small is heavier but usually more accurate for Indonesian and code-switching.${cacheText}`
        : 'SenseVoiceSmall is the fixed fast English recognizer.';
    }
    const currentVoice = forceDefaults ? profile.defaultVoice : (form.elements.namedItem('edge_voice').value || profile.defaultVoice);
    renderEdgeVoiceOptions(currentVoice, language);
    applyLanguageTtsAvailability(form.elements.namedItem('tts_mode'), language);
  };
  applyAgentLanguage(false);
  languageSelect.onchange = () => applyAgentLanguage(true);
  sttModelSelect.onchange = () => applyAgentLanguage(false);
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
  const knowledgeChoices = appState.knowledgeLibraries || [];
  let knowledgePage = 0;
  const knowledgePerPage = 8;
  const selectedKnowledgeLibraries = new Set((agent.knowledge_library_ids || []).map(Number));
  const renderKnowledgeChoices = () => {
    const box = $('#agentKnowledgeCheckboxes');
    const pager = $('#agentKnowledgePager');
    if (!box || !pager) return;
    const start = knowledgePage * knowledgePerPage;
    const visible = knowledgeChoices.slice(start, start + knowledgePerPage);
    box.innerHTML = visible.map(item => `<label class="check-item"><input type="checkbox" name="knowledge_library" value="${item.id}" ${selectedKnowledgeLibraries.has(Number(item.id)) ? 'checked' : ''}><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.description || `${item.document_count || 0} documents`)}${item.enabled ? '' : ' · disabled'}</small></span></label>`).join('') || '<div class="queue-empty">No Knowledge Libraries yet.</div>';
    const pages = Math.max(1, Math.ceil(knowledgeChoices.length / knowledgePerPage));
    pager.innerHTML = knowledgeChoices.length > knowledgePerPage
      ? `<button type="button" class="btn ghost compact" id="knowledgePrevPage" ${knowledgePage <= 0 ? 'disabled' : ''}>← Previous</button><button type="button" class="btn ghost compact" id="knowledgeNextPage" ${knowledgePage >= pages - 1 ? 'disabled' : ''}>Next → (${knowledgePage + 1}/${pages})</button>`
      : '';
    $$('input[name="knowledge_library"]', box).forEach(input => {
      input.onchange = () => {
        const value = Number(input.value);
        if (input.checked) selectedKnowledgeLibraries.add(value);
        else selectedKnowledgeLibraries.delete(value);
      };
    });
    const prev = $('#knowledgePrevPage'); if (prev) prev.onclick = () => { knowledgePage -= 1; renderKnowledgeChoices(); };
    const next = $('#knowledgeNextPage'); if (next) next.onclick = () => { knowledgePage += 1; renderKnowledgeChoices(); };
  };
  renderKnowledgeChoices();
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
      info_ids: [],
      knowledge_library_ids: [...selectedKnowledgeLibraries].sort((a, b) => a - b),
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
