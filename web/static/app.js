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
const processCoreKicker = document.querySelector('#process-core-kicker');
const processCoreLabel = document.querySelector('#process-core-label');
const processStageImage = document.querySelector('#process-stage-image');
const stageVisual = document.querySelector('#stage-visual');
const artifactCount = document.querySelector('#artifact-count');
const artifactStream = document.querySelector('#artifact-stream');
const processStockTitle = document.querySelector('#process-stock-title');
const processMarketBadge = document.querySelector('#process-market-badge');
const processStatus = document.querySelector('#process-status');
const liveArtifactCount = document.querySelector('#live-artifact-count');
const liveArtifact = document.querySelector('#live-artifact');
const finalReportCard = document.querySelector('#final-report-card');
const reportReadyNotice = document.querySelector('#report-ready-notice');
const artifactDetailModal = document.querySelector('#artifact-detail-modal');
const artifactDetailTitle = document.querySelector('#artifact-detail-title');
const artifactDetailTicker = document.querySelector('#artifact-detail-ticker');
const artifactDetailDate = document.querySelector('#artifact-detail-date');
const artifactDetailContent = document.querySelector('#artifact-detail-content');
let pollTimer = null;
let stageTimer = null;
let currentStage = 0;
let currentAnalysisRecord = null;

const today = new Date();
const localToday = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
document.querySelector('#trade-date').value = localToday;
document.querySelector('#trade-date').max = localToday;

document.querySelector('#locator-trigger').addEventListener('click', () => {
  if (!modelProfilesLoaded) {
    loadModelCenter().catch(() => {});
  }
  if (!modelProfileSelect.value) {
    note.textContent = '请先选择研究模型。';
    note.classList.add('error');
    return;
  }
  openModal(locatorPanel);
  window.setTimeout(() => document.querySelector('#company-query').focus(), 300);
});

document.querySelector('#locator-close').addEventListener('click', () => {
  closeModal(locatorPanel);
});

locatorPanel.addEventListener('click', (event) => {
  if (event.target === locatorPanel) closeModal(locatorPanel);
});

// 公司描述框：Enter 提交，Shift+Enter 换行；中文输入法组合期间不抢占 Enter。
document.querySelector('#company-query').addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  locatorForm.requestSubmit();
});

