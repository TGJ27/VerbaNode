'use strict';

function pluginStatusLabel(plugin) {
  if (plugin.status === 'incompatible') return ['Incompatible', 'error'];
  if (plugin.status === 'invalid') return ['Invalid package', 'error'];
  if (plugin.status === 'load_error') return ['Load failed', 'error'];
  if (!plugin.enabled || plugin.status === 'disabled') return ['Disabled', 'disabled'];
  if (plugin.status === 'loading') return ['Loading', 'neutral'];
  if (plugin.status === 'reloading') return ['Reloading', 'neutral'];
  if (plugin.status === 'unhealthy') return ['Unhealthy', 'warning'];
  if (!plugin.healthy || plugin.status === 'error') return ['Error', 'error'];
  return ['Healthy', 'healthy'];
}

function pluginMetric(value, suffix = '') {
  const number = Number(value || 0);
  return `${Number.isInteger(number) ? number : number.toFixed(2)}${suffix}`;
}

function createPluginElement(tagName, className = '', text = '') {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== '') node.textContent = String(text);
  return node;
}

function createPluginMetricElement(label, value) {
  const metric = createPluginElement('div', 'plugin-metric');
  metric.append(
    createPluginElement('span', '', label),
    createPluginElement('strong', '', value),
  );
  return metric;
}

function createPluginCard(plugin) {
  const [statusLabel, statusClass] = pluginStatusLabel(plugin);
  const failedLoad = ['load_error', 'incompatible', 'invalid'].includes(plugin.status);
  const card = createPluginElement('article', `card plugin-card${plugin.enabled ? '' : ' plugin-disabled'}${failedLoad ? ' plugin-load-error' : ''}`);
  card.dataset.pluginCard = String(plugin.id || '');

  const head = createPluginElement('div', 'plugin-card-head');
  const title = createPluginElement('div', 'plugin-card-title');
  const eyebrow = createPluginElement('div', 'plugin-title-meta');
  eyebrow.append(
    createPluginElement('span', 'eyebrow', plugin.category || 'General'),
    createPluginElement('span', `plugin-source ${plugin.external ? 'external' : 'builtin'}`, plugin.external ? 'External' : 'Built-in'),
  );
  title.append(
    eyebrow,
    createPluginElement('h3', '', plugin.name || plugin.id || 'Plugin'),
    createPluginElement('small', '', `${plugin.declared_id || plugin.id || 'unknown'} · v${plugin.version || '0.0.0'} · SDK ${plugin.sdk_version || '1'}`),
  );
  head.append(title, createPluginElement('span', `plugin-status ${statusClass}`, statusLabel));

  const body = createPluginElement('div', 'plugin-card-body');
  body.append(createPluginElement('p', 'plugin-description', plugin.description || plugin.tool_description || ''));

  const permissions = createPluginElement('div', 'plugin-permissions');
  const permissionList = Array.isArray(plugin.permissions) ? plugin.permissions : [];
  if (permissionList.length) {
    permissionList.forEach(permission => {
      permissions.append(createPluginElement('span', 'chip plugin-permission', permission));
    });
  } else {
    permissions.append(createPluginElement('span', 'chip plugin-permission neutral', 'No declared permissions'));
  }
  body.append(permissions);

  if (!failedLoad) {
    const metrics = createPluginElement('div', 'plugin-metrics');
    metrics.append(
      createPluginMetricElement('Executions', pluginMetric(plugin.executions)),
      createPluginMetricElement('Errors', pluginMetric(plugin.errors)),
      createPluginMetricElement('Timeouts', pluginMetric(plugin.timeouts)),
      createPluginMetricElement('Failure streak', `${pluginMetric(plugin.consecutive_failures)} / ${pluginMetric(plugin.failure_threshold)}`),
      createPluginMetricElement('Average', pluginMetric(plugin.average_latency_ms, ' ms')),
      createPluginMetricElement('Active', pluginMetric(plugin.active_executions)),
    );
    body.append(metrics);

    const assignment = createPluginElement('div', 'plugin-agent-use');
    assignment.append(
      createPluginElement('span', '', 'Assigned to agents'),
      createPluginElement('strong', '', `${Number(plugin.agent_count || 0)} / ${Number(plugin.agent_total || 0)}`),
    );
    body.append(assignment);
  }

  if (plugin.last_error) {
    const errorBox = createPluginElement('div', 'plugin-error');
    errorBox.append(
      createPluginElement('strong', '', failedLoad ? 'Package error' : 'Last execution error'),
      createPluginElement('span', '', plugin.last_error),
    );
    body.append(errorBox);
  }
  if (plugin.last_reload_error) {
    const reloadErrorBox = createPluginElement('div', 'plugin-error plugin-reload-error');
    reloadErrorBox.append(
      createPluginElement('strong', '', 'Last reload kept the previous version'),
      createPluginElement('span', '', plugin.last_reload_error),
    );
    body.append(reloadErrorBox);
  }

  if (plugin.external && plugin.plugin_path) {
    const pathBox = createPluginElement('div', 'plugin-path');
    pathBox.title = plugin.plugin_path;
    pathBox.append(
      createPluginElement('span', '', 'Folder'),
      createPluginElement('code', '', plugin.plugin_path),
    );
    body.append(pathBox);
  }

  const footer = createPluginElement('div', 'plugin-card-footer');
  footer.append(createPluginElement('span', 'plugin-author', plugin.author || 'Unknown author'));

  const actions = createPluginElement('div', 'plugin-card-actions');
  if (!failedLoad) {
    const resetButton = createPluginElement('button', 'plugin-action plugin-action-reset', 'Reset metrics');
    resetButton.type = 'button';
    resetButton.dataset.resetPlugin = String(plugin.id || '');
    resetButton.disabled = !Number(plugin.executions || 0) && !Number(plugin.errors || 0);
    actions.append(resetButton);
  }

  if (plugin.external && plugin.reloadable) {
    const reloadButton = createPluginElement('button', 'plugin-action plugin-action-reload', failedLoad || plugin.status === 'unhealthy' ? 'Repair / reload' : 'Reload');
    reloadButton.type = 'button';
    reloadButton.dataset.reloadPlugin = String(plugin.id || '');
    actions.append(reloadButton);
  } else if (plugin.status === 'unhealthy') {
    const recoverButton = createPluginElement('button', 'plugin-action plugin-action-reload', 'Recover');
    recoverButton.type = 'button';
    recoverButton.dataset.recoverPlugin = String(plugin.id || '');
    actions.append(recoverButton);
  }

  if (!failedLoad) {
    const toggleButton = createPluginElement(
      'button',
      `plugin-action ${plugin.enabled ? 'plugin-action-disable' : 'plugin-action-enable'}`,
      plugin.enabled ? 'Disable' : 'Enable',
    );
    toggleButton.type = 'button';
    toggleButton.dataset.togglePlugin = String(plugin.id || '');
    toggleButton.dataset.enabled = plugin.enabled ? 'true' : 'false';
    actions.append(toggleButton);
  }

  footer.append(actions);
  card.append(head, body, footer);
  return card;
}

