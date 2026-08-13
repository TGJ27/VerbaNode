'use strict';

function messageListNearBottom(list = $('#messageList'), threshold = 96) {
  return list.scrollHeight - list.scrollTop - list.clientHeight <= threshold;
}

function updateChatAutoScrollUi() {
  const list = $('#messageList');
  const toggle = $('#autoScrollToggle');
  if (list) list.classList.toggle('scroll-locked', appState.chatAutoScroll);
  if (toggle) {
    toggle.textContent = appState.chatAutoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF';
    toggle.classList.toggle('primary', appState.chatAutoScroll);
    toggle.classList.toggle('ghost', !appState.chatAutoScroll);
    toggle.setAttribute('aria-pressed', appState.chatAutoScroll ? 'true' : 'false');
    toggle.title = appState.chatAutoScroll
      ? 'Chat is locked to the newest message. Turn off to browse history.'
      : 'Browsing is unlocked. New messages will not move your scroll position.';
  }
  updateNewMessagesButton();
}

function setChatAutoScroll(enabled, persist = true) {
  appState.chatAutoScroll = Boolean(enabled);
  if (persist) localStorage.setItem(CHAT_AUTO_SCROLL_KEY, appState.chatAutoScroll ? 'true' : 'false');
  if (appState.chatAutoScroll) {
    appState.chatUnreadMessages = 0;
    scrollMessagesToBottom(true);
  }
  updateChatAutoScrollUi();
}

function updateNewMessagesButton() {
  const button = $('#newMessagesBtn');
  if (!button) return;
  const visible = !appState.chatAutoScroll && appState.chatUnreadMessages > 0;
  button.classList.toggle('hidden', !visible);
  if (visible) {
    button.textContent = `↓ ${appState.chatUnreadMessages} new ${appState.chatUnreadMessages === 1 ? 'message' : 'messages'}`;
  }
}

function markChatActivity(count = 1) {
  if (appState.chatAutoScroll) {
    scrollMessagesToBottom(true);
    return;
  }
  appState.chatUnreadMessages += Math.max(1, Number(count) || 1);
  updateNewMessagesButton();
}

function clearChatUnreadIfAtBottom() {
  if (appState.chatAutoScroll || !messageListNearBottom()) return;
  if (appState.chatUnreadMessages) {
    appState.chatUnreadMessages = 0;
    updateNewMessagesButton();
  }
}

function jumpToNewestMessages() {
  appState.chatUnreadMessages = 0;
  scrollMessagesToBottom(true);
  updateNewMessagesButton();
}

function scrollMessagesToBottom(force = false) {
  const list = $('#messageList');
  if (!list) return;
  if (force || appState.chatAutoScroll) {
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

function renderMessages() {
  const list = $('#messageList');
  const hadContent = list.scrollHeight > list.clientHeight;
  const previousTop = list.scrollTop;
  appState.streaming.clear();
  appState.chatUnreadMessages = 0;
  if (!appState.messages.length) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">◉</div><h3>Start a conversation</h3><p>Use continuous mode, push to talk, or type below. Replies will be spoken by the Windows host.</p></div>`;
    updateChatAutoScrollUi();
    return;
  }
  list.innerHTML = appState.messages.map(messageHtml).join('');
  applyRejectedTranscriptVisibility();
  updateChatAutoScrollUi();
  requestAnimationFrame(() => {
    if (appState.chatAutoScroll || !hadContent) list.scrollTop = list.scrollHeight;
    else list.scrollTop = Math.min(previousTop, Math.max(0, list.scrollHeight - list.clientHeight));
  });
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
  markChatActivity();
  setLiveStatus('idle', 'Ready', 'Low-confidence transcript was not sent');
}

function appendMessage(message) {
  const list = $('#messageList');
  $('.empty-state', list)?.remove();
  if ($(`[data-message-id="${message.id}"]`, list)) return;
  list.insertAdjacentHTML('beforeend', messageHtml(message));
  markChatActivity();
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
  markChatActivity();
  setLiveStatus('thinking', 'Generating reply', 'Ollama is producing a response');
}

function appendAssistantToken(data) {
  const stream = appState.streaming.get(data.generation_id);
  if (!stream) return;
  const list = $('#messageList');
  stream.text += data.token || '';
  $('.message-bubble', stream.node).textContent = stream.text;
  if (appState.chatAutoScroll) scrollMessagesToBottom(true);
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

async function refreshConversationsAndMessages() {
  try {
    const conversations = await api(`/api/agents/${appState.activeAgent.id}/conversations`);
    appState.conversations = conversations;
    const result = await api(`/api/conversations/${appState.conversation.id}`);
    appState.messages = result.messages;
    renderConversations(); renderMessages();
  } catch (error) { toast(error.message, 'error'); }
}