function renderLocatorResults(data) {
  if (data.status === 'model_required') {
    locatorResults.innerHTML = `
      <div class="locator-empty">
        <strong>请先配置研究模型</strong>
        <p>${escapeHtml(data.message || '公司描述理解需要一个可用的日常分析模型。')}</p>
        <button class="secondary-button locator-configure-model" type="button">打开模型配置</button>
      </div>`;
    locatorResults.querySelector('.locator-configure-model').addEventListener('click', openModelCenter);
    return;
  }
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
    // 与首页“研究模型”保持一致：必须使用用户明确选择的配置。
    if (!modelProfilesLoaded) {
      await loadModelCenter();
    }
    const modelProfileId = modelProfileSelect.value;
    if (!modelProfileId) {
      locatorState.classList.add('hidden');
      renderLocatorResults({ status: 'model_required', message: '请先添加并选择一个研究模型，系统会使用其中的日常分析模型。' });
      return;
    }
    modelProfileSelect.value = modelProfileId;
    const response = await fetch('/api/instruments/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        market: document.querySelector('#company-market').value,
        use_ai: true,
        model_profile_id: modelProfileId,
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

const historyPagination = document.querySelector('#history-pagination');
const historyFilter = document.querySelector('#history-filter');
const historyQuery = document.querySelector('#history-query');
const historyReportList = document.querySelector('#history-report-list');
const historyPageControls = document.querySelector('#history-page-controls');
const reportDeleteButton = document.querySelector('#report-delete');
const reportCloseButton = document.querySelector('#report-close');
const HISTORY_PAGE_SIZE = 10;
let historyCurrentPage = 1;
let historyTotal = 0;
let historyLoadSequence = 0;
let currentReportId = '';

function closeModal(modal) {
  modal.classList.add('hidden');
  if (!document.querySelector('.modal-backdrop:not(.hidden)')) document.body.classList.remove('modal-open');
}

function openModal(modal) {
  modal.classList.remove('hidden');
  document.body.classList.add('modal-open');
}

function renderHistoryPagination(total, page) {
  const pageCount = Math.max(1, Math.ceil(total / HISTORY_PAGE_SIZE));
  historyPagination.classList.toggle('hidden', pageCount <= 1);
  const candidates = [...new Set([1, page - 1, page, page + 1, pageCount])]
    .filter((number) => number >= 1 && number <= pageCount)
    .sort((a, b) => a - b);
  const pageItems = [];
  candidates.forEach((number, index) => {
    if (index && number - candidates[index - 1] > 1) pageItems.push('<span class="history-page-ellipsis" aria-hidden="true">…</span>');
    pageItems.push(`<button class="history-page-number${number === page ? ' is-current' : ''}" type="button" data-history-page="${number}"${number === page ? ' aria-current="page"' : ''}>${number}</button>`);
  });
  historyPageControls.innerHTML = `
    <button class="history-page-arrow" type="button" data-history-page="${page - 1}"${page <= 1 ? ' disabled' : ''} aria-label="上一页">‹</button>
    ${pageItems.join('')}
    <button class="history-page-arrow" type="button" data-history-page="${page + 1}"${page >= pageCount ? ' disabled' : ''} aria-label="下一页">›</button>`;
}

function renderHistoryPicker(items, page, total) {
  historyTotal = total;
  historyCurrentPage = page;
  if (!items.length) {
    historyReportList.innerHTML = '<div class="history-report-empty"><span class="history-empty-mark">⌕</span><strong>暂时没有匹配的研报</strong><p>可以更换股票代码搜索，或先生成一份新研报。</p></div>';
  } else {
    historyReportList.innerHTML = items.map((item, index) => {
      const generated = item.generated_at ? item.generated_at.replace('T', ' ').slice(0, 16) : '时间未知';
      const assetLabel = item.asset_type === 'crypto' ? 'DIGITAL ASSET' : 'EQUITY RESEARCH';
      return `<article class="history-report-card">
        <div class="history-report-card-top">
          <span class="history-report-code">${escapeHtml(item.ticker)}</span>
          <span class="history-report-kind">${assetLabel}</span>
          <span class="history-report-index">${String((page - 1) * HISTORY_PAGE_SIZE + index + 1).padStart(2, '0')}</span>
        </div>
        <h3>${escapeHtml(item.ticker)} <span>投资研究报告</span></h3>
        <div class="history-report-meta">
          <span><small>分析日期</small><strong>${escapeHtml(item.trade_date || '日期未知')}</strong></span>
          <span><small>生成时间</small><strong>${escapeHtml(generated)}</strong></span>
        </div>
        <button class="history-report-open" type="button" data-history-report-id="${escapeHtml(item.id)}"><span>查看完整研报</span><b aria-hidden="true">→</b></button>
      </article>`;
    }).join('');
  }
  renderHistoryPagination(total, page);
}

async function loadHistoryPicker(query = historyQuery.value.trim(), page = 1) {
  const requestSequence = ++historyLoadSequence;
  historyReportList.innerHTML = '<div class="history-report-empty"><strong>正在读取历史研报…</strong></div>';
  try {
    const params = new URLSearchParams({
      limit: String(HISTORY_PAGE_SIZE),
      offset: String((page - 1) * HISTORY_PAGE_SIZE),
    });
    if (query) params.set('query', query);
    const response = await fetch(`/api/reports?${params.toString()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('历史研报暂时无法读取');
    const data = await response.json();
    if (requestSequence !== historyLoadSequence) return;
    const pageCount = Math.max(1, Math.ceil(Number(data.total || 0) / HISTORY_PAGE_SIZE));
    if (page > pageCount) {
      await loadHistoryPicker(query, pageCount);
      return;
    }
    renderHistoryPicker(data.reports || [], page, Number(data.total || 0));
  } catch (error) {
    if (requestSequence !== historyLoadSequence) return;
    historyReportList.innerHTML = `<div class="history-report-empty"><strong>${escapeHtml(error.message || '历史研报暂时无法读取')}</strong><p>请稍后重试。</p></div>`;
    historyPageControls.innerHTML = '';
    historyPagination.classList.add('hidden');
  }
}

async function openHistoricalReportById(reportId) {
  if (!reportId) return;
  const trigger = [...historyReportList.querySelectorAll('[data-history-report-id]')]
    .find((button) => button.dataset.historyReportId === reportId);
  if (trigger) { trigger.disabled = true; trigger.innerHTML = '<span>正在打开…</span><b aria-hidden="true">…</b>'; }
  try {
    const response = await fetch(`/api/reports/${encodeURIComponent(reportId)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('历史报告不存在或已损坏');
    const historical = await response.json();
    showReport({ ...historical, status: 'completed', phase: '历史报告' });
  } catch (error) {
    window.alert(error.message || '历史研报暂时无法打开');
  } finally {
    if (trigger?.isConnected) { trigger.disabled = false; trigger.innerHTML = '<span>查看完整研报</span><b aria-hidden="true">→</b>'; }
  }
}

historyFilter.addEventListener('submit', (event) => {
  event.preventDefault();
  loadHistoryPicker(historyQuery.value.trim(), 1);
});
historyPageControls.addEventListener('click', (event) => {
  const button = event.target.closest('[data-history-page]');
  if (!button || button.disabled) return;
  loadHistoryPicker(historyQuery.value.trim(), Number(button.dataset.historyPage));
});
historyReportList.addEventListener('click', (event) => {
  const button = event.target.closest('[data-history-report-id]');
  if (button) openHistoricalReportById(button.dataset.historyReportId);
});

const modelSettings = document.querySelector('#model-settings');
const modelProfileSelect = document.querySelector('#model-profile');
const modelProfileList = document.querySelector('#model-profile-list');
const modelProfileForm = document.querySelector('#model-profile-form');
const modelTemplate = document.querySelector('#model-template');
const modelTemplatePicker = document.querySelector('#model-template-picker');
const modelTemplateTrigger = document.querySelector('#model-template-trigger');
const modelTemplateMenu = document.querySelector('#model-template-menu');
const modelStatus = document.querySelector('#model-form-status');
let modelProfiles = [];
let modelTemplates = [];
let discoveredModelOptions = [];
let modelProfilesLoaded = false;

const providerIconMeta = {
  custom: { glyph: '✦', tone: 'mint' },
  deepseek: { glyph: 'DS', tone: 'cyan', logo: 'https://www.deepseek.com/favicon.ico' },
  volcengine: { glyph: '火', tone: 'blue', logo: 'https://portal.volccdn.com/obj/volcfe/misc/favicon.png' },
  'minimax-cn': { glyph: 'M', tone: 'coral', logo: 'https://www.minimaxi.com/favicon.ico' },
  minimax: { glyph: 'M', tone: 'coral', logo: 'https://www.minimax.io/favicon.ico' },
  'glm-cn': { glyph: 'Z', tone: 'slate', logo: 'https://open.bigmodel.cn/static/images/favicon.png' },
  'qwen-cn': { glyph: '阿', tone: 'orange', logo: 'https://assets.alicdn.com/g/qwenweb/qwen-chat-fe/0.2.91/static/images/qwen-logo.svg' },
  qwen: { glyph: '阿', tone: 'orange', logo: 'https://assets.alicdn.com/g/qwenweb/qwen-chat-fe/0.2.91/static/images/qwen-logo.svg' },
  'xiaomi-mimo': { glyph: 'mi', tone: 'xiaomi', logo: '/static/xiaomi-official.png?v=mi-official-1' },
  siliconflow: { glyph: 'SF', tone: 'indigo', logo: 'https://www.siliconflow.cn/favicon.ico' },
  'z-ai': { glyph: 'Z', tone: 'violet', logo: 'https://z-cdn.chatglm.cn/z-ai/static/logo.svg' },
  openrouter: { glyph: '◈', tone: 'violet', logo: 'https://openrouter.ai/favicon.ico' },
  'kimi-cn': { glyph: 'K', tone: 'slate', logo: 'https://www.moonshot.cn/favicon.ico' },
  kimi: { glyph: 'K', tone: 'slate', logo: 'https://www.moonshot.ai/favicon.ico' },
  byteplus: { glyph: 'BP', tone: 'blue', logo: 'https://sf-bpcms.bytepluscdn.com/obj/byteplus-public-aiso/portal/assets/favicon.png' },
  'aws-bedrock': { glyph: 'aws', tone: 'amber', logo: 'https://aws.amazon.com/favicon.ico' },
  'tencent-hunyuan': { glyph: '云', tone: 'cyan', logo: 'https://cloud.tencent.com/favicon.ico' },
  moark: { glyph: 'MO', tone: 'green', logo: 'https://www.moark.com/favicon.ico' },
  ppio: { glyph: 'P', tone: 'coral', logo: 'https://ppio.com/favicon.ico' },
  openai: { glyph: 'AI', tone: 'dark', logo: 'https://openai.com/favicon.svg' },
  groq: { glyph: 'G', tone: 'amber', logo: 'https://groq.com/favicon.ico' },
  'xai-grok': { glyph: 'X', tone: 'dark', logo: 'https://x.ai/favicon.ico' },
  'opencode-zen': { glyph: 'OC', tone: 'dark', logo: 'https://opencode.ai/favicon.ico' },
};

function providerIconMarkup(template) {
  const meta = providerIconMeta[template.id] || { glyph: String(template.name || '?').slice(0, 2).toUpperCase(), tone: 'neutral' };
  const logo = meta.logo
    ? `<img class="provider-logo" src="${escapeHtml(meta.logo)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.hidden=true;this.nextElementSibling.hidden=false;" />`
    : '';
  return `<span class="provider-icon provider-icon-${meta.tone} provider-icon-${escapeHtml(template.id)}" aria-hidden="true">${logo}<span class="provider-icon-glyph"${logo ? ' hidden' : ''}>${escapeHtml(meta.glyph)}</span></span>`;
}

function renderModelTemplatePicker() {
  const selected = modelTemplates.find((item) => item.id === modelTemplate.value) || modelTemplates[0];
  if (!selected) {
    modelTemplateTrigger.querySelector('.provider-picker-label').textContent = '暂无服务商模板';
    modelTemplateMenu.innerHTML = '';
    return;
  }
  modelTemplateTrigger.innerHTML = `${providerIconMarkup(selected)}<span class="provider-picker-label">${escapeHtml(selected.name)}</span><b aria-hidden="true">⌄</b>`;
  modelTemplateMenu.innerHTML = modelTemplates.map((item) => `
    <button class="provider-picker-option${item.id === selected.id ? ' is-selected' : ''}" type="button" role="option" aria-selected="${item.id === selected.id}" data-template-id="${escapeHtml(item.id)}">
      ${providerIconMarkup(item)}
      <span class="provider-option-copy"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.base_url || '自定义 Endpoint')}</small></span>
      <i aria-hidden="true">${item.id === selected.id ? '✓' : ''}</i>
    </button>`).join('');
  modelTemplateMenu.querySelectorAll('[data-template-id]').forEach((option) => {
    option.addEventListener('click', () => {
      modelTemplate.value = option.dataset.templateId;
      modelTemplate.dispatchEvent(new Event('change', { bubbles: true }));
      closeModelTemplatePicker();
      modelTemplateTrigger.focus();
    });
  });
}

function closeModelTemplatePicker() {
  modelTemplateMenu.classList.add('hidden');
  modelTemplateTrigger.setAttribute('aria-expanded', 'false');
}

function toggleModelTemplatePicker() {
  const isOpen = !modelTemplateMenu.classList.contains('hidden');
  if (isOpen) closeModelTemplatePicker();
  else {
    renderModelTemplatePicker();
    modelTemplateMenu.classList.remove('hidden');
    modelTemplateTrigger.setAttribute('aria-expanded', 'true');
  }
}

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
}

function resetModelForm() {
  modelProfileForm.reset();
  document.querySelector('#editing-profile-id').value = '';
  document.querySelector('#model-form-title').textContent = '新增模型 Endpoint';
  setModelStatus();
  showDiscoveredModels();
  const custom = modelTemplates.find((item) => item.id === 'custom');
  if (custom) modelTemplate.value = custom.id;
  renderModelTemplatePicker();
}

function populateModelForm(profile) {
  document.querySelector('#editing-profile-id').value = profile.id;
  document.querySelector('#model-name').value = profile.name || '';
  modelTemplate.value = profile.template || 'custom';
  renderModelTemplatePicker();
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
  const activeProfileId = modelProfiles.some((profile) => profile.id === selected)
    ? selected
    : '';
  modelProfileSelect.innerHTML = '<option value="">请选择已添加的模型</option>' + modelProfiles.map((profile) => `<option value="${escapeHtml(profile.id)}"${profile.id === activeProfileId ? ' selected' : ''}>${escapeHtml(profile.name)} · ${escapeHtml(profile.quick_model)}</option>`).join('');
  modelProfileSelect.value = activeProfileId;
  if (!modelProfiles.length) {
    modelProfileList.innerHTML = '<p class="profile-empty">还没有模型配置，请先添加一个模型。</p>';
    return;
  }
  const editing = currentProfileId();
  modelProfileList.innerHTML = modelProfiles.map((profile) => `<div class="saved-profile-row"><button class="saved-profile ${profile.id === editing ? 'active' : ''}" type="button" data-profile-id="${escapeHtml(profile.id)}"><strong>${escapeHtml(profile.name)}</strong><small>${escapeHtml(profile.quick_model)} · ${profile.has_api_key ? '已配置密钥' : '无密钥'}</small></button><button class="saved-profile-delete" type="button" data-delete-profile-id="${escapeHtml(profile.id)}" aria-label="删除 ${escapeHtml(profile.name)}" title="删除配置"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="M7 7l1 13h8l1-13"></path><path d="M10 11v5M14 11v5"></path></svg></button></div>`).join('');
  modelProfileList.querySelectorAll('.saved-profile[data-profile-id]').forEach((button) => {
    button.addEventListener('click', () => {
      const profile = modelProfiles.find((item) => item.id === button.dataset.profileId);
      if (profile) {
        // 左侧配置列表与首页下拉框必须指向同一个当前模型；否则新增模型后点击旧配置只会编辑旧配置，实际分析仍会使用新模型。
        modelProfileSelect.value = profile.id;
        populateModelForm(profile);
        renderModelProfiles();
      }
    });
  });
  modelProfileList.querySelectorAll('.saved-profile-delete[data-delete-profile-id]').forEach((button) => {
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      deleteModelProfile(button.dataset.deleteProfileId);
    });
  });
}

modelProfileSelect.addEventListener('change', () => {
  const profile = modelProfiles.find((item) => item.id === modelProfileSelect.value);
  if (profile) populateModelForm(profile);
  else resetModelForm();
  renderModelProfiles();
});

async function fetchModelJson(url, options = {}, action = '读取模型配置') {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(`${action}失败：无法连接应用服务，请确认后端已启动，并通过应用地址打开页面。`);
    }
    throw error;
  }
  let data = {};
  try {
    data = await response.json();
  } catch {
    // Keep the HTTP status message when the server returns a non-JSON body.
  }
  if (!response.ok) throw new Error(data.detail || `${action}失败（HTTP ${response.status}）`);
  return data;
}