function renderPlugins() {
  const payload = appState.plugins || { plugins: [], summary: {} };
  const plugins = Array.isArray(payload.plugins) ? payload.plugins : [];
  const summary = payload.summary || {};
  const summaryNode = $('#pluginSummary');
  const grid = $('#pluginGrid');
  if (!summaryNode || !grid) return;

  const healthLabel = Number(summary.errors || 0) > 0
    ? `${summary.errors} issue${Number(summary.errors) === 1 ? '' : 's'}`
    : 'All clear';

  const summaryCards = [
    ['Discovered', Number(summary.total || plugins.length), `${Number(summary.loaded || 0)} loaded`],
    ['Sources', `${Number(summary.builtin || 0)} + ${Number(summary.external || 0)}`, 'Built-in + external'],
    ['Executions', Number(summary.executions || 0), `${Number(summary.agent_assignments || 0)} agent assignments`],
    ['Health', healthLabel, `${Number(summary.failed_loads || 0)} failed to load`],
  ].map(([label, value, detail]) => {
    const card = createPluginElement('div', 'card plugin-summary-card');
    card.append(
      createPluginElement('span', '', label),
      createPluginElement('strong', '', value),
      createPluginElement('small', '', detail),
    );
    return card;
  });
  summaryNode.replaceChildren(...summaryCards);

  const folder = $('#externalPluginDirectory');
  if (folder) folder.textContent = payload.external_plugins_directory || 'plugins/';

  if (!plugins.length) {
    grid.replaceChildren(createPluginElement('div', 'card queue-empty plugin-empty-state', 'No plugins were reported by the backend.'));
    return;
  }

  grid.replaceChildren(...plugins.map(createPluginCard));
  applyExplorerView('plugins', getExplorerView('plugins'), false);
}

async function refreshPlugins(showToast = false) {
  const payload = await api('/api/plugins');
  appState.plugins = payload;
  if (appState.data) appState.data.plugins = payload;
  renderPlugins();
  if (showToast) toast('Plugin status refreshed.');
  return payload;
}
