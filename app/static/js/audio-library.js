'use strict';

function bytesHuman(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function durationHuman(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${String(whole % 60).padStart(2, '0')}`;
}

async function loadAudioLibrary(render = true) {
  if (!appState.token) return;
  const payload = await api('/api/audio-library');
  appState.audioLibrary = payload.items || [];
  appState.audioLibraryPlaying = payload.playing || null;
  if (render) renderAudioLibrary();
}

function renderAudioLibrary() {
  const grid = $('#audioLibraryGrid');
  if (!grid) return;
  const items = appState.audioLibrary || [];
  $('#audioLibraryCount').textContent = `${items.length} ${items.length === 1 ? 'file' : 'files'}`;
  $('#audioLibraryStatus').textContent = appState.audioLibraryPlaying ? `Playing: ${appState.audioLibraryPlaying}` : 'No audio playing';
  if (!items.length) {
    grid.innerHTML = '<div class="card queue-empty">No audio files yet. Upload a supported audio file.</div>';
    return;
  }
  grid.innerHTML = items.map(item => {
    const duration = durationHuman(item.duration_seconds);
    const playing = item.name === appState.audioLibraryPlaying;
    return `<article class="card audio-file-card ${playing ? 'playing' : ''}">
      <div class="audio-file-icon">♫</div>
      <div class="audio-file-copy"><h3>${escapeHtml(item.name)}</h3><p>${bytesHuman(item.size_bytes)}${duration ? ` · ${duration}` : ''}</p></div>
      <div class="audio-file-actions">
        <button class="btn ${playing ? 'success' : 'primary'} compact" data-audio-play="${encodeURIComponent(item.name)}">${playing ? '▶ Playing' : '▶ Play'}</button>
        <button class="btn ghost compact" data-audio-rename="${encodeURIComponent(item.name)}">Rename</button>
        <button class="btn danger-outline compact" data-audio-delete="${encodeURIComponent(item.name)}">Delete</button>
      </div>
    </article>`;
  }).join('');
}

function bindAudioLibraryControls() {
  const upload = $('#audioLibraryUpload');
  if (upload) upload.onchange = async event => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!file) return;
    if (!/\.(wav|mp3|mpeg|mpg|mpga|mp2|flac|ogg|oga|opus|m4a|aac|wma|aiff|aif|webm|mka|amr)$/i.test(file.name)) return toast('Choose a supported audio file.', 'error');
    const body = new FormData();
    body.append('file', file, file.name);
    try {
      await api('/api/audio-library/upload', { method: 'POST', body });
      await loadAudioLibrary();
      toast(`${file.name} uploaded.`, 'success');
    } catch (error) { toast(error.message, 'error'); }
  };
  const stop = $('#stopAudioLibraryBtn');
  if (stop) stop.onclick = async () => {
    try { await api('/api/audio-library/stop', { method: 'POST' }); await loadAudioLibrary(); }
    catch (error) { toast(error.message, 'error'); }
  };
  document.addEventListener('click', async event => {
    const play = event.target.closest('[data-audio-play]');
    const rename = event.target.closest('[data-audio-rename]');
    const remove = event.target.closest('[data-audio-delete]');
    if (!play && !rename && !remove) return;
    const encoded = play?.dataset.audioPlay || rename?.dataset.audioRename || remove?.dataset.audioDelete;
    const name = decodeURIComponent(encoded || '');
    if (!name) return;
    try {
      if (play) await api(`/api/audio-library/${encodeURIComponent(name)}/play`, { method: 'POST' });
      if (rename) {
        const next = prompt('New audio filename', name);
        if (!next || next === name) return;
        await api(`/api/audio-library/${encodeURIComponent(name)}`, { method: 'PATCH', body: JSON.stringify({ name: next }) });
      }
      if (remove) {
        if (!confirm(`Delete ${name}?`)) return;
        await api(`/api/audio-library/${encodeURIComponent(name)}`, { method: 'DELETE' });
      }
      await loadAudioLibrary();
    } catch (error) { toast(error.message, 'error'); }
  });
}