async function loadModelCenter() {
  const [templates, profiles] = await Promise.all([
    fetchModelJson('/api/model-templates', { cache: 'no-store' }, '读取服务商模板'),
    fetchModelJson('/api/model-profiles', { cache: 'no-store' }, '读取已保存配置'),
  ]);
  modelTemplates = templates.templates || [];
  modelProfiles = profiles.profiles || [];
  modelTemplate.innerHTML = modelTemplates.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  renderModelTemplatePicker();
  renderModelProfiles();
  modelProfilesLoaded = true;
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
modelTemplateTrigger.addEventListener('click', toggleModelTemplatePicker);
modelTemplateTrigger.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    toggleModelTemplatePicker();
  } else if (event.key === 'Escape') {
    closeModelTemplatePicker();
  }
});
document.addEventListener('click', (event) => {
  if (!modelTemplatePicker.contains(event.target)) closeModelTemplatePicker();
});

modelTemplate.addEventListener('change', () => {
  renderModelTemplatePicker();
  const template = modelTemplates.find((item) => item.id === modelTemplate.value);
  const urlInput = document.querySelector('#model-base-url');
  if (template?.base_url) urlInput.value = template.base_url;
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
  const codeSpans = [];
  const links = [];
  let html = escapeHtml(text).replace(/`([^`]+)`/g, (_match, code) => {
    const token = `@@CODE_SPAN_${codeSpans.length}@@`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/gi, (_match, label, url) => {
    const token = `@@MARKDOWN_LINK_${links.length}@@`;
    links.push(`<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`);
    return token;
  });
  html = html
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
    .replace(/~~(.+?)~~/g, '<del>$1</del>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
  html = links.reduce((result, link, index) => result.replace(`@@MARKDOWN_LINK_${index}@@`, link), html);
  return codeSpans.reduce((result, code, index) => result.replace(`@@CODE_SPAN_${index}@@`, code), html);
}

function renderMarkdown(markdown = '') {
  const lines = String(markdown).split(/\r?\n/);
  let html = '';
  let paragraph = [];
  let listType = '';
  let tableRows = [];
  let quoteLines = [];
  let codeLines = null;
  let codeLanguage = '';

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html += `<p>${inlineMarkdown(paragraph.join(' '))}</p>`;
    paragraph = [];
  };
  const flushList = () => {
    if (listType) { html += `</${listType}>`; listType = ''; }
  };
  const flushTable = () => {
    if (!tableRows.length) return;
    const rows = tableRows.filter((row) => !row.every((cell) => /^:?-{3,}:?$/.test(cell)));
    if (rows.length) {
      const columns = rows[0].length;
      const cells = (row, tag) => Array.from({ length: columns }, (_, index) => `<${tag}>${inlineMarkdown(row[index] || '')}</${tag}>`).join('');
      html += '<div class="markdown-table-wrap"><table><thead><tr>' + cells(rows[0], 'th') + '</tr></thead><tbody>';
      html += rows.slice(1).map((row) => `<tr>${cells(row, 'td')}</tr>`).join('');
      html += '</tbody></table></div>';
    }
    tableRows = [];
  };
  const flushQuote = () => {
    if (!quoteLines.length) return;
    html += `<blockquote><p>${inlineMarkdown(quoteLines.join(' '))}</p></blockquote>`;
    quoteLines = [];
  };
  const flushBlocks = () => { flushParagraph(); flushList(); flushTable(); flushQuote(); };

  for (const raw of lines) {
    const line = raw.trim();
    if (codeLines) {
      if (/^```\s*$/.test(line)) {
        const languageClass = codeLanguage && /^[a-z0-9_-]+$/i.test(codeLanguage) ? ` class="language-${escapeHtml(codeLanguage)}"` : '';
        html += `<pre><code${languageClass}>${escapeHtml(codeLines.join('\n'))}</code></pre>`;
        codeLines = null;
        codeLanguage = '';
      } else codeLines.push(raw);
      continue;
    }
    const fence = line.match(/^```\s*([a-z0-9_-]*)\s*$/i);
    if (fence) { flushBlocks(); codeLines = []; codeLanguage = fence[1]; continue; }

    if (line.includes('|') && (line.startsWith('|') || line.endsWith('|'))) {
      flushParagraph(); flushList(); flushQuote();
      tableRows.push(line.replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim()));
      continue;
    }
    flushTable();
    if (!line) { flushBlocks(); continue; }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    const unordered = line.match(/^[-*+]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (heading) {
      flushBlocks();
      const level = heading[1].length;
      html += `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;
    } else if (/^(?:[-*_]\s*){3,}$/.test(line)) {
      flushBlocks(); html += '<hr />';
    } else if (line.startsWith('>')) {
      flushParagraph(); flushList();
      quoteLines.push(line.replace(/^>\s?/, ''));
    } else if (unordered || ordered) {
      flushParagraph(); flushQuote();
      const nextType = unordered ? 'ul' : 'ol';
      if (listType !== nextType) { flushList(); listType = nextType; html += `<${listType}>`; }
      html += `<li>${inlineMarkdown((unordered || ordered)[1])}</li>`;
    } else {
      flushList(); flushQuote();
      paragraph.push(line);
    }
  }
  if (codeLines) html += `<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`;
  flushBlocks();
  return html || '<p>本章节没有可用内容。</p>';
}

