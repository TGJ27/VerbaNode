'use strict';

async function loadTypeToTalk(render = true) {
  if (!appState.token) return;
  const payload = await api('/api/type-to-talk');
  appState.typeToTalkItems = payload.items || [];
  appState.typeToTalkState = payload.state || 'idle';
  appState.typeToTalkDefaults = payload.defaults || appState.typeToTalkDefaults || {};
  if (render) renderTypeToTalk();
}

function typeToTalkConfig() {
  return {
    language: $('#typeToTalkLanguage')?.value || 'en',
    tts_mode: $('#typeToTalkMode')?.value || 'edge',
    edge_voice: $('#typeToTalkEdgeVoice')?.value || 'en-US-AriaNeural',
    kokoro_voice_id: Number($('#typeToTalkKokoroVoice')?.value || 0),
    tts_rate: Number($('#typeToTalkRate')?.value || 1),
    tts_volume: Number($('#typeToTalkVolume')?.value || 1),
  };
}

function configureTypeToTalkVoices(forceDefault = false) {
  const language = $('#typeToTalkLanguage')?.value || 'en';
  const profile = languageProfile(language);
  const defaults = appState.typeToTalkDefaults || {};
  const edgeSelect = $('#typeToTalkEdgeVoice');
  if (edgeSelect) {
    const preferred = forceDefault ? profile.defaultVoice : (edgeSelect.value || defaults.edge_voice || profile.defaultVoice);
    renderStandaloneEdgeVoiceSelect(edgeSelect, language, preferred);
  }
  const mode = $('#typeToTalkMode');
  if (mode) applyLanguageTtsAvailability(mode, language);
  const kokoro = $('#typeToTalkKokoroVoice');
  if (kokoro) kokoro.disabled = language === 'id';
}

function initializeTypeToTalkConfig() {
  if (appState.typeToTalkConfigInitialized) return;
  const defaults = appState.typeToTalkDefaults || {};
  const language = defaults.language || 'en';
  const languageSelect = $('#typeToTalkLanguage');
  const modeSelect = $('#typeToTalkMode');
  const kokoroSelect = $('#typeToTalkKokoroVoice');
  if (languageSelect) languageSelect.value = language;
  if (modeSelect) modeSelect.value = defaults.tts_mode || 'edge';
  if (kokoroSelect) {
    const voices = appState.kokoroVoices.length ? appState.kokoroVoices : [{ id: 0, name: 'af_maple', category: 'American female' }];
    kokoroSelect.innerHTML = voices.map(voice => `<option value="${voice.id}">${escapeHtml(voice.name)} — ${escapeHtml(voice.category)}</option>`).join('');
    kokoroSelect.value = String(defaults.kokoro_voice_id ?? 0);
  }
  if ($('#typeToTalkRate')) $('#typeToTalkRate').value = String(defaults.tts_rate ?? 1);
  if ($('#typeToTalkVolume')) $('#typeToTalkVolume').value = String(defaults.tts_volume ?? 1);
  configureTypeToTalkVoices(false);
  appState.typeToTalkConfigInitialized = true;
}

function renderTypeToTalk() {
  initializeTypeToTalkConfig();
  const list = $('#typeToTalkMessages');
  const stateNode = $('#typeToTalkState');
  if (stateNode) stateNode.textContent = (appState.typeToTalkState || 'idle').replace(/^./, c => c.toUpperCase());
  if (!list) return;
  const items = appState.typeToTalkItems || [];
  if (!items.length) {
    list.innerHTML = '<div class="type-to-talk-empty">Type a message below and press Enter. VerbaNode will speak it directly without sending it to the LLM.</div>';
    return;
  }
  list.innerHTML = items.map(item => {
    const status = item.status || 'waiting';
    const statusLabel = status === 'playing' ? 'Speaking now' : status === 'completed' ? 'Spoken' : 'Queued';
    const mode = item.tts_mode || 'edge';
    const voice = mode.startsWith('kokoro') ? `Kokoro #${Number(item.kokoro_voice_id || 0)}` : (item.edge_voice || 'Edge');
    return `<div class="type-to-talk-message-row">
      <div class="type-to-talk-bubble" data-status="${escapeHtml(status)}">
        <p>${escapeHtml(item.text || '')}</p>
        <small>${escapeHtml(statusLabel)} · ${escapeHtml(voice)} · ${Number(item.tts_rate || 1).toFixed(2)}× <button class="link-btn" data-ttt-remove="${item.id}" type="button">Remove</button></small>
      </div>
    </div>`;
  }).join('');
  list.scrollTop = list.scrollHeight;
}

function bindTypeToTalkControls() {
  $('#typeToTalkLanguage')?.addEventListener('change', () => configureTypeToTalkVoices(true));
  $('#typeToTalkMode')?.addEventListener('change', () => configureTypeToTalkVoices(false));

  const input = $('#typeToTalkInput');
  input?.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      $('#typeToTalkForm')?.requestSubmit();
    }
  });

  const form = $('#typeToTalkForm');
  if (form) form.onsubmit = async event => {
    event.preventDefault();
    const text = input?.value.trim() || '';
    if (!text) return;
    const payload = { text, ...typeToTalkConfig() };
    try {
      await api('/api/type-to-talk', { method: 'POST', body: JSON.stringify(payload) });
      if (input) input.value = '';
      appState.typeToTalkDefaults = { ...payload }; delete appState.typeToTalkDefaults.text;
      await loadTypeToTalk();
      input?.focus();
    } catch (error) { toast(error.message, 'error'); }
  };
  $('#typeToTalkPlayBtn')?.addEventListener('click', async () => { try { await api('/api/type-to-talk/play', { method: 'POST' }); await loadTypeToTalk(); } catch (e) { toast(e.message, 'error'); } });
  $('#typeToTalkStopBtn')?.addEventListener('click', async () => { try { await api('/api/type-to-talk/stop', { method: 'POST' }); await loadTypeToTalk(); } catch (e) { toast(e.message, 'error'); } });
  $('#typeToTalkClearBtn')?.addEventListener('click', async () => { try { await api('/api/type-to-talk', { method: 'DELETE' }); await loadTypeToTalk(); } catch (e) { toast(e.message, 'error'); } });
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-ttt-remove]');
    if (!button) return;
    try { await api(`/api/type-to-talk/${Number(button.dataset.tttRemove)}`, { method: 'DELETE' }); await loadTypeToTalk(); }
    catch (e) { toast(e.message, 'error'); }
  });
}
