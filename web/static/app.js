const form = document.querySelector('#analysis-form');
const note = document.querySelector('#form-note');
const processPanel = document.querySelector('#process');
const reportPanel = document.querySelector('#report');
const stages = [...document.querySelectorAll('.stage')];
const submitButton = form.querySelector('button[type="submit"]');
const locatorPanel = document.querySelector('#locator-panel');
const locatorForm = document.querySelector('#locator-form');
const locatorState = document.querySelector('#locator-state');
const locatorResults = document.querySelector('#locator-results');
let pollTimer = null;
let stageTimer = null;
let currentStage = 0;

const today = new Date();
const localToday = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
document.querySelector('#trade-date').value = localToday;
document.querySelector('#trade-date').max = localToday;

document.querySelector('#locator-trigger').addEventListener('click', () => {
  openModal(locatorPanel);
  window.setTimeout(() => document.querySelector('#company-query').focus(), 300);
});

document.querySelector('#locator-close').addEventListener('click', () => {
  closeModal(locatorPanel);
});

locatorPanel.addEventListener('click', (event) => {
  if (event.target === locatorPanel) closeModal(locatorPanel);
});

function renderLocatorResults(data) {
  if (!data.results?.length) {
    locatorResults.innerHTML = `<div class="locator-empty"><strong>未找到已验证的股票代码</strong><p>${escapeHtml(data.message)}</p></div>`;
    return;
  }
  locatorResults.innerHTML = `
    <div class="locator-result-summary"><span>${escapeHtml(data.message)}</span><small>代码均已通过证券目录验证</small></div>
    <div class="candidate-list">
      ${data.results.map((item) => `
        <article class="candidate-card">
          <div class="candidate-main">
            <span class="candidate-market">${escapeHtml(item.market)}</span>
            <h3>${escapeHtml(item.company_name)}</h3>
            <strong>${escapeHtml(item.ticker)}</strong>
            <p>${escapeHtml(item.exchange)} · ${escapeHtml(item.match_reason)}</p>
          </div>
          <div class="candidate-actions">
            <span class="verified-badge">✓ 已验证</span>
            <button type="button" data-ticker="${escapeHtml(item.ticker)}">选择并分析</button>
          </div>
        </article>
      `).join('')}
    </div>`;
  locatorResults.querySelectorAll('[data-ticker]').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelector('#ticker').value = button.dataset.ticker;
      document.querySelector('#asset-type').value = 'stock';
      note.textContent = `已选择 ${button.dataset.ticker}，可以开始生成研报。`;
      note.classList.remove('error');
      closeModal(locatorPanel);
      form.scrollIntoView({ behavior: 'smooth', block: 'center' });
      submitButton.focus();
    });
  });
}

locatorForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const query = document.querySelector('#company-query').value.trim();
  if (!query) {
    locatorResults.innerHTML = '<div class="locator-empty"><strong>请先描述一家公司</strong><p>可以输入公司名称、产品、行业或创始人。</p></div>';
    return;
  }
  const button = locatorForm.querySelector('button[type="submit"]');
  button.disabled = true;
  locatorResults.innerHTML = '';
  locatorState.classList.remove('hidden');
  try {
    const response = await fetch('/api/instruments/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        market: document.querySelector('#company-market').value,
        use_ai: true,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '股票定位服务暂时不可用');
    renderLocatorResults(data);
  } catch (error) {
    locatorResults.innerHTML = `<div class="locator-empty error"><strong>暂时无法完成搜索</strong><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    locatorState.classList.add('hidden');
    button.disabled = false;
  }
});

const escapeHtml = (value = '') => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const historyReportSelect = document.querySelector('#history-report-select');
const historyOpenButton = document.querySelector('#history-open');
const historyPickerState = document.querySelector('#history-picker-state');
const historyFilter = document.querySelector('#history-filter');
const historyQuery = document.querySelector('#history-query');
const reportDeleteButton = document.querySelector('#report-delete');
const reportCloseButton = document.querySelector('#report-close');
const historyResultsModal = document.querySelector('#history-results-modal');
const historyResultsState = document.querySelector('#history-results-state');
const historyResultsList = document.querySelector('#history-results-list');
const historyResultsQuery = document.querySelector('#history-results-query');
const historyResultsClose = document.querySelector('#history-results-close');
let currentReportId = '';

function closeModal(modal) {
  modal.classList.add('hidden');
  if (modal === reportPanel) restoreHistoryPickerState();
  if (!document.querySelector('.modal-backdrop:not(.hidden)')) document.body.classList.remove('modal-open');
}

function openModal(modal) {
  modal.classList.remove('hidden');
  document.body.classList.add('modal-open');
}

function reportDateLabel(item) {
  const generated = item.generated_at ? item.generated_at.replace('T', ' ').slice(0, 16) : '时间未知';
  return `股票代码：${item.ticker} ｜ 分析日期：${item.trade_date || '日期未知'} ｜ 生成时间：${generated}`;
}

function restoreHistoryPickerState() {
  const count = Math.max(0, historyReportSelect.options.length - 1);
  historyPickerState.textContent = count ? `已保存 ${count} 份研报` : '完成分析后，研报会自动出现在这里';
}

function renderHistoryPicker(items) {
  historyReportSelect.innerHTML = '<option value="">选择已生成的研报</option>' + items.map((item) => (
    `<option value="${escapeHtml(item.id)}">${escapeHtml(reportDateLabel(item))}</option>`
  )).join('');
  historyOpenButton.disabled = !items.length;
  restoreHistoryPickerState();
}

async function loadHistoryPicker(query = '') {
  try {
    const params = new URLSearchParams({ limit: '200' });
    if (query) params.set('query', query);
    const response = await fetch(`/api/reports?${params.toString()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('历史研报暂时无法读取');
    const data = await response.json();
    renderHistoryPicker(data.reports || []);
  } catch (error) {
    historyPickerState.textContent = error.message;
    historyOpenButton.disabled = true;
  }
}