function stageIndexForArtifacts(artifacts = []) {
  const ids = new Set(artifacts.map((item) => item.id));
  if (ids.has('final_trade_decision')) return 4;
  if (ids.has('risk_debate_state')) return 3;
  if (ids.has('investment_debate_state') || ids.has('trader_investment_plan')) return 2;
  if (artifacts.length) return 1;
  return 0;
}

const PROCESS_STAGE_VISUALS = [
  {
    id: 'data-gathering',
    src: '/static/stages/data-gathering.jpg?v=stage-visuals-1',
    kicker: 'DATA COLLECTION',
    label: '市场资料汇集中',
    title: '研究团队正在收集资料',
    message: '行情、公司信息、新闻与市场情绪资料正在汇集。',
    alt: '行情、公司资料、新闻和市场信号同时汇入研究数据中心',
  },
  {
    id: 'four-analysts',
    src: '/static/stages/four-analysts.jpg?v=stage-visuals-1',
    kicker: '4 ANALYSTS · PARALLEL',
    label: '四个分析面并行中',
    title: '四个分析面并行研究',
    message: '技术面、基本面、新闻与市场情绪分析同步运行。',
    alt: '技术面、基本面、新闻和市场情绪四个分析面同时开展研究',
  },
  {
    id: 'bull-bear-debate',
    src: '/static/stages/bull-bear-debate.jpg?v=stage-visuals-1',
    kicker: 'BULL VS BEAR',
    label: '多空观点往返讨论',
    title: 'Bull / Bear 多空研究',
    message: '看多与看空研究员轮流论证，再由研究经理汇总。',
    alt: '看多与看空双方围绕证据进行讨论，由中心裁决点平衡观点',
  },
  {
    id: 'risk-review',
    src: '/static/stages/risk-review.jpg?v=stage-visuals-1',
    kicker: 'RISK REVIEW',
    label: '三方风险讨论中',
    title: '风险团队正在评估',
    message: '激进、保守与中性风险分析师依次讨论交易方案。',
    alt: '盾牌代表风险控制，周围三个指标代表不同风险视角',
  },
  {
    id: 'report-ready',
    src: '/static/stages/report-ready.jpg?v=stage-visuals-1',
    kicker: 'REPORT SYNTHESIS',
    label: '最终研报整理中',
    title: '正在形成最终研报',
    message: '投资组合经理正在综合分析结论并生成最终决策。',
    alt: '分析报告正在汇总并完成确认',
  },
];

