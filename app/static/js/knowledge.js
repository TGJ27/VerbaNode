'use strict';

const knowledgeUi = {
  selectedLibraryId: null,
  libraryPage: 0,
  documentPage: 0,
  libraryPageSize: 6,
  documentPageSize: 6,
};

function knowledgePageSlice(items, page, size) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const resolved = Math.max(0, Math.min(page, pages - 1));
  return { page: resolved, pages, items: items.slice(resolved * size, resolved * size + size) };
}

function renderKnowledgePager(container, page, pages, kind) {
  if (!container) return;
  container.innerHTML = `<button class="btn ghost compact" data-knowledge-page="${kind}" data-delta="-1" ${page <= 0 ? 'disabled' : ''}>←</button><span class="tiny muted">${page + 1} / ${pages}</span><button class="btn ghost compact" data-knowledge-page="${kind}" data-delta="1" ${page >= pages - 1 ? 'disabled' : ''}>→</button>`;
}

function selectedKnowledgeLibrary() {
  return appState.knowledgeLibraries.find(item => Number(item.id) === Number(knowledgeUi.selectedLibraryId)) || null;
}

function renderKnowledge() {
  const summary = $('#knowledgeSummary');
  const libraryList = $('#knowledgeLibraryList');
  const documentList = $('#knowledgeDocumentList');
  if (!summary || !libraryList || !documentList) return;

  const status = appState.knowledgeStatus || {};
  const migration = status.legacy_information_migration || {};
  const counts = status.counts || {};
  const indexStatus = String(migration.index_status || 'pending');
  const total = Number(migration.index_total || 0);
  const completed = Number(migration.index_completed || 0);
  const progressLabel = indexStatus === 'indexing' && total ? `${completed}/${total}` : indexStatus.toUpperCase();
  summary.innerHTML = `
    <article class="card plugin-summary-card"><span>Libraries</span><strong>${Number(counts.libraries || appState.knowledgeLibraries.length || 0)}</strong><small>Agent-scoped collections</small></article>
    <article class="card plugin-summary-card"><span>Documents</span><strong>${Number(counts.documents || appState.knowledgeDocuments.length || 0)}</strong><small>Searchable sources</small></article>
    <article class="card plugin-summary-card"><span>Migrated</span><strong>${Number(migration.migrated_documents || 0)}</strong><small>Legacy entries preserved</small></article>
    <article class="card plugin-summary-card"><span>Dense index</span><strong>${escapeHtml(progressLabel)}</strong><small>BM25 remains immediately available</small></article>`;

  if (!selectedKnowledgeLibrary() && appState.knowledgeLibraries.length) {
    knowledgeUi.selectedLibraryId = Number(appState.knowledgeLibraries[0].id);
  }
  const libPage = knowledgePageSlice(appState.knowledgeLibraries, knowledgeUi.libraryPage, knowledgeUi.libraryPageSize);
  knowledgeUi.libraryPage = libPage.page;
  libraryList.innerHTML = libPage.items.length ? libPage.items.map(library => `
    <div class="knowledge-row ${Number(library.id) === Number(knowledgeUi.selectedLibraryId) ? 'active' : ''}" data-knowledge-library-row="${library.id}">
      <button class="knowledge-row-copy link-btn" data-select-knowledge-library="${library.id}"><strong>${escapeHtml(library.name)}</strong><small>${Number(library.document_count || 0)} docs · ${Number(library.agent_count || 0)} agents · ${library.enabled ? 'enabled' : 'disabled'}</small></button>
      <div class="knowledge-row-actions"><button class="icon-btn" data-edit-knowledge-library="${library.id}" title="Edit">✎</button><button class="icon-btn" data-delete-knowledge-library="${library.id}" title="Delete">×</button></div>
    </div>`).join('') : '<div class="queue-empty">No Knowledge Libraries yet.</div>';
  renderKnowledgePager($('#knowledgeLibraryPager'), libPage.page, libPage.pages, 'library');

  const library = selectedKnowledgeLibrary();
  const docs = library ? appState.knowledgeDocuments.filter(item => Number(item.library_id) === Number(library.id)) : [];
  const docPage = knowledgePageSlice(docs, knowledgeUi.documentPage, knowledgeUi.documentPageSize);
  knowledgeUi.documentPage = docPage.page;
  $('#knowledgeDocumentHeading').textContent = library ? library.name : 'Select a library';
  documentList.innerHTML = docPage.items.length ? docPage.items.map(document => {
    const metadata = document.metadata || {};
    const statusText = document.status || 'registered';
    const editable = ['manual_text', 'legacy_information', 'packaged_default'].includes(String(document.source_type || ''));
    return `<div class="knowledge-row">
      <button class="knowledge-row-copy link-btn" data-view-knowledge-document="${document.id}"><strong>${escapeHtml(document.title)}</strong><small>${escapeHtml(document.source_type || 'source')} · ${escapeHtml(statusText)} · ${Number(metadata.chunk_count || 0)} chunks</small></button>
      <div class="knowledge-row-actions">${editable ? `<button class="icon-btn" data-edit-knowledge-text="${document.id}" title="Edit text">✎</button>` : ''}<button class="icon-btn" data-reindex-knowledge-document="${document.id}" title="Reindex">↻</button><button class="icon-btn" data-delete-knowledge-document="${document.id}" title="Delete">×</button></div>
    </div>`;
  }).join('') : `<div class="queue-empty">${library ? 'No documents in this library.' : 'Select a library to manage documents.'}</div>`;
  renderKnowledgePager($('#knowledgeDocumentPager'), docPage.page, docPage.pages, 'document');

  const migrationText = $('#knowledgeMigrationText');
  if (migrationText) migrationText.textContent = migration.retired
    ? `${Number(migration.migrated_documents || 0)} legacy entries migrated into ${Number(migration.migrated_libraries || 0)} libraries.`
    : 'Knowledge migration status unavailable.';
  const badge = $('#knowledgeMigrationBadge');
  if (badge) badge.textContent = migration.retired ? 'Migrated' : 'Checking';
  const indexBadge = $('#knowledgeIndexBadge');
  if (indexBadge) indexBadge.textContent = progressLabel;
  const indexText = $('#knowledgeIndexText');
  if (indexText) indexText.textContent = indexStatus === 'indexing'
    ? `Dense embedding/HNSW indexing continues in the background (${completed}/${total || '?'} libraries). Core is already ready and BM25 search works.`
    : (migration.index_error ? `Dense index ${indexStatus}: ${migration.index_error}` : `Dense index ${indexStatus}. BM25 is ready independently.`);
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
  if (knowledgeUi.selectedLibraryId && !selectedKnowledgeLibrary()) knowledgeUi.selectedLibraryId = null;
  renderKnowledge();
}