async function openHistoricalReportById(reportId) {
  if (!reportId) return;
  historyOpenButton.disabled = true;
  historyPickerState.textContent = '正在打开研报…';
  try {
    const response = await fetch(`/api/reports/${encodeURIComponent(reportId)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('历史报告不存在或已损坏');
    const historical = await response.json();
    showReport({ ...historical, status: 'completed', phase: '历史报告' });
  } catch (error) {
    historyPickerState.textContent = error.message;
  } finally {
    historyOpenButton.disabled = false;
  }
}

async function openHistoricalReport() {
  await openHistoricalReportById(historyReportSelect.value);
}

function renderHistorySearchResults(items, query) {
  historyResultsQuery.textContent = `股票代码：${query} · 找到 ${items.length} 份研报`;
  if (!items.length) {
    historyResultsState.textContent = '';
    historyResultsList.innerHTML = '<div class="history-results-empty"><strong>未找到对应研报</strong><p>请检查股票代码是否正确，或先生成一份新的研报。</p></div>';
    return;
  }
  historyResultsState.textContent = '请选择一份研报查看完整内容。';
  historyResultsList.innerHTML = items.map((item) => {
    const generated = item.generated_at ? item.generated_at.replace('T', ' ').slice(0, 16) : '时间未知';
    return `<article class="history-result-card">
      <div class="history-result-main">
        <span class="history-result-ticker">${escapeHtml(item.ticker)}</span>
        <strong>投资研究报告</strong>
        <p>分析日期：${escapeHtml(item.trade_date || '日期未知')} · 生成时间：${escapeHtml(generated)}</p>
      </div>
      <button class="secondary-button" type="button" data-history-report-id="${escapeHtml(item.id)}">查看研报 →</button>
    </article>`;
  }).join('');
  historyResultsList.querySelectorAll('[data-history-report-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      historyReportSelect.value = button.dataset.historyReportId;
      closeModal(historyResultsModal);
      await openHistoricalReportById(button.dataset.historyReportId);
    });
  });
}

async function searchHistoryReports(query) {
  openModal(historyResultsModal);
  historyResultsQuery.textContent = `股票代码：${query}`;
  historyResultsState.textContent = '正在查找研报…';
  historyResultsList.innerHTML = '';
  try {
    const params = new URLSearchParams({ limit: '200', query });
    const response = await fetch(`/api/reports?${params.toString()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('历史研报查询失败');
    const data = await response.json();
    renderHistorySearchResults(data.reports || [], query);
  } catch (error) {
    historyResultsState.textContent = error.message;
    historyResultsList.innerHTML = '<div class="history-results-empty"><strong>暂时无法查询</strong><p>请稍后重试。</p></div>';
  }
}

historyReportSelect.addEventListener('change', () => {
  historyOpenButton.disabled = !historyReportSelect.value;
});
historyOpenButton.addEventListener('click', openHistoricalReport);
historyFilter.addEventListener('submit', (event) => {
  event.preventDefault();
  const query = historyQuery.value.trim();
  if (!query) {
    openModal(historyResultsModal);
    historyResultsQuery.textContent = '请输入股票代码';
    historyResultsState.textContent = '请输入股票代码';
    historyResultsList.innerHTML = '<div class="history-results-empty"><strong>还没有输入股票代码</strong><p>例如：NVDA、600519.SS 或 0700.HK。</p></div>';
    return;
  }
  searchHistoryReports(query);
});
historyResultsClose.addEventListener('click', () => closeModal(historyResultsModal));
historyResultsModal.addEventListener('click', (event) => { if (event.target === historyResultsModal) closeModal(historyResultsModal); });

const modelSettings = document.querySelector('#model-settings');
const modelProfileSelect = document.querySelector('#model-profile');
const modelProfileList = document.querySelector('#model-profile-list');
const modelProfileForm = document.querySelector('#model-profile-form');
const modelTemplate = document.querySelector('#model-template');
const modelStatus = document.querySelector('#model-form-status');
const discoveredModels = document.querySelector('#discovered-models');
let modelProfiles = [];
let modelTemplates = [];
let discoveredModelOptions = [];

function setModelStatus(message = '', kind = '') {
  modelStatus.textContent = message;
  modelStatus.className = kind;
}

function currentProfileId() {
  return document.querySelector('#editing-profile-id').value;
}

function showDiscoveredModels(models = []) {
  const quickSelect = document.querySelector('#model-quick');
  const deepSelect = document.querySelector('#model-deep');
  const quickValue = quickSelect.value;
  const deepValue = deepSelect.value;
  const uniqueModels = [...new Set(models.filter(Boolean))];
  discoveredModelOptions = uniqueModels;
  const fillSelect = (select, selected, placeholder) => {
    const choices = uniqueModels.includes(selected) || !selected ? uniqueModels : [selected, ...uniqueModels];
    select.innerHTML = `<option value="">${placeholder}</option>` + choices.map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join('');
    select.value = selected;
  };
  fillSelect(quickSelect, quickValue, '请选择日常分析模型');
  fillSelect(deepSelect, deepValue, '请选择深度推理模型');
  if (!models.length) {
    discoveredModels.classList.add('hidden');
    discoveredModels.innerHTML = '';
    return;
  }
  discoveredModels.classList.remove('hidden');
  discoveredModels.innerHTML = `<span>接口返回 ${uniqueModels.length} 个模型，已载入上方两个下拉框。</span>`;
}

function resetModelForm() {
  modelProfileForm.reset();
  document.querySelector('#editing-profile-id').value = '';
  document.querySelector('#model-form-title').textContent = '新增模型 Endpoint';
  setModelStatus();
  showDiscoveredModels();
  const custom = modelTemplates.find((item) => item.id === 'custom');
  if (custom) modelTemplate.value = custom.id;
}

function populateModelForm(profile) {
  document.querySelector('#editing-profile-id').value = profile.id;
  document.querySelector('#model-name').value = profile.name || '';
  modelTemplate.value = profile.template || 'custom';
  document.querySelector('#model-base-url').value = profile.base_url || '';
  showDiscoveredModels(profile.discovered_models || []);
  const quickSelect = document.querySelector('#model-quick');
  const deepSelect = document.querySelector('#model-deep');
  if (profile.quick_model && ![...quickSelect.options].some((item) => item.value === profile.quick_model)) quickSelect.add(new Option(profile.quick_model, profile.quick_model));
  if (profile.deep_model && ![...deepSelect.options].some((item) => item.value === profile.deep_model)) deepSelect.add(new Option(profile.deep_model, profile.deep_model));
  quickSelect.value = profile.quick_model || '';
  deepSelect.value = profile.deep_model || '';
  document.querySelector('#model-api-key').value = '';
  document.querySelector('#model-form-title').textContent = `编辑：${profile.name}`;
  setModelStatus(profile.has_api_key ? '密钥已安全保存' : '未设置密钥');
}

function renderModelProfiles() {
  const selected = modelProfileSelect.value;
  modelProfileSelect.innerHTML = '<option value="">系统默认</option>' + modelProfiles.map((profile) => `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.name)} · ${escapeHtml(profile.quick_model)}</option>`).join('');
  if (modelProfiles.some((profile) => profile.id === selected)) modelProfileSelect.value = selected;
  if (!modelProfiles.length) {
    modelProfileList.innerHTML = '<p class="profile-empty">还没有模型配置。可继续使用当前系统模型，或添加新的第三方 Endpoint。</p>';
    return;
  }
  const editing = currentProfileId();
  modelProfileList.innerHTML = modelProfiles.map((profile) => `<div class="saved-profile-row"><button class="saved-profile ${profile.id === editing ? 'active' : ''}" type="button" data-profile-id="${escapeHtml(profile.id)}"><strong>${escapeHtml(profile.name)}</strong><small>${escapeHtml(profile.quick_model)} · ${profile.has_api_key ? '已配置密钥' : '无密钥'}</small></button><button class="saved-profile-delete" type="button" data-delete-profile-id="${escapeHtml(profile.id)}" aria-label="删除 ${escapeHtml(profile.name)}" title="删除配置"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="M7 7l1 13h8l1-13"></path><path d="M10 11v5M14 11v5"></path></svg></button></div>`).join('');
  modelProfileList.querySelectorAll('.saved-profile[data-profile-id]').forEach((button) => {
    button.addEventListener('click', () => {
      const profile = modelProfiles.find((item) => item.id === button.dataset.profileId);
      if (profile) { populateModelForm(profile); renderModelProfiles(); }
    });
  });
  modelProfileList.querySelectorAll('.saved-profile-delete[data-delete-profile-id]').forEach((button) => {
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      deleteModelProfile(button.dataset.deleteProfileId);
    });
  });
}