function updateStageVisual(stageIndex, record = {}) {
  const visual = PROCESS_STAGE_VISUALS[stageIndex] || PROCESS_STAGE_VISUALS[0];
  if (processStageImage.dataset.stage !== visual.id) {
    processStageImage.classList.add('is-changing');
    processStageImage.onload = () => processStageImage.classList.remove('is-changing');
    processStageImage.onerror = () => processStageImage.classList.remove('is-changing');
    processStageImage.src = visual.src;
    processStageImage.dataset.stage = visual.id;
  }
  const isComplete = record.status === 'completed';
  const isFailed = record.status === 'failed';
  stageVisual.classList.toggle('is-complete', isComplete);
  stageVisual.classList.toggle('is-failed', isFailed);
  processStageImage.alt = visual.alt;
  stageVisual.setAttribute('aria-label', visual.alt);
  processCoreKicker.textContent = isComplete ? 'REPORT READY' : isFailed ? 'ANALYSIS STOPPED' : visual.kicker;
  processCoreLabel.textContent = isComplete ? '研报已完成' : isFailed ? '分析任务中断' : visual.label;
  document.querySelector('#process-title').textContent = isComplete
    ? '研究任务已完成'
    : isFailed ? '本次分析未完成' : visual.title;
  document.querySelector('#process-message').textContent = isComplete
    ? '完整研报已生成，阶段产物也已整理完成。'
    : isFailed ? (record.error || '任务中断，已生成的阶段产物仍可查看。')
      : visual.message;
}

