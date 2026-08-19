const form = document.querySelector('#analysis-form');
const note = document.querySelector('#form-note');
const processPanel = document.querySelector('#process');
const reportPanel = document.querySelector('#report');
const stages = [...document.querySelectorAll('.stage')];
const submitButton = form.querySelector('button[type="submit"]');
let pollTimer = null;
let stageTimer = null;
let currentStage = 0;

const today = new Date();
const localToday = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
document.querySelector('#trade-date').value = localToday;
document.querySelector('#trade-date').max = localToday;

const escapeHtml = (value = '') => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

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
  reportPanel.classList.remove('hidden');
  reportPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

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
  reportPanel.classList.add('hidden');
  document.querySelector('#hero').scrollIntoView({ behavior: 'smooth' });
  document.querySelector('#ticker').focus();
});