async function loadModelCenter() {
  const [templatesResponse, profilesResponse] = await Promise.all([fetch('/api/model-templates'), fetch('/api/model-profiles', { cache: 'no-store' })]);
  if (!templatesResponse.ok || !profilesResponse.ok) throw new Error('模型配置中心暂时不可用');
  modelTemplates = (await templatesResponse.json()).templates || [];
  modelProfiles = (await profilesResponse.json()).profiles || [];
  modelTemplate.innerHTML = modelTemplates.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  renderModelProfiles();
  if (!currentProfileId()) resetModelForm();
}

function openModelCenter() {
  openModal(modelSettings);
  loadModelCenter().catch((error) => { modelProfileList.innerHTML = `<p class="profile-empty">${escapeHtml(error.message)}</p>`; });
}

document.querySelector('#model-settings-trigger').addEventListener('click', openModelCenter);
document.querySelector('#model-settings-close').addEventListener('click', () => closeModal(modelSettings));
modelSettings.addEventListener('click', (event) => { if (event.target === modelSettings) closeModal(modelSettings); });
document.querySelector('#new-model-profile').addEventListener('click', resetModelForm);

modelTemplate.addEventListener('change', () => {
  const template = modelTemplates.find((item) => item.id === modelTemplate.value);
  const urlInput = document.querySelector('#model-base-url');
  if (template?.base_url && (!urlInput.value || confirm(`使用 ${template.name} 的默认 Endpoint？`))) urlInput.value = template.base_url;
});

modelProfileForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const profileId = currentProfileId();
  const button = modelProfileForm.querySelector('button[type="submit"]');
  button.disabled = true;
  setModelStatus('正在保存…');
  const payload = {
    name: document.querySelector('#model-name').value.trim(), template: modelTemplate.value,
    base_url: document.querySelector('#model-base-url').value.trim(), quick_model: document.querySelector('#model-quick').value.trim(),
    deep_model: document.querySelector('#model-deep').value.trim(), api_key: document.querySelector('#model-api-key').value,
    discovered_models: discoveredModelOptions,
  };
  try {
    const response = await fetch(profileId ? `/api/model-profiles/${profileId}` : '/api/model-profiles', { method: profileId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '无法保存模型配置');
    await loadModelCenter();
    populateModelForm(data.profile);
    modelProfileSelect.value = data.profile.id;
    setModelStatus('已保存，可用于下一次分析', 'success');
  } catch (error) { setModelStatus(error.message, 'error'); }
  finally { button.disabled = false; }
});

async function invokeProfileAction(action) {
  const profileId = currentProfileId();
  const baseUrl = document.querySelector('#model-base-url').value.trim();
  const apiKey = document.querySelector('#model-api-key').value;
  if (!baseUrl) { setModelStatus('请先填写 Endpoint URL', 'error'); return; }
  if (!apiKey.trim() && !profileId) { setModelStatus('请先填写 API Key', 'error'); return; }
  const button = document.querySelector(`#${action}-models`.replace('discover-models', 'discover-models').replace('test-models', 'test-model'));
  if (button) button.disabled = true;
  setModelStatus(action === 'discover' ? '正在读取模型列表…' : '正在验证连接…');
  try {
    const response = await fetch(`/api/model-connections/${action}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_id: profileId || null, base_url: baseUrl, api_key: apiKey, model: document.querySelector('#model-quick').value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '请求失败');
    if (data.models) showDiscoveredModels(data.models);
    if (action === 'discover') setModelStatus(`发现 ${data.models?.length || 0} 个模型，请从下拉框选择`, 'success');
    else setModelStatus(`${data.message}${data.reply ? `：${data.reply}` : ''}`, 'success');
  } catch (error) { setModelStatus(error.message, 'error'); }
  finally { if (button) button.disabled = false; }
}

document.querySelector('#discover-models').addEventListener('click', () => invokeProfileAction('discover'));
document.querySelector('#test-model').addEventListener('click', () => invokeProfileAction('test'));
async function deleteModelProfile(profileId) {
  if (!profileId || !confirm('确认删除这条模型配置？')) return;
  try {
    const response = await fetch(`/api/model-profiles/${profileId}`, { method: 'DELETE' });
    if (!response.ok) { const data = await response.json(); throw new Error(data.detail || '删除失败'); }
    if (currentProfileId() === profileId) resetModelForm();
    await loadModelCenter();
  } catch (error) { setModelStatus(error.message, 'error'); }
}

loadModelCenter().catch(() => { modelProfileList.innerHTML = '<p class="profile-empty">模型配置加载失败</p>'; });
loadHistoryPicker();

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
}

function renderMarkdown(markdown = '') {
  const lines = markdown.split(/\r?\n/);
  let html = '';
  let inList = false;
  let tableRows = [];

  const flushList = () => { if (inList) { html += '</ul>'; inList = false; } };
  const flushTable = () => {
    if (!tableRows.length) return;
    const rows = tableRows.filter((row) => !row.every((cell) => /^:?-+:?$/.test(cell)));
    if (rows.length) {
      html += '<table><thead><tr>' + rows[0].map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join('') + '</tr></thead><tbody>';
      html += rows.slice(1).map((row) => '<tr>' + row.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join('') + '</tr>').join('');
      html += '</tbody></table>';
    }
    tableRows = [];
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (line.includes('|') && line.startsWith('|') && line.endsWith('|')) {
      flushList();
      tableRows.push(line.slice(1, -1).split('|').map((cell) => cell.trim()));
      continue;
    }
    flushTable();
    if (!line) { flushList(); html += '<br />'; continue; }
    if (line.startsWith('### ')) { flushList(); html += `<h3>${inlineMarkdown(line.slice(4))}</h3>`; }
    else if (line.startsWith('## ')) { flushList(); html += `<h2>${inlineMarkdown(line.slice(3))}</h2>`; }
    else if (line.startsWith('# ')) { flushList(); html += `<h1>${inlineMarkdown(line.slice(2))}</h1>`; }
    else if (/^[-*] /.test(line)) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${inlineMarkdown(line.slice(2))}</li>`;
    } else { flushList(); html += `<p>${inlineMarkdown(line)}</p>`; }
  }
  flushList(); flushTable();
  return html || '<p>本章节没有可用内容。</p>';
}