function renderProcessArtifacts(record = {}) {
  const artifacts = Array.isArray(record.artifacts) ? [...record.artifacts] : [];
  artifacts.sort((left, right) => String(left.updated_at || '').localeCompare(String(right.updated_at || '')));
  currentAnalysisRecord = record;
  const isComplete = record.status === 'completed';
  const latest = isComplete ? null : artifacts[artifacts.length - 1];
  const completedArtifacts = isComplete || !latest
    ? artifacts
    : artifacts.filter((artifact) => artifact.id !== latest.id);
  const analystDimensions = [
    { id: 'market_report', key: 'market', title: '技术面分析' },
    { id: 'fundamentals_report', key: 'fundamentals', title: '基本面分析' },
    { id: 'news_report', key: 'news', title: '新闻分析' },
    { id: 'sentiment_report', key: 'sentiment', title: '市场情绪' },
  ];
  const missingDimensions = isComplete
    ? analystDimensions.filter(({ id, key }) =>
      !String(record.result?.reports?.[key] || '').trim())
    : [];
  const unavailableArtifactIds = new Set(missingDimensions.map(({ id }) => id));
  const visibleCompletedArtifacts = completedArtifacts.filter((artifact) => !unavailableArtifactIds.has(artifact.id));
  const stageIndex = isComplete ? 4 : stageIndexForArtifacts(artifacts);
  currentStage = stageIndex;
  stages.forEach((stage, index) => {
    stage.className = `stage${isComplete || index < stageIndex ? ' done' : index === stageIndex ? ' active' : ''}`;
  });
  updateStageVisual(stageIndex, record);
  processStatus.classList.toggle('is-complete', isComplete);
  processStatus.classList.toggle('is-failed', record.status === 'failed');
  processStatus.querySelector('span').textContent = isComplete
    ? '分析已完成'
    : record.status === 'failed' ? '分析未完成' : record.status === 'queued' ? '等待开始' : '分析进行中';
  if (isComplete) {
    reportReadyNotice.classList.remove('hidden');
  } else {
    reportReadyNotice.classList.add('hidden');
  }

  liveArtifactCount.textContent = latest ? '最新更新' : isComplete ? '已完成' : '等待中';
  liveArtifact.innerHTML = latest ? `
    <article class="live-artifact-entry">
      <div class="artifact-card-heading"><strong>${escapeHtml(artifacts.length ? latest.title || '最新阶段产物' : '正在研究')}</strong><span class="artifact-state-pill is-live">实时更新</span></div>
      <p>${escapeHtml(latest.preview || '研究团队正在生成内容…')}</p>
      <small>${Number(latest.chars || 0).toLocaleString()} 字符 · ${escapeHtml(record.phase || '研究中')}</small>
      <button class="artifact-open-button" type="button" data-open-artifact="${escapeHtml(latest.id)}">查看当前内容</button>
    </article>` : `<div class="artifact-empty">${isComplete ? '分析已完成，所有阶段产物已整理在下方。' : '研究产物生成后会显示在这里。'}</div>`;

  const completedCount = visibleCompletedArtifacts.length + (isComplete && record.result ? 1 : 0);
  artifactCount.textContent = `${completedCount} 份${missingDimensions.length ? ` · ${missingDimensions.length} 项未生成` : ''}`;
  const missingCards = missingDimensions.map(({ title }) => `
    <article class="artifact-item is-unavailable">
      <div class="artifact-card-heading"><strong>${escapeHtml(title)}</strong><span class="artifact-state-pill is-unavailable">未生成</span></div>
      <p>本次没有生成独立分析内容。请在完整研报中查看数据限制，不要用其他分析面代替。</p>
    </article>`).join('');
  const generatedCards = visibleCompletedArtifacts.slice().reverse().map((artifact) => `
    <article class="artifact-item">
      <div class="artifact-card-heading"><strong>${escapeHtml(artifact.title || '阶段报告')}</strong><span class="artifact-state-pill">已生成</span></div>
      <p>${escapeHtml(artifact.preview || '报告内容已生成，可打开查看。')}</p>
      <small>${Number(artifact.chars || 0).toLocaleString()} 字符</small>
      <button class="artifact-open-button" type="button" data-open-artifact="${escapeHtml(artifact.id)}">查看报告</button>
    </article>`).join('');
  artifactStream.innerHTML = missingCards + generatedCards
    || '<div class="artifact-empty">已生成的阶段报告会即时归档在这里。</div>';

  if (isComplete && record.result) {
    const completedAt = record.updated_at ? new Date(record.updated_at).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
    finalReportCard.innerHTML = `
      <article class="final-report-entry">
        <div class="artifact-card-heading"><strong>${escapeHtml(record.ticker)} 完整投资研报</strong><span class="artifact-state-pill is-complete">已完成</span></div>
        <p>${escapeHtml(field(record.result.decision_fields, 'executive_summary') || '完整研报已生成，包含技术面、基本面、新闻、情绪与风险分析。')}</p>
        <small>${completedAt ? `${escapeHtml(completedAt)} 生成` : '刚刚生成'}</small>
        <button class="artifact-open-button is-primary" type="button" data-open-final-report>查看完整报告</button>
      </article>`;
    finalReportCard.classList.remove('hidden');
  } else {
    finalReportCard.classList.add('hidden');
    finalReportCard.innerHTML = '';
  }
}

