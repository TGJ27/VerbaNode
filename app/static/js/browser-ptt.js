'use strict';

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