function openKnowledgeLibraryModal(library = null) {
  const fragment = $('#simpleModalTemplate').content.cloneNode(true);
  $('#modalRoot').replaceChildren(fragment);
  $('#simpleModalTitle').textContent = library ? 'Edit Knowledge Library' : 'Create Knowledge Library';
  $('#simpleModalFields').innerHTML = `<label>Name<input name="name" maxlength="120" required value="${escapeHtml(library?.name || '')}"></label><label>Description<textarea name="description" rows="4">${escapeHtml(library?.description || '')}</textarea></label><label class="toggle-row"><span><strong>Enabled</strong><small>Disabled libraries are excluded from retrieval.</small></span><input name="enabled" type="checkbox" ${library?.enabled !== 0 ? 'checked' : ''}><i></i></label>`;
  wireModalBasics();
  $('#simpleModalForm').onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = { name: form.elements.name.value.trim(), description: form.elements.description.value.trim(), enabled: form.elements.enabled.checked };
    try {
      const saved = await api(library ? `/api/knowledge/libraries/${library.id}` : '/api/knowledge/libraries', { method: library ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      knowledgeUi.selectedLibraryId = Number(saved.id); knowledgeUi.documentPage = 0; closeModal(); await refreshKnowledgeOverview(); toast('Knowledge Library saved.', 'success');
    } catch (error) { toast(error.message, 'error'); }
  };
}

function openKnowledgeTextModal(document = null) {
  const library = selectedKnowledgeLibrary();
  if (!document && !library) { toast('Select a Knowledge Library first.', 'error'); return; }
  const fragment = $('#simpleModalTemplate').content.cloneNode(true);
  $('#modalRoot').replaceChildren(fragment);
  $('#simpleModalTitle').textContent = document ? 'Edit Knowledge Text' : `Add text to ${library.name}`;
  $('#simpleModalFields').innerHTML = `<label>Title<input name="title" maxlength="240" required value="${escapeHtml(document?.title || '')}"></label><label>Knowledge text<textarea name="text" rows="12" required></textarea></label><p class="tiny muted">Text is chunked and indexed into Hybrid RAG. It is retrieved only when relevant; it is never appended to every prompt.</p>`;
  wireModalBasics();
  const form = $('#simpleModalForm');
  if (document) {
    api(`/api/knowledge/documents/${document.id}/content?limit=500`).then(content => {
      const parent = (content.parent_blocks || []).map(block => block.text || '').filter(Boolean).join('\n\n');
      form.elements.text.value = parent;
    }).catch(error => toast(error.message, 'error'));
  }
  form.onsubmit = async event => {
    event.preventDefault();
    const payload = { title: form.elements.title.value.trim(), text: form.elements.text.value.trim() };
    try {
      await api(document ? `/api/knowledge/documents/${document.id}/text` : `/api/knowledge/libraries/${library.id}/text-documents`, { method: document ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      closeModal(); await refreshKnowledgeOverview(); toast('Knowledge text indexed.', 'success');
    } catch (error) { toast(error.message, 'error'); }
  };
}

async function openKnowledgeDocumentDetail(documentId) {
  try {
    const content = await api(`/api/knowledge/documents/${documentId}/content?limit=24`);
    const document = content.document || {};
    const fragment = $('#simpleModalTemplate').content.cloneNode(true);
    $('#modalRoot').replaceChildren(fragment);
    $('#simpleModalTitle').textContent = document.title || 'Knowledge document';
    const chunks = (content.chunks || []).slice(0, 8).map((chunk, index) => `<div class="knowledge-search-hit"><strong>Chunk ${index + 1} · ${escapeHtml(chunk.content_type || 'text')}</strong><small>${escapeHtml(chunk.heading_path || '')}</small><p class="tiny">${escapeHtml(String(chunk.text || '').slice(0, 480))}</p></div>`).join('');
    const sourceButton = document.storage_key ? `<button type="button" class="btn secondary" id="knowledgeDownloadSourceBtn">Download original source</button>` : '';
    $('#simpleModalFields').innerHTML = `<div class="status-box"><strong>${escapeHtml(document.source_name || document.source_type || '')}</strong><p>${escapeHtml(document.status || '')} · ${Number(content.parent_blocks_total || 0)} parent blocks · ${Number(content.chunks_total || 0)} chunks · ${Number(content.assets_total || 0)} assets</p></div>${sourceButton}<div class="knowledge-detail-text">${chunks || '<span class="tiny muted">No chunks available.</span>'}</div>`;
    $('#simpleModalForm .modal-footer .btn.primary').remove();
    wireModalBasics();
    const source = $('#knowledgeDownloadSourceBtn');
    if (source) source.onclick = () => downloadAuthenticated(`/api/knowledge/documents/${document.id}/source`, document.source_name || 'knowledge-source');
  } catch (error) { toast(error.message, 'error'); }
}

async function runKnowledgeSearch() {
  const query = $('#knowledgeSearchInput').value.trim();
  if (!query) return;
  const library = selectedKnowledgeLibrary();
  const button = $('#knowledgeSearchBtn'); button.disabled = true;
  try {
    const result = await api('/api/knowledge/search', { method:'POST', body:JSON.stringify({ query, library_ids: library ? [library.id] : [], top_k:6, candidate_k:24, adaptive:true, build_context:true, context_top_k:4, context_token_budget:1800, neighbor_window:1 }) });
    const confidence = result.confidence || {};
    const hits = (result.results || []).slice(0, 4);
    $('#knowledgeSearchResults').innerHTML = hits.length ? hits.map((hit, index) => `<div class="knowledge-search-hit"><strong>K${index + 1} · ${escapeHtml(hit.document_title || hit.source_name || 'Knowledge')}</strong><small>${escapeHtml(hit.heading_path || '')} · ${Number(hit.rerank_score ?? hit.rrf_score ?? 0).toFixed(3)}</small></div>`).join('') : '<span class="tiny muted">No relevant evidence found.</span>';
    $('#knowledgeIndexText').textContent = `Retrieval ${escapeHtml(confidence.label || 'none')} · score ${Number(confidence.score || 0).toFixed(3)} · ${result.elapsed_ms || 0} ms · ${result.context?.safe_to_inject ? 'safe to inject' : 'not injected'}.`;
  } catch (error) { toast(error.message, 'error'); }
  finally { button.disabled = false; }
}

async function uploadKnowledgeFiles(files) {
  const library = selectedKnowledgeLibrary();
  if (!library) { toast('Select a Knowledge Library first.', 'error'); return; }
  for (const file of files) {
    const form = new FormData(); form.append('file', file, file.name);
    try { await api(`/api/knowledge/libraries/${library.id}/documents`, { method:'POST', body:form }); toast(`${file.name} queued for ingestion.`, 'success'); }
    catch (error) { toast(`${file.name}: ${error.message}`, 'error'); }
  }
  await refreshKnowledgeOverview();
}

function bindKnowledgeManagement() {
  $('#addKnowledgeLibraryBtn')?.addEventListener('click', () => openKnowledgeLibraryModal());
  $('#addKnowledgeTextBtn')?.addEventListener('click', () => openKnowledgeTextModal());
  $('#uploadKnowledgeBtn')?.addEventListener('click', () => { if (!selectedKnowledgeLibrary()) return toast('Select a Knowledge Library first.', 'error'); $('#knowledgeFileInput').click(); });
  $('#knowledgeFileInput')?.addEventListener('change', event => { const files = [...(event.currentTarget.files || [])]; event.currentTarget.value = ''; if (files.length) uploadKnowledgeFiles(files); });
  $('#knowledgeSearchBtn')?.addEventListener('click', runKnowledgeSearch);
  $('#knowledgeSearchInput')?.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); runKnowledgeSearch(); } });
  $('#knowledgeRebuildBtn')?.addEventListener('click', async () => {
    const library = selectedKnowledgeLibrary();
    try { await api('/api/knowledge/index/rebuild', { method:'POST', body:JSON.stringify({ library_id: library?.id || null }) }); toast('Knowledge index rebuild started in the background.', 'success'); }
    catch (error) { toast(error.message, 'error'); }
  });
  document.addEventListener('click', async event => {
    const target = event.target.closest('[data-select-knowledge-library],[data-edit-knowledge-library],[data-delete-knowledge-library],[data-view-knowledge-document],[data-edit-knowledge-text],[data-delete-knowledge-document],[data-reindex-knowledge-document],[data-knowledge-page]');
    if (!target) return;
    if (target.dataset.selectKnowledgeLibrary) { knowledgeUi.selectedLibraryId = Number(target.dataset.selectKnowledgeLibrary); knowledgeUi.documentPage = 0; renderKnowledge(); }
    else if (target.dataset.editKnowledgeLibrary) openKnowledgeLibraryModal(appState.knowledgeLibraries.find(item => Number(item.id) === Number(target.dataset.editKnowledgeLibrary)));
    else if (target.dataset.deleteKnowledgeLibrary) {
      const library = appState.knowledgeLibraries.find(item => Number(item.id) === Number(target.dataset.deleteKnowledgeLibrary));
      if (!confirm(`Delete empty library ${library?.name || 'this library'}? Documents must be deleted first.`)) return;
      try { await api(`/api/knowledge/libraries/${target.dataset.deleteKnowledgeLibrary}`, { method:'DELETE' }); knowledgeUi.selectedLibraryId = null; await refreshKnowledgeOverview(); }
      catch (error) { toast(error.message, 'error'); }
    } else if (target.dataset.viewKnowledgeDocument) openKnowledgeDocumentDetail(Number(target.dataset.viewKnowledgeDocument));
    else if (target.dataset.editKnowledgeText) openKnowledgeTextModal(appState.knowledgeDocuments.find(item => Number(item.id) === Number(target.dataset.editKnowledgeText)));
    else if (target.dataset.deleteKnowledgeDocument) {
      const document = appState.knowledgeDocuments.find(item => Number(item.id) === Number(target.dataset.deleteKnowledgeDocument));
      if (!confirm(`Delete ${document?.title || 'this document'}?`)) return;
      try { await api(`/api/knowledge/documents/${target.dataset.deleteKnowledgeDocument}`, { method:'DELETE' }); await refreshKnowledgeOverview(); }
      catch (error) { toast(error.message, 'error'); }
    } else if (target.dataset.reindexKnowledgeDocument) {
      try { await api(`/api/knowledge/documents/${target.dataset.reindexKnowledgeDocument}/reindex`, { method:'POST' }); toast('Document reindex queued.', 'success'); }
      catch (error) { toast(error.message, 'error'); }
    } else if (target.dataset.knowledgePage) {
      const delta = Number(target.dataset.delta || 0);
      if (target.dataset.knowledgePage === 'library') knowledgeUi.libraryPage += delta;
      else knowledgeUi.documentPage += delta;
      renderKnowledge();
    }
  });
}

bindKnowledgeManagement();

setInterval(() => {
  if (appState.token && $('#page-knowledge')?.classList.contains('active') && appState.knowledgeStatus?.legacy_information_migration?.index_status === 'indexing') {
    refreshKnowledgeOverview().catch(() => {});
  }
}, 2000);