function startStageAnimation() {
  window.clearInterval(stageTimer);
  currentStage = 0;
  stages.forEach((stage, index) => stage.className = `stage${index === 0 ? ' active' : ''}`);
  updateStageVisual(0);
  artifactCount.textContent = '0 份产物';
  liveArtifactCount.textContent = '等待中';
  liveArtifact.innerHTML = '<div class="artifact-empty">研究产物生成后会显示在这里。</div>';
  artifactStream.innerHTML = '<div class="artifact-empty">正在等待第一份研究产物…</div>';
  finalReportCard.classList.add('hidden');
  finalReportCard.innerHTML = '';
  reportReadyNotice.classList.add('hidden');
  processStatus.classList.remove('is-complete', 'is-failed');
  processStatus.querySelector('span').textContent = '分析进行中';
}

function completeStages() {
  window.clearInterval(stageTimer);
  stages.forEach((stage) => stage.className = 'stage done');
}

function field(fields, name) {
  return fields?.[name] || '—';
}

function marketLabelForTicker(ticker) {
  if (/^\d{6}(?:\.(?:SS|SZ|BJ))?$/.test(ticker)) return 'A 股';
  if (/^\d{4,5}\.HK$/.test(ticker)) return '港股';
  return '美股';
}

async function openProgressArtifact(artifactId) {
  artifactDetailTicker.textContent = `${currentAnalysisRecord?.ticker || ''} · 阶段产物`;
  artifactDetailTitle.textContent = '正在读取报告…';
  artifactDetailDate.textContent = '';
  artifactDetailContent.innerHTML = '<p>正在加载已生成的分析内容…</p>';
  openModal(artifactDetailModal);
  try {
    const response = await fetch(`/api/analyses/${encodeURIComponent(currentAnalysisRecord.id)}/artifacts/${encodeURIComponent(artifactId)}`, { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '阶段报告暂时无法读取');
    artifactDetailTicker.textContent = `${data.ticker} · 阶段报告`;
    artifactDetailTitle.textContent = data.title;
    artifactDetailDate.textContent = `分析日期 ${data.trade_date} · 内容随研究进度更新`;
    artifactDetailContent.innerHTML = renderMarkdown(data.content || '本章节暂时没有可展示的内容。');
  } catch (error) {
    artifactDetailTitle.textContent = '报告暂时无法读取';
    artifactDetailContent.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
  }
}

processPanel.addEventListener('click', (event) => {
  const finalButton = event.target.closest('[data-open-final-report]');
  if (finalButton && currentAnalysisRecord?.result) {
    showReport(currentAnalysisRecord);
    return;
  }
  const artifactButton = event.target.closest('[data-open-artifact]');
  if (artifactButton && currentAnalysisRecord?.id) openProgressArtifact(artifactButton.dataset.openArtifact);
});

document.querySelector('#open-completed-report').addEventListener('click', () => {
  if (currentAnalysisRecord?.result) showReport(currentAnalysisRecord);
});
document.querySelector('#artifact-detail-close').addEventListener('click', () => closeModal(artifactDetailModal));
artifactDetailModal.addEventListener('click', (event) => { if (event.target === artifactDetailModal) closeModal(artifactDetailModal); });

function showReport(record) {
  const result = record.result || {};
  const reports = result.reports || {};
  const research = result.research || {};
  const risk = result.risk || {};
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
    ['技术面分析', reports.market || '> 本次没有生成独立的技术面分析内容，请将此项视为缺失。'],
    ['基本面分析', reports.fundamentals || '> 本次没有生成独立的基本面分析内容，请将此项视为缺失。'],
    ['新闻分析', reports.news || '> 本次没有生成独立新闻分析报告。情绪分析中可能提及新闻标题，但不能替代新闻研究员的独立分析；请将此项视为缺失，不要据此推断新闻结论。'],
    ['市场情绪', reports.sentiment || '> 本次没有生成独立的市场情绪分析内容，请将此项视为缺失。'],
    ['看多观点', research.bull],
    ['看空观点', research.bear],
    ['研究结论', research.manager],
    ['交易方案', result.trader_report],
    ['风险评估', [risk.aggressive, risk.neutral, risk.conservative].filter(Boolean).join('\n\n---\n\n')],
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
  openModal(reportPanel);
  reportCloseButton.focus();
  loadHistoryPicker(historyQuery.value.trim(), historyCurrentPage);
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
    await loadHistoryPicker(historyQuery.value.trim(), historyCurrentPage);
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
});
reportPanel.addEventListener('click', (event) => { if (event.target === reportPanel) closeModal(reportPanel); });

