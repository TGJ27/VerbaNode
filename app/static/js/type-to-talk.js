
'use strict';

function currentTypeToTalkSettings() {
  return {
    language: $('#typeToTalkLanguage')?.value || 'en',
    tts_mode: $('#typeToTalkMode')?.value || 'edge',
    edge_voice: $('#typeToTalkEdgeVoice')?.value || ($('#typeToTalkLanguage')?.value === 'id' ? 'id-ID-GadisNeural' : 'en-US-AriaNeural'),
    kokoro_voice_id: Number($('#typeToTalkKokoroVoice')?.value || 0),
    tts_rate: Number($('#typeToTalkRate')?.value || 1),
    tts_volume: Number($('#typeToTalkVolume')?.value || 1),
  };
}

function renderTypeToTalkSettings() {
  const settings = appState.typeToTalkSettings || {};
  const language = settings.language === 'id' ? 'id' : 'en';
  const languageSelect = $('#typeToTalkLanguage');
  const modeSelect = $('#typeToTalkMode');
  if (languageSelect) languageSelect.value = language;
  if (modeSelect) {
    modeSelect.value = language === 'id' ? 'edge' : (settings.tts_mode || 'edge');
    modeSelect.disabled = language === 'id';
  }
  const edge = $('#typeToTalkEdgeVoice');
  if (edge) renderStandaloneEdgeVoiceSelect(edge, language, settings.edge_voice || (language === 'id' ? 'id-ID-GadisNeural' : 'en-US-AriaNeural'));
  const kokoro = $('#typeToTalkKokoroVoice');
  if (kokoro) {
    const voices = appState.kokoroVoices.length ? appState.kokoroVoices : [{ id: 0, name: 'af_maple' }];
    kokoro.innerHTML = voices.map(v => `<option value="${Number(v.id)}">${escapeHtml(v.name || `Voice ${v.id}`)}</option>`).join('');
    kokoro.value = String(settings.kokoro_voice_id ?? 0);
    kokoro.disabled = language === 'id';
  }
  if ($('#typeToTalkRate')) $('#typeToTalkRate').value = String(settings.tts_rate ?? 1);
  if ($('#typeToTalkVolume')) $('#typeToTalkVolume').value = String(settings.tts_volume ?? 1);
}

async function saveTypeToTalkSettings() {
  const payload = currentTypeToTalkSettings();
  if (payload.language === 'id') {
    payload.tts_mode = 'edge';
    if (!String(payload.edge_voice).startsWith('id-')) payload.edge_voice = 'id-ID-GadisNeural';
  } else if (String(payload.edge_voice).startsWith('id-')) {
    payload.edge_voice = 'en-US-AriaNeural';
  }
  appState.typeToTalkSettings = await api('/api/type-to-talk/settings', { method: 'PATCH', body: JSON.stringify(payload) });
  renderTypeToTalkSettings();
}

async function loadTypeToTalk(render = true) {
  if (!appState.token) return;
  const payload = await api('/api/type-to-talk');
  appState.typeToTalkItems = payload.items || [];
  appState.typeToTalkState = payload.state || 'idle';
  appState.typeToTalkSettings = payload.settings || appState.typeToTalkSettings || {};
  if (render) renderTypeToTalk();
}

function renderTypeToTalk() {
  const list = $('#typeToTalkQueue');
  if (!list) return;
  const stateNode = $('#typeToTalkState');
  if (stateNode) stateNode.textContent = appState.typeToTalkState || 'idle';
  renderTypeToTalkSettings();
  const items = appState.typeToTalkItems || [];
  if (!items.length) {
    list.innerHTML = '<div class="type-to-talk-empty">Nothing queued yet. Type below and press Enter.</div>';
    return;
  }
  list.innerHTML = items.map((item, index) => `<article class="type-to-talk-message ${item.status === 'playing' ? 'playing' : ''}" draggable="true" data-ttt-id="${item.id}">
    <div class="message-content">${escapeHtml(item.text)}</div>
    <div class="message-meta"><span>${item.status === 'playing' ? 'Speaking now' : `Queued ${index + 1}`}</span></div>
    <div class="message-actions"><button class="icon-btn compact" data-ttt-remove="${item.id}" title="Remove">×</button></div>
  </article>`).join('');
  wireTypeToTalkDrag();
  list.scrollTop = list.scrollHeight;
}

function wireTypeToTalkDrag() {
  const list = $('#typeToTalkQueue');
  if (!list) return;
  let draggedId = null;
  list.querySelectorAll('[data-ttt-id]').forEach(node => {
    node.addEventListener('dragstart', event => {
      draggedId = Number(node.dataset.tttId);
      node.classList.add('dragging');
      event.dataTransfer.effectAllowed = 'move';
    });
    node.addEventListener('dragend', () => node.classList.remove('dragging'));
    node.addEventListener('dragover', event => event.preventDefault());
    node.addEventListener('drop', async event => {
      event.preventDefault();
      const targetId = Number(node.dataset.tttId);
      if (!draggedId || draggedId === targetId) return;
      const ids = appState.typeToTalkItems.map(item => Number(item.id));
      const from = ids.indexOf(draggedId), to = ids.indexOf(targetId);
      if (from < 0 || to < 0) return;
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      try { await api('/api/type-to-talk/reorder', { method: 'PUT', body: JSON.stringify({ ordered_ids: ids }) }); await loadTypeToTalk(); }
      catch (error) { toast(error.message, 'error'); }
    });
  });
}

function bindTypeToTalkControls() {
  const form = $('#typeToTalkForm');
  const input = $('#typeToTalkInput');
  if (form) form.onsubmit = async event => {
    event.preventDefault();
    const text = input?.value.trim() || '';
    if (!text) return;
    try {
      const settings = currentTypeToTalkSettings();
      await api('/api/type-to-talk', { method: 'POST', body: JSON.stringify({ text, ...settings }) });
      appState.typeToTalkSettings = { ...settings };
      input.value = '';
      await loadTypeToTalk();
      input.focus();
    } catch (error) { toast(error.message, 'error'); }
  };
  input?.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form?.requestSubmit(); }
  });
  ['typeToTalkLanguage','typeToTalkMode','typeToTalkEdgeVoice','typeToTalkKokoroVoice','typeToTalkRate','typeToTalkVolume'].forEach(id => {
    $(`#${id}`)?.addEventListener('change', async () => { try { await saveTypeToTalkSettings(); } catch (e) { toast(e.message, 'error'); } });
  });
  $('#typeToTalkLanguage')?.addEventListener('change', () => {
    const language = $('#typeToTalkLanguage').value;
    if (language === 'id') { $('#typeToTalkMode').value = 'edge'; }
    renderTypeToTalkSettings();
  });
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
