'use strict';

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