async function poll(taskId) {
  try {
    const response = await fetch(`/api/analyses/${taskId}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('无法读取分析任务');
    const record = await response.json();
    renderProcessArtifacts(record);
    if (record.status === 'completed') {
      window.clearTimeout(pollTimer);
      completeStages();
      loadHistoryPicker();
      submitButton.disabled = false;
      return;
    }
    if (record.status === 'failed') {
      window.clearTimeout(pollTimer);
      document.querySelector('#process-title').textContent = '分析暂未完成';
      document.querySelector('#process-message').textContent = record.error || '分析遇到问题，请检查模型和数据源后重试。';
      processStatus.classList.add('is-failed');
      submitButton.disabled = false;
      return;
    }
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
  const modelProfileId = modelProfileSelect.value;
  if (!modelProfileId) {
    note.textContent = modelProfiles.length ? '请先选择一个已添加的模型。' : '请先在“管理模型”中添加一个模型。';
    note.classList.add('error');
    return;
  }
  note.textContent = '分析任务启动后请保持页面打开。';
  submitButton.disabled = true;
  const ticker = document.querySelector('#ticker').value.trim().toUpperCase();
  currentAnalysisRecord = null;
  reportPanel.classList.add('hidden');
  processStockTitle.textContent = `${ticker} 投资研究`;
  processMarketBadge.textContent = marketLabelForTicker(ticker);
  document.querySelector('#process-title').textContent = '研究团队正在协作';
  document.querySelector('#process-message').textContent = '正在连接研究流水线，稍后会陆续出现阶段性产物。';
  processPanel.classList.remove('hidden');
  processPanel.scrollIntoView({ behavior: 'smooth', block: 'center' });
  startStageAnimation();

  const payload = {
    ticker,
    trade_date: document.querySelector('#trade-date').value,
    // 当前页面只提供股票研报入口；后端仍保留 crypto 能力供 API/历史任务兼容。
    asset_type: 'stock',
    analysts: ['market', 'social', 'news', 'fundamentals'],
    model_profile_id: modelProfileId,
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
  document.querySelector('#hero').scrollIntoView({ behavior: 'smooth' });
  document.querySelector('#ticker').focus();
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  const openBackdrop = document.querySelector('.modal-backdrop:not(.hidden)');
  if (openBackdrop) closeModal(openBackdrop);
});