function startStageAnimation() {
  currentStage = 0;
  stages.forEach((stage, index) => stage.className = `stage${index === 0 ? ' active' : ''}`);
  stageTimer = window.setInterval(() => {
    if (currentStage >= stages.length - 2) return;
    stages[currentStage].className = 'stage done';
    currentStage += 1;
    stages[currentStage].className = 'stage active';
  }, 14000);
}

function completeStages() {
  window.clearInterval(stageTimer);
  stages.forEach((stage) => stage.className = 'stage done');
}

function field(fields, name) {
  return fields?.[name] || '—';
}

function showReport(record) {
  const result = record.result;
  currentReportId = result?.report_id || record.id || '';
  reportDeleteButton.classList.toggle('hidden', !currentReportId);
  document.querySelector('#report-ticker').textContent = record.ticker;
  document.querySelector('#report-date').textContent = `分析日期 ${record.trade_date} · AI 自动生成`;
  document.querySelector('#decision').textContent = result.decision || field(result.decision_fields, 'rating');
  document.querySelector('#executive-summary').textContent = field(result.decision_fields, 'executive_summary');
  document.querySelector('#price-target').textContent = field(result.decision_fields, 'price_target');
  document.querySelector('#entry-price').textContent = field(result.trader_fields, 'entry_price');
  document.querySelector('#stop-loss').textContent = field(result.trader_fields, 'stop_loss');
  document.querySelector('#time-horizon').textContent = field(result.decision_fields, 'time_horizon');

  const sections = [
    ['最终决策', result.final_report],
    ['技术面分析', result.reports.market],
    ['基本面分析', result.reports.fundamentals],
    ['新闻分析', result.reports.news],
    ['市场情绪', result.reports.sentiment],
    ['看多观点', result.research.bull],
    ['看空观点', result.research.bear],
    ['研究结论', result.research.manager],
    ['交易方案', result.trader_report],
    ['风险评估', [result.risk.aggressive, result.risk.neutral, result.risk.conservative].filter(Boolean).join('\n\n---\n\n')],
  ].filter(([, content]) => content);

  const nav = document.querySelector('#report-nav');
  const content = document.querySelector('#report-content');
  nav.innerHTML = '';
  const activate = (index) => {
    [...nav.children].forEach((button, i) => button.classList.toggle('active', i === index));
    content.innerHTML = `<h1>${escapeHtml(sections[index][0])}</h1>${renderMarkdown(sections[index][1])}`;
  };
  sections.forEach(([title], index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = title;
    button.addEventListener('click', () => activate(index));
    nav.appendChild(button);
  });
  activate(0);
  processPanel.classList.add('hidden');
  openModal(reportPanel);
  reportCloseButton.focus();
}

async function deleteCurrentReport() {
  if (!currentReportId) return;
  const ticker = document.querySelector('#report-ticker').textContent;
  if (!confirm(`确认删除 ${ticker} 的这份研报？删除后无法恢复。`)) return;
  reportDeleteButton.disabled = true;
  reportDeleteButton.textContent = '正在删除…';
  try {
    const response = await fetch(`/api/reports/${encodeURIComponent(currentReportId)}`, { method: 'DELETE' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || '删除研报失败');
    closeModal(reportPanel);
    currentReportId = '';
    historyReportSelect.value = '';
    await loadHistoryPicker(historyQuery.value.trim());
  } catch (error) {
    reportDeleteButton.textContent = error.message;
  } finally {
    reportDeleteButton.disabled = false;
    if (!reportDeleteButton.textContent.includes('失败')) reportDeleteButton.textContent = '删除研报';
  }
}

reportDeleteButton.addEventListener('click', deleteCurrentReport);
reportCloseButton.addEventListener('click', () => {
  closeModal(reportPanel);
  restoreHistoryPickerState();
});
reportPanel.addEventListener('click', (event) => { if (event.target === reportPanel) closeModal(reportPanel); });

async function poll(taskId) {
  try {
    const response = await fetch(`/api/analyses/${taskId}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('无法读取分析任务');
    const record = await response.json();
    document.querySelector('#process-message').textContent = record.phase;
    if (record.status === 'completed') {
      window.clearTimeout(pollTimer);
      completeStages();
      showReport(record);
      submitButton.disabled = false;
      return;
    }
    if (record.status === 'failed') throw new Error(record.error || '分析失败');
    pollTimer = window.setTimeout(() => poll(taskId), 2500);
  } catch (error) {
    window.clearInterval(stageTimer);
    processPanel.classList.add('hidden');
    submitButton.disabled = false;
    note.textContent = error.message;
    note.classList.add('error');
    document.querySelector('#hero').scrollIntoView({ behavior: 'smooth' });
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  note.classList.remove('error');
  note.textContent = '分析任务启动后请保持页面打开。';
  submitButton.disabled = true;
  reportPanel.classList.add('hidden');
  processPanel.classList.remove('hidden');
  processPanel.scrollIntoView({ behavior: 'smooth', block: 'center' });
  startStageAnimation();

  const payload = {
    ticker: document.querySelector('#ticker').value.trim(),
    trade_date: document.querySelector('#trade-date').value,
    asset_type: document.querySelector('#asset-type').value,
    analysts: ['market', 'social', 'news', 'fundamentals'],
    model_profile_id: modelProfileSelect.value || null,
  };

  try {
    const response = await fetch('/api/analyses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.[0]?.msg || data.detail || '无法创建分析任务');
    poll(data.id);
  } catch (error) {
    window.clearInterval(stageTimer);
    processPanel.classList.add('hidden');
    submitButton.disabled = false;
    note.textContent = error.message;
    note.classList.add('error');
  }
});

document.querySelector('#new-analysis').addEventListener('click', () => {
  closeModal(reportPanel);
  restoreHistoryPickerState();
  document.querySelector('#hero').scrollIntoView({ behavior: 'smooth' });
  document.querySelector('#ticker').focus();
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  const openBackdrop = document.querySelector('.modal-backdrop:not(.hidden)');
  if (openBackdrop) closeModal(openBackdrop);
});
