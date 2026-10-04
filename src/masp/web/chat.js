import { setLocale, installLocaleObserver, translateUiText } from './i18n.js?v=43';
import { icon, installIcons } from './icons.js';
import { renderMarkdownElement, visibleAssistantContent } from './markdown.js?v=43';
import './native-form.js';
import { renderAttachmentCards } from './attachment-preview.js?v=44';

const $ = (selector) => document.querySelector(selector);
installIcons();
installLocaleObserver();
const thread = $('#thread');
const paneWidth = { sidebar: 312, inspector: 360 };
const maxAttachmentBytes = 250_000;
let pendingAttachments = [];
let projects = [];
let profiles = [];
let conversations = [];
let conversationId = null;
let draftProjectId = null;
let team = null;
let teamDirty = false;
let editingProfileId = null;
let busy = false;
let selectedRunId = null;
let runStream = null;
let feedbackRunId = null;
let conversationTrail = [];
let trailIndex = -1;
let toastTimer = null;
let workspaceFolder = '';
let selectedWorkspaceFile = '';
let browserHistory = [];
let browserHistoryIndex = -1;
let lastDeletedConversation = null;
let lastDeletedProject = null;
let selectMenuNumber = 0;
let activePluginTab = 'all';
let dshSettings = null;
let dshPluginInventory = null;
let contextMaxTokens = Number(localStorage.getItem('masp.contextMaxTokens')) || 64000;
let contextAutoCompact = localStorage.getItem('masp.contextAutoCompact') !== 'false';
let activeChatAbortController = null;
let userAbortedCurrentTurn = false;
installSelectMenus();

const settingsPanels = ['team', 'models', 'skills', 'mcp', 'plugins', 'runs'];
document.querySelectorAll('[data-rail="runs"]').forEach(button => button.remove());
document.querySelectorAll('[data-rail="skills"], [data-rail="mcp"]').forEach(button => button.hidden = true);
document.querySelector('[data-rail="plugins"]')?.setAttribute('title', '自定义');
const settingsContent = $('#left-tool-content');
settingsContent.append(...settingsPanels.map((name) => $('#' + name + '-panel')));
if (window.maspDesktop?.isDesktop) {
  document.body.classList.add('desktop-shell');
  window.maspDesktop.onMenuAction((action) => {
    document.querySelector('[data-action="' + action + '"]')?.click();
  });
}

try {
  const saved = JSON.parse(localStorage.getItem('masp.layout') || '{}');
  if (Number.isFinite(saved.sidebar)) paneWidth.sidebar = saved.sidebar;
  if (Number.isFinite(saved.inspector)) paneWidth.inspector = saved.inspector;
} catch {}

function applyPaneWidths() {
  const overlay = window.innerWidth <= 1100;
  const centerMin = overlay ? 0 : 380;
  const rail = window.innerWidth <= 1250 ? 56 : 64;
  const sidebarMax = Math.max(264, Math.min(420, window.innerWidth - rail - 300 - 16 - centerMin));
  paneWidth.sidebar = Math.min(sidebarMax, Math.max(264, paneWidth.sidebar));
  const inspectorMax = overlay
    ? Math.max(300, window.innerWidth - rail - 48)
    : Math.max(300, window.innerWidth - rail - paneWidth.sidebar - 16 - centerMin);
  paneWidth.inspector = Math.min(700, inspectorMax, Math.max(300, paneWidth.inspector));
  document.documentElement.style.setProperty('--sidebar-size', paneWidth.sidebar + 'px');
  document.documentElement.style.setProperty('--inspector-size', paneWidth.inspector + 'px');
  $('#resize-sidebar').setAttribute('aria-valuenow', String(paneWidth.sidebar));
  $('#resize-inspector').setAttribute('aria-valuenow', String(paneWidth.inspector));
}

function savePaneWidths() {
  try { localStorage.setItem('masp.layout', JSON.stringify(paneWidth)); } catch {}
}

function setPaneWidth(which, requested) {
  if (which === 'sidebar') paneWidth.sidebar = requested;
  else paneWidth.inspector = requested;
  applyPaneWidths();
}

for (const handle of document.querySelectorAll('[data-resize]')) {
  let drag = null;
  handle.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    drag = { x: event.clientX, width: paneWidth[handle.dataset.resize] };
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add('resizing-pane');
  });
  handle.addEventListener('pointermove', (event) => {
    if (!drag) return;
    const delta = event.clientX - drag.x;
    setPaneWidth(handle.dataset.resize, drag.width + (handle.dataset.resize === 'sidebar' ? delta : -delta));
  });
  const endDrag = () => {
    if (!drag) return;
    drag = null;
    document.body.classList.remove('resizing-pane');
    savePaneWidths();
  };
  handle.addEventListener('pointerup', endDrag);
  handle.addEventListener('pointercancel', endDrag);
  handle.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const direction = event.key === 'ArrowRight' ? 1 : -1;
    const delta = direction * (handle.dataset.resize === 'sidebar' ? 1 : -1) * 16;
    setPaneWidth(handle.dataset.resize, paneWidth[handle.dataset.resize] + delta);
    savePaneWidths();
  });
}
applyPaneWidths();
if (window.innerWidth < 1100) document.body.classList.add('inspector-closed');
if (window.innerWidth < 700) document.body.classList.add('sidebar-closed');
window.addEventListener('resize', applyPaneWidths);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

async function api(path, method = 'GET', body) {
  const response = await fetch('/api' + path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = '请求失败 (HTTP ' + response.status + ')';
    try {
      const rawText = await response.text();
      if (rawText) {
        try {
          const parsed = JSON.parse(rawText);
          detail = parsed.detail || parsed.message || detail;
        } catch {
          detail = rawText.trim().slice(0, 240) || detail;
        }
      }
    } catch {}
    const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new Error('服务返回了非 JSON 响应: ' + text.trim().slice(0, 160));
  }
}

function setFeedback(selector, text, error = false) {
  const element = typeof selector === 'string' ? $(selector) : selector;
  if (!element) return;
  element.textContent = text;
  element.classList.toggle('error', error);
}

function toast(text, error = false) {
  const element = $('#toast');
  element.textContent = text;
  element.classList.toggle('error', error);
  element.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove('visible'), 2600);
}

function updateNavigationButtons() {
  if ($('#back')) $('#back').disabled = trailIndex <= 0;
  if ($('#forward')) $('#forward').disabled = trailIndex < 0 || trailIndex >= conversationTrail.length - 1;
}

function formatDiffHtml(diffText, filePath = '') {
  if (!diffText) {
    return '<div class="ide-code-row kind-ctx"><span class="ide-ln">1</span><span class="ide-code-cell muted">无差异内容</span></div>';
  }
  const info = splitFilePathInfo(filePath || '');
  const dr = buildFallbackDiffReviewFromUnified(diffText);
  if (dr.diff_lines && dr.diff_lines.length) {
    return dr.diff_lines.map((ln) => renderIdeCodeRowHtml(filePath || '', ln, info.ext)).join('');
  }
  return String(diffText).replace(/\n$/, '').split('\n').map((line, idx) =>
    renderIdeCodeRowHtml(filePath || '', { kind: 'ctx', new_lineno: idx + 1, text: line }, info.ext)
  ).join('');
}

function toolCategoryIcon(category) {
  if (category === 'browser') {
    return '<svg class="app-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>';
  }
  if (category === 'edit') {
    return '<svg class="app-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
  }
  if (category === 'command') {
    return '<svg class="app-icon" viewBox="0 0 24 24" aria-hidden="true"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>';
  }
  return icon('file');
}

function summarizeToolEvents(events) {
  if (!events.length) return '已执行工具';
  const running = events.some((e) => e.status === 'running');
  const phrases = [];
  if (events.some((e) => e.category === 'browser')) phrases.push('使用 浏览器');
  const editEvents = events.filter((e) => e.category === 'edit');
  if (editEvents.length > 1) phrases.push('编辑了多个文件');
  else if (editEvents.length === 1) phrases.push('编辑了文件');
  if (events.some((e) => e.category === 'read') && !phrases.length) phrases.push('浏览了文件');
  if (events.some((e) => e.category === 'command')) phrases.push('运行了命令');
  if (!phrases.length) phrases.push('调用了工具');
  return (running ? '正在' : '已') + phrases.join(' ') + ' · ' + events.length + ' 步';
}

// Reuse live DOM nodes so a stream update cannot interrupt clicks or scrollbar drags.
function updateActivityMarkup(root, html) {
  const template = document.createElement('template');
  template.innerHTML = html;
  function sync(parent, incoming) {
    const desired = Array.from(incoming.childNodes);
    desired.forEach((next, index) => {
      let current = parent.childNodes[index];
      if (!current || current.nodeType !== next.nodeType || current.nodeName !== next.nodeName) {
        const copy = next.cloneNode(true);
        if (current) parent.replaceChild(copy, current);
        else parent.appendChild(copy);
        return;
      }
      if (current.nodeType === Node.TEXT_NODE) {
        if (current.textContent !== next.textContent) current.textContent = next.textContent;
        return;
      }
      if (current.nodeType !== Node.ELEMENT_NODE) return;
      for (const attr of Array.from(current.attributes)) {
        if (!['open', 'hidden'].includes(attr.name) && !next.hasAttribute(attr.name)) current.removeAttribute(attr.name);
      }
      for (const attr of Array.from(next.attributes)) {
        if (!['open', 'hidden'].includes(attr.name) && current.getAttribute(attr.name) !== attr.value) current.setAttribute(attr.name, attr.value);
      }
      if (!current.classList?.contains('plugin-tool-view')) sync(current, next);
    });
    while (parent.childNodes.length > desired.length) parent.lastChild.remove();
  }
  sync(root, template.content);
}

// Preserve interaction state across streaming updates, including nested output scroll.
const activityViewSelector = '.tool-step-detail, .thinking-activity-body, .subagent-step-detail, details[data-open-key], .subagent-thinking-content, .subagent-live-preview pre';
function captureActivityView(root) {
  const state = new Map();
  root.querySelectorAll(activityViewSelector).forEach((el) => state.set(el, {
    hidden: el.hidden, open: el.open, top: el.scrollTop, left: el.scrollLeft,
  }));
  return state;
}
function restoreActivityView(root, state) {
  root.querySelectorAll(activityViewSelector).forEach((el) => {
    const saved = state.get(el);
    if (!saved) return;
    el.hidden = saved.hidden;
    if (el.tagName === 'DETAILS') el.open = saved.open;
    el.scrollTop = saved.top;
    el.scrollLeft = saved.left;
  });
}

function createOrUpdateToolGroup(groupEl, events) {
  let details = groupEl;
  if (!details) {
    details = document.createElement('details');
    details.className = 'tool-activity-group';
    details.open = false;
    details.addEventListener('toggle', () => {
      details.dataset.userToggled = 'true';
    });
  }
  const preserveOpen = details.open;
  const viewState = captureActivityView(details);
  const summaryText = summarizeToolEvents(events);
  const uniqueCategories = [...new Set(events.map((e) => e.category || 'read'))].slice(0, 3);
  const groupIconsHtml = uniqueCategories.map((c) => toolCategoryIcon(c)).join('');
  const stepsHtml = events.map((ev, idx) => {
    const cat = ev.category || 'read';
    const label = ev.label || ev.short_name || ev.name || '工具';
    const hasStats = cat === 'edit' && (Number(ev.added || 0) > 0 || Number(ev.removed || 0) > 0);
    const statsHtml = hasStats
      ? '<span class="tool-diff-badge"><span class="diff-add">+' + Number(ev.added || 0) + '</span><span class="diff-del">-' + Number(ev.removed || 0) + '</span></span>'
      : '';
    const stateBadge = ev.status === 'running'
      ? '<span class="muted">进行中…</span>'
      : (ev.status === 'blocked' ? '<span class="muted">等待批准</span>' : ev.status === 'failed' ? '<span class="tool-failure-badge">调用失败</span>' : '');
    const hasDiff = Boolean(ev.diff);
    const detailBody = hasDiff
      ? formatDiffHtml(ev.diff, ev.path || '')
      : escapeHtml(ev.output || '');
    const detailHtml = detailBody
      ? (hasDiff
        ? '<div class="tool-step-detail ide-code-table" hidden>' + detailBody + '</div>'
        : '<div class="tool-step-detail plain-output" hidden>' + detailBody + '</div>')
      : '';
    return '<div class="tool-step-item" data-step-index="' + idx + '">' +
      '<div class="tool-step-head" data-toggle-step="' + idx + '">' +
        '<span class="tool-step-icon">' + toolCategoryIcon(cat) + '</span>' +
        '<span class="tool-step-label">' + escapeHtml(label) + '</span>' +
        statsHtml +
        stateBadge +
        (detailBody ? '<svg class="tool-group-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m6 4 4 4-4 4"/></svg>' : '') +
      '</div>' +
      detailHtml +
      (ev.native_result ? '<div class="plugin-tool-view plugin-slot-host"></div>' : '') +
    '</div>';
  }).join('');

  updateActivityMarkup(details,
    '<summary class="tool-activity-summary">' +
      '<span class="tool-group-icons">' + groupIconsHtml + '</span>' +
      '<span class="tool-group-title">' + escapeHtml(summaryText) + '</span>' +
      '<svg class="tool-group-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m6 4 4 4-4 4"/></svg>' +
    '</summary>' +
    '<div class="tool-activity-list">' + stepsHtml + '</div>');
  details.open = preserveOpen;
  restoreActivityView(details, viewState);
  events.forEach((event,index)=>{
    if (!event.native_result || event.status === 'running') return;
    const item=details.querySelector('[data-step-index="'+index+'"]');
    if(!item)return;
    let target=item.querySelector('.plugin-tool-view');
    if(!target){target=document.createElement('div');target.className='plugin-tool-view plugin-slot-host';item.append(target);}
    const result=event.native_result;
    const block={kind:'tool',phase:'result',name:event.name,callId:event.call_id||String(index),call:{name:event.name,argsRaw:event.arguments||'{}'},content:result.content||[],isError:Boolean(result.isError),error:result.error,meta:result.meta,subCalls:[]};
    for(const entry of conversationPluginMounts.values())if(entry.dispose.renderToolView?.(target,{callId:block.callId,toolName:event.name,block,phase:'result',openFile:path=>void openWorkspaceFile(path)}))break;
  });
  return details;
}

function createOrUpdateThinkingGroup(groupEl, thinkingData) {
  if (!thinkingData) return null;
  let details = groupEl;
  const isRunning = thinkingData.status === 'running' || thinkingData.status === 'thinking';
  if (!details) {
    details = document.createElement('details');
    details.className = 'thinking-activity-group';
    details.open = false;
    details.addEventListener('toggle', () => {
      details.dataset.userToggled = 'true';
    });
  }
  const preserveOpen = details.open;
  const viewState = captureActivityView(details);
  const secs = thinkingData.seconds ?? Math.max(0.1, Number(((thinkingData.duration_ms || 100) / 1000).toFixed(1)));
  const titleText = thinkingData.kind === 'work' ? (isRunning ? '工作中' : '协作方案已生成') : (isRunning ? '思考中' : '已思考 ' + secs + 's');
  updateActivityMarkup(details,
    '<summary class="tool-activity-summary">' +
      '<span class="tool-group-icons">' + icon('sparkle') + '</span>' +
      '<span class="tool-group-title">' + escapeHtml(titleText) + '</span>' +
      '<svg class="tool-group-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m6 4 4 4-4 4"/></svg>' +
    '</summary>' +
    '<div class="thinking-activity-body">' + escapeHtml(thinkingData.content || '正在分析任务需求与协作方案…') + '</div>');
  details.open = preserveOpen;
  restoreActivityView(details, viewState);
  return details;
}

function createOrUpdatePlanApprovalCard(cardEl, teamData) {
  if (!teamData || !Array.isArray(teamData.agents) || !teamData.agents.length) return null;
  let container = cardEl;
  if (!container) {
    container = document.createElement('div');
    container.className = 'plan-approval-card';
  }
  const planVer = Number(teamData.plan_version || teamData.version || 1);
  container.dataset.teamVersion = String(teamData.version || 1);
  const wfState = String(teamData.workflow_state || (teamData.status === 'approved' ? 'approved' : 'planned'));
  const isApproved = teamData.status === 'approved' || wfState === 'approved' || wfState === 'running' || wfState === 'done';
  const riskLv = String(teamData.risk_level || 'medium');
  const riskLabel = riskLv === 'high' ? '高风险' : (riskLv === 'low' ? '低风险' : '中风险');
  const agentsRows = teamData.agents.map((ag, idx) => {
    const paths = Array.isArray(ag.owned_paths) && ag.owned_paths.length ? ag.owned_paths.join(', ') : '工作区';
    return '<div class="plan-agent-item">' +
      '<div class="plan-agent-head">' +
        '<span class="plan-agent-badge">' + (idx + 1) + '. ' + escapeHtml(ag.name || ag.id) + '</span>' +
        '<code class="plan-agent-paths">' + escapeHtml(paths) + '</code>' +
      '</div>' +
      '<div class="plan-agent-resp">' + escapeHtml(ag.responsibility || '负责模块实现与验证') + '</div>' +
    '</div>';
  }).join('');
  container.innerHTML =
    '<div class="plan-approval-header">' +
      '<div class="plan-approval-title-wrap">' +
        '<span class="plan-approval-icon">' + icon('team') + '</span>' +
        '<span class="plan-approval-title">协作方案 · v' + planVer + '</span>' +
        '<span class="plan-risk-tag risk-' + escapeHtml(riskLv) + '">' + escapeHtml(riskLabel) + '</span>' +
      '</div>' +
      '<span class="plan-status-pill ' + (isApproved ? 'is-approved' : 'is-pending') + '">' +
        (isApproved ? '已批准' : '待确认') +
      '</span>' +
    '</div>' +
    '<div class="plan-agents-grid">' + agentsRows + '</div>' +
    ((teamData.plan_documents || []).length ? '<div class="plan-document-links">' + teamData.plan_documents.map(path => '<button type="button" data-team-document="' + escapeHtml(path) + '">' + escapeHtml(path.split('/').pop()) + '</button>').join('') + '</div>' : '') +
    '<div class="plan-approval-actions">' +
      (isApproved
        ? '<button type="button" class="plan-btn secondary" data-inline-open-mindmap="true">查看团队</button>'
        : '<button type="button" class="plan-btn primary" data-inline-approve-plan="true">确认执行</button>' +
          '<button type="button" class="plan-btn secondary" data-inline-open-mindmap="true">调整团队</button>') +
    '</div>';
  return container;
}

function createOrUpdateSubagentGroup(groupEl, subagentEvents) {
  if (!Array.isArray(subagentEvents) || !subagentEvents.length) return null;
  let details = groupEl;
  if (!details) {
    details = document.createElement('details');
    details.className = 'subagent-progress-group';
    details.open = true;
    details.addEventListener('toggle', () => {
      details.dataset.userToggled = 'true';
    });
  }
  const openKeys = new Set();
  details.querySelectorAll('details[data-open-key]').forEach((d) => {
    if (d.open) openKeys.add(d.dataset.openKey);
  });
  const runningAgent = subagentEvents.find((e) => e.status === 'running');
  const defaultOpen = Boolean(runningAgent) || details.open;
  const preserveOpen = groupEl ? details.open : defaultOpen;
  const viewState = captureActivityView(details);
  const completedCount = subagentEvents.filter((e) => e.status === 'completed' || e.status === 'complete').length;
  const summaryTitle = runningAgent
    ? ('子 Agent 协作中 · ' + completedCount + '/' + subagentEvents.length)
    : ('子 Agent 协作完成 · ' + completedCount + '/' + subagentEvents.length);
  const rowsHtml = subagentEvents.map((ev, idx) => {
    const st = ['running', 'paused', 'cancelled', 'failed'].includes(ev.status) ? ev.status : 'completed';
    const pct = typeof ev.progress_pct === 'number'
      ? Math.max(5, Math.min(100, ev.progress_pct))
      : (st === 'completed' ? 100 : (st === 'running' ? 45 : 0));
    const statusLabel = st === 'running'
      ? (pct + '%')
      : ({ failed: '未完成', paused: '已暂停', cancelled: '已取消' }[st] || '已完成');
    const ownedPathsText = Array.isArray(ev.owned_paths) && ev.owned_paths.length
      ? ev.owned_paths.join(', ')
      : '';
    const rawSteps = Array.isArray(ev.steps) && ev.steps.length
      ? ev.steps
      : [
          { label: '加载任务规范与上下文', status: 'done' },
          { label: '推导模块结构与接口契约', status: st === 'completed' ? 'done' : 'running' },
          { label: '执行任务与代码产出', status: st === 'completed' ? 'done' : 'running' },
          { label: '写入工作区文件并同步结果', status: st === 'completed' ? 'done' : 'pending' },
        ];
    const stepRowsHtml = rawSteps.map((stepItem, sIdx) => {
      const stepText = typeof stepItem === 'string' ? stepItem : (stepItem.text || stepItem.label || '');
      const stepSt = typeof stepItem === 'object' && stepItem.status
        ? stepItem.status
        : (st === 'running' && sIdx === rawSteps.length - 1 ? 'running' : 'done');
      const rowCls = stepSt === 'running' ? 'is-active' : (stepSt === 'done' ? 'is-done' : 'is-pending');
      const bullet = stepSt === 'done' ? '✓' : (stepSt === 'running' ? '●' : '○');
      return '<div class="subagent-step-log-row ' + rowCls + '">' +
        '<span class="subagent-step-bullet">' + bullet + '</span>' +
        '<span>' + escapeHtml(stepText) + '</span>' +
      '</div>';
    }).join('');
    const thinkKey = 'think-' + (ev.agent_id || idx);
    const thinkOpenAttr = openKeys.has(thinkKey) ? ' open' : '';
    const thinkingHtml = ev.thinking
      ? '<details class="subagent-thinking-box" data-open-key="' + escapeHtml(thinkKey) + '"' + thinkOpenAttr + '>' +
          '<summary class="subagent-thinking-title">' + icon('sparkle') + ' <span>' + (st === 'running' ? '思考中' : '思考过程') + '</span></summary>' +
          '<div class="subagent-thinking-content">' + escapeHtml(ev.thinking) + '</div>' +
        '</details>'
      : '';
    const prevKey = 'prev-' + (ev.agent_id || idx);
    const prevOpenAttr = openKeys.has(prevKey) ? ' open' : '';
    const previewHtml = ev.code_preview
      ? '<details class="subagent-live-preview" data-open-key="' + escapeHtml(prevKey) + '"' + prevOpenAttr + '>' +
          '<summary class="subagent-live-preview-head">代码预览</summary>' +
          '<pre><code>' + escapeHtml(ev.code_preview) + '</code></pre>' +
        '</details>'
      : '';
    const progressBarHtml = st === 'running'
      ? '<div class="subagent-progress-bar"><div class="subagent-progress-fill ' + st + '" style="width:' + pct + '%"></div></div>'
      : '';
    return '<div class="subagent-step-item" data-subagent-idx="' + idx + '">' +
      '<div class="subagent-step-head" data-toggle-subagent="' + idx + '">' +
        '<span class="subagent-step-left">' +
          '<span class="subagent-status-dot ' + st + '"></span>' +
          '<strong>' + escapeHtml(ev.agent_name || ev.agent_id || '子 Agent') + '</strong>' +
          (ownedPathsText ? '<code class="subagent-owned-tag">' + escapeHtml(ownedPathsText) + '</code>' : '') +
        '</span>' +
        '<span class="subagent-status-pill ' + st + '">' + statusLabel + '</span>' +
      '</div>' +
      progressBarHtml +
      '<div class="subagent-step-detail">' +
        (ev.effective_model ? '<div class="subagent-runtime-model muted">实际运行模型：' + escapeHtml(ev.effective_model) + '</div>' : '') +
        '<div class="subagent-step-log">' + stepRowsHtml + '</div>' +
        (st === 'failed' ? '<div class="subagent-error-detail">' + escapeHtml(ev.error || ev.thinking || ev.detail || '任务未完成，请查看工具结果') + '</div>' : '') +
        thinkingHtml +
        previewHtml +
      '</div>' +
    '</div>';
  }).join('');
  updateActivityMarkup(details,
    '<summary class="tool-activity-summary">' +
      '<span class="tool-group-icons">' + icon('team') + '</span>' +
      '<span class="tool-group-title">' + escapeHtml(summaryTitle) + '</span>' +
      '<svg class="tool-group-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m6 4 4 4-4 4"/></svg>' +
    '</summary>' +
    '<div class="subagent-activity-list">' + rowsHtml + '</div>');
  details.open = preserveOpen;
  restoreActivityView(details, viewState);
  return details;
}

function collectTurnEditedFiles(turnDiff, toolEvents = []) {
  const map = new Map();
  if (Array.isArray(turnDiff?.files)) {
    for (const f of turnDiff.files) {
      const p = String(f.path || '').trim();
      if (!p) continue;
      map.set(p, {
        path: p,
        added: Number(f.added || 0),
        removed: Number(f.removed || 0),
      });
    }
  }
  if (!map.size && Array.isArray(toolEvents)) {
    for (const ev of toolEvents) {
      if (ev.category !== 'edit') continue;
      const rawTarget = ev.path || ev.target || String(ev.label || '').replace(/^(?:\[[^\]]+\]\s*)?(?:已编辑|正在编辑|编辑文件|写入文件)\s*/u, '').trim();
      if (!rawTarget || rawTarget === '文件') continue;
      const prev = map.get(rawTarget) || { path: rawTarget, added: 0, removed: 0 };
      prev.added += Number(ev.added || 0);
      prev.removed += Number(ev.removed || 0);
      map.set(rawTarget, prev);
    }
  }
  return [...map.values()];
}

function createTurnDiffElement(turnDiff, toolEvents = [], messageId = null) {
  if (!turnDiff) return null;
  const effectiveMsgId = messageId || turnDiff.message_id || null;
  const added = Number(turnDiff.added || 0);
  const removed = Number(turnDiff.removed || 0);
  const filesList = collectTurnEditedFiles(turnDiff, toolEvents);
  const filesChanged = Number(turnDiff.files_changed || filesList.length || 0);
  if (added === 0 && removed === 0 && filesChanged === 0 && !filesList.length) return null;

  const project = projects.find((item) => item.id === (draftProjectId || $('#project-select')?.value));
  const deliverableTitle = project?.name || 'Micro-Multi';
  const allPathsAttr = escapeHtml(JSON.stringify(filesList.map((f) => f.path)));

  const maxInitial = 3;
  const rowsHtml = filesList.map((f, idx) => {
    const info = splitFilePathInfo(f.path);
    const hiddenAttr = idx >= maxInitial ? ' data-extra-turn-file="true" hidden' : '';
    return '<button type="button" class="turn-edits-row" data-open-turn-file="' + escapeHtml(f.path) + '"' + hiddenAttr + '>' +
      '<span class="turn-edits-path">' +
        renderFileTypeBadge(f.path) +
        '<span class="name-part">' + escapeHtml(info.name) + '</span>' +
        (info.dir ? '<span class="dir-part">' + escapeHtml(info.dir) + '</span>' : '') +
      '</span>' +
      '<span class="tool-diff-badge"><span class="diff-add">+' + Number(f.added || 0) + '</span><span class="diff-del">-' + Number(f.removed || 0) + '</span></span>' +
    '</button>';
  }).join('');

  const extraCount = Math.max(0, filesList.length - maxInitial);
  const moreBtnHtml = extraCount > 0
    ? '<button type="button" class="turn-edits-more" data-expand-turn-files="true" data-extra-count="' + extraCount + '">' +
        '<span>再显示 ' + extraCount + ' 个文件</span><span aria-hidden="true">∨</span>' +
      '</button>'
    : '';

  const wrap = document.createElement('div');
  wrap.className = 'turn-summary-stack';
  wrap.dataset.turnPaths = allPathsAttr;
  if (effectiveMsgId) wrap.dataset.turnMsgId = effectiveMsgId;
  const msgAttr = effectiveMsgId ? (' data-turn-msg-id="' + escapeHtml(effectiveMsgId) + '"') : '';
  wrap.innerHTML =
    '<div class="turn-deliverable-card">' +
      '<div class="turn-deliverable-left">' +
        '<span class="turn-deliverable-icon">' + icon('file') + '</span>' +
        '<div class="turn-deliverable-info">' +
          '<strong>' + escapeHtml(deliverableTitle) + '</strong>' +
          '<small>工作区交付成果' + (effectiveMsgId ? ' · 历史快照' : '') + '</small>' +
        '</div>' +
      '</div>' +
      '<button type="button" class="turn-deliverable-open" data-open-changes="true"' + msgAttr + '>' +
        '<span>查看改动</span>' +
        '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>' +
      '</button>' +
    '</div>' +
    '<div class="turn-edits-card">' +
      '<div class="turn-edits-head">' +
        '<span class="turn-edits-title" data-open-changes="true"' + msgAttr + '>' +
          '<span>已编辑 ' + (filesChanged || filesList.length || 1) + ' 个文件</span>' +
          '<span class="tool-diff-badge"><span class="diff-add">+' + added + '</span><span class="diff-del">-' + removed + '</span></span>' +
        '</span>' +
        '<div class="turn-edits-actions">' +
          '<button type="button" class="turn-edits-btn" data-revert-turn-files="true">撤销 ↶</button>' +
          '<button type="button" class="turn-edits-btn" data-review-turn-files="true">审核</button>' +
        '</div>' +
      '</div>' +
      (rowsHtml ? '<div class="turn-edits-list">' + rowsHtml + moreBtnHtml + '</div>' : '') +
    '</div>';
  return wrap;
}

function renderExecutionPlanCard(plan) {
  if (!plan) return null;
  const wrap = document.createElement('div');
  wrap.className = 'execution-plan-card';
  wrap.id = 'plan-' + escapeHtml(plan.plan_id);

  const stepsHtml = (plan.steps || []).map((step) => {
    const isDone = step.status === 'done';
    const isRunning = step.status === 'running';
    const statusBadge = isDone
      ? '<span class="plan-step-badge is-done">✓ 已完成</span>'
      : (isRunning ? '<span class="plan-step-badge is-running">● 执行中</span>' : '<span class="plan-step-badge is-pending">等待确认</span>');
    const agentBadge = step.assigned_agent && step.assigned_agent !== 'main'
      ? '<span class="plan-agent-tag">' + escapeHtml(step.assigned_agent) + '</span>'
      : '<span class="plan-agent-tag is-main">主 Agent</span>';
    const filesHtml = (step.target_files || []).map((f) => '<code class="plan-step-file">' + escapeHtml(f) + '</code>').join(' ');

    return '<div class="execution-plan-step ' + (isDone ? 'is-done' : (isRunning ? 'is-running' : '')) + '" id="plan-step-' + step.step_number + '">' +
      '<div class="plan-step-head">' +
        '<span class="plan-step-num">' + step.step_number + '</span>' +
        '<span class="plan-step-title">' + escapeHtml(step.title) + '</span>' +
        agentBadge +
        statusBadge +
      '</div>' +
      (step.description ? '<div class="plan-step-desc">' + escapeHtml(step.description) + '</div>' : '') +
      (filesHtml ? '<div class="plan-step-files">' + filesHtml + '</div>' : '') +
    '</div>';
  }).join('');

  wrap.innerHTML =
    '<div class="execution-plan-header">' +
      '<div class="execution-plan-title-bar">' +
        '<span class="execution-plan-icon">' + icon('sparkle') + '</span>' +
        '<strong class="execution-plan-title">' + escapeHtml(plan.title || '需求执行方案规划') + '</strong>' +
        '<span class="execution-plan-status-tag">待审核</span>' +
      '</div>' +
      '<div class="execution-plan-goal">' + escapeHtml(plan.goal || '') + '</div>' +
    '</div>' +
    '<div class="execution-plan-steps">' + stepsHtml + '</div>' +
    '<div class="execution-plan-actions">' +
      '<button type="button" class="btn-confirm-plan" data-confirm-plan-id="' + escapeHtml(plan.plan_id) + '">' +
        '确认执行计划' +
      '</button>' +
    '</div>';

  wrap.querySelector('.btn-confirm-plan')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = '计划已确认，正在执行…';
    const tagEl = wrap.querySelector('.execution-plan-status-tag');
    if (tagEl) {
      tagEl.textContent = '执行中';
      tagEl.classList.add('is-running');
    }
    submitChatPlanExecution(plan.plan_id);
  });

  return wrap;
}

function submitChatPlanExecution(planId) {
  const promptInput = $('#prompt');
  if (promptInput) promptInput.value = '按计划开始执行';
  const composer = $('#composer');
  if (composer) {
    composer.dataset.executePlanNow = 'true';
    composer.dataset.planId = planId;
    composer.requestSubmit();
  }
}

function appendSwitchNotice(fromLabel, toLabel) {
  const fromClean = String(fromLabel || '').trim();
  const toClean = String(toLabel || '').trim();
  if (!fromClean || !toClean || fromClean === toClean) return;
  if (!thread.querySelector('.message')) return;
  const notice = document.createElement('div');
  notice.className = 'chat-switch-notice';
  notice.textContent = '由 ' + fromClean + ' 切换到 ' + toClean;
  thread.appendChild(notice);
  thread.scrollTop = thread.scrollHeight;
}

function createAbortBannerElement(message = '用户手动中止') {
  const el = document.createElement('div');
  el.className = 'abort-banner';
  el.textContent = '■ ' + message;
  return el;
}

function renderMessage(role, content, extra = '', toolEvents = [], options = {}) {
  const item = document.createElement('article');
  item.className = 'message ' + role;
  if (options.messageId) item.dataset.messageId = options.messageId;
  item.innerHTML = role === 'user'
    ? '<div class="bubble"></div>'
    : '<span class="role-mark" aria-hidden="true">' + icon('sparkle') + '</span><div class="assistant-turn assistant-turn-container"></div>';
  if (role === 'user') {
    const bubble = item.querySelector('.bubble');
    bubble.className += (extra ? ' ' + extra : '');
    bubble.dataset.rawContent = String(content ?? '');
    renderMarkdownElement(bubble, content);
    renderAttachmentCards(bubble, options.attachments || []);
    thread.append(item);
    thread.scrollTop = thread.scrollHeight;
    updateChatTurnRail();
    return bubble;
  }

  const turn = item.querySelector('.assistant-turn');
  for (const segment of options.segments || []) {
    if (segment.type === 'team_plan') {
      const card = createOrUpdatePlanApprovalCard(null, segment.team);
      if (card) {
        card.dataset.teamVersion = String(segment.team.version);
        if (team && segment.team.version !== team.version) card.querySelector('[data-inline-approve-plan]')?.setAttribute('disabled', '');
        turn.append(card);
      }
    }
  }
  if (options.thinking && (options.thinking.content || options.thinking.duration_ms)) {
    const thinkEl = createOrUpdateThinkingGroup(null, options.thinking);
    if (thinkEl) turn.append(thinkEl);
  }
  if (Array.isArray(options.subagentEvents) && options.subagentEvents.length) {
    const subEl = createOrUpdateSubagentGroup(null, options.subagentEvents);
    if (subEl) turn.append(subEl);
  }
  const segments = Array.isArray(options.segments) && options.segments.length ? options.segments : null;
  const collectedTools = Array.isArray(toolEvents) ? [...toolEvents] : [];
  let lastBubble = null;
  if (segments && !segments.some(seg => seg.type === 'tools' && seg.events?.length) && collectedTools.length) {
    turn.append(createOrUpdateToolGroup(null, collectedTools));
  }
  if (segments) {
    for (const seg of segments) {
      if (seg.type === 'tools' && Array.isArray(seg.events) && seg.events.length) {
        collectedTools.push(...seg.events);
        turn.append(createOrUpdateToolGroup(null, seg.events));
      } else if (seg.type === 'text' && String(seg.content || '').trim()) {
        const b = document.createElement('div');
        b.className = 'bubble assistant-segment-text' + (extra ? ' ' + extra : '');
        b.dataset.rawContent = String(seg.content);
        renderMarkdownElement(b, visibleAssistantContent(seg.content));
        turn.append(b);
        lastBubble = b;
      }
    }
  }
  if (!lastBubble) {
    if (Array.isArray(toolEvents) && toolEvents.length && !segments) {
      turn.append(createOrUpdateToolGroup(null, toolEvents));
    }
    const b = document.createElement('div');
    b.className = 'bubble assistant-segment-text' + (extra ? ' ' + extra : '');
    b.dataset.rawContent = String(content ?? '');
    renderMarkdownElement(b, visibleAssistantContent(content));
    turn.append(b);
    lastBubble = b;
  }
  if (options.executionPlan) {
    turn.append(renderExecutionPlanCard(options.executionPlan));
  }
  if (options.executionStatus === 'interrupted') {
    const notice = document.createElement('div');
    notice.className = 'turn-diff-summary';
    notice.textContent = '上一轮连接已中断，已保留收到的内容。可发送消息继续任务。';
    turn.appendChild(notice);
  }
  if (options.aborted) {
    turn.append(createAbortBannerElement('用户手动中止'));
  }
  const diffBar = createTurnDiffElement(options.turnDiff, collectedTools, options.messageId);
  if (diffBar) turn.append(diffBar);

  thread.append(item);
  thread.scrollTop = thread.scrollHeight;
  updateChatTurnRail();
  return lastBubble;
}

function renderAgentSelector() {
  const wrap = $('#agent-select-wrap');
  const selector = $('#agent-select');
  const hasProject = Boolean(draftProjectId);
  if (wrap) wrap.hidden = !hasProject;
  if (!hasProject) {
    selector.innerHTML = '<option value="main_only">仅主agent</option>';
    selector.value = 'main_only';
    refreshSelectMenu(selector);
    syncTrackedSelectorLabels();
    return;
  }
  const selected = selector.value;
  selector.innerHTML =
    '<option value="">多agent协作</option>' +
    '<option value="main_only">仅主agent</option>';
  if (selected === 'main_only') {
    selector.value = 'main_only';
  } else {
    selector.value = '';
  }
  refreshSelectMenu(selector);
  syncTrackedSelectorLabels();
}

function welcome() {
  const project = projects.find((item) => item.id === draftProjectId);
  const modeHint = project
    ? '当前已绑定项目 <strong>' + escapeHtml(project.name) + '</strong>，主 Agent 会先分析并提交本轮团队方案，审核后才启动子 Agent；普通问答直接回答。'
    : '当前为独立新聊天，在下方选项卡选择项目文件夹即可启用 Git 分支与多 Agent 协作。';
  thread.innerHTML = '<div class="welcome"><div class="logo" aria-hidden="true"><img src="/static/micro-multi.svg" alt=""></div><h1>我们从哪里开始？</h1><p>' + modeHint + '</p><div class="suggestions"><button type="button">帮我分析当前工作区结构</button><button type="button">列出当前已加载的所有插件与 MCP 工具</button><button type="button">为我的需求规划实现方案</button></div></div>';
  updateHeader();
  updateChatTurnRail();
}

function isSpuriousConvItem(item) {
  const label = String(item?.name || item?.title || '').trim();
  const repo = String(item?.repository || '').replace(/\\/g, '/');
  return /^conv-[0-9a-f]{6,}$/i.test(label) || repo.includes('temporary/conv-');
}

function updateHeader() {
  const current = conversations.find((item) => item.id === conversationId);
  const project = projects.find((item) => item.id === (draftProjectId || $('#project-select').value));
  const rawTitle = (current && current.message_count > 0) ? String(current.title || '新聊天') : '新聊天';
  $('#project-name').textContent = rawTitle.length > 16 ? (rawTitle.slice(0, 16) + '…') : rawTitle;
  $('#project-name').title = rawTitle;
  $('#header-project').textContent = project ? project.name : '临时工作区';
  $('#workspace-heading').textContent = project?.name || '工作区';
  $('#workspace-root-label').textContent = project?.repository || (conversationId ? 'temporary/' + conversationId : '临时工作区');
}

function renderConversationList() {
  const visible = conversations.filter((item) => !item.deleted_at && !isSpuriousConvItem(item)).sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)));
  $('#conversations').innerHTML = visible.map((item) => {
    const proj = item.project_id ? projects.find((p) => p.id === item.project_id) : null;
    const badge = proj ? '<span class="conv-project-tag">' + escapeHtml(proj.name) + '</span>' : '';
    return '<div class="conversation-row ' + (item.id === conversationId ? 'active' : '') + '">' +
      '<button class="conversation" data-id="' + escapeHtml(item.id) + '" title="' + escapeHtml(item.title) + '">' +
      '<span class="conv-title-text">' + escapeHtml(item.title) + '</span>' + badge + '</button>' +
      '<button class="conversation-delete" data-delete-conversation="' + escapeHtml(item.id) +
      '" title="删除对话" aria-label="删除对话：' + escapeHtml(item.title) + '">' + icon('trash') + '</button></div>';
  }).join('') || '<p class="empty">尚无历史对话。</p>';
  updateHeader();
  renderProjectList();
}

function renderProjectList() {
  projects = (projects || []).filter((p) => !isSpuriousConvItem(p));
  const activeProjId = draftProjectId || $('#project-select').value;
  $('#projects').innerHTML = projects.map((project) => {
    const children = conversations
      .filter((item) => item.project_id === project.id && !item.deleted_at && !isSpuriousConvItem(item))
      .sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)))
      .map((item) =>
        '<div class="project-conversation ' + (item.id === conversationId ? 'active' : '') + '">' +
        '<button class="conversation" data-id="' + escapeHtml(item.id) + '" title="' + escapeHtml(item.title) + '">' +
        (item.pinned ? '📌 ' : '') + escapeHtml(item.title) + '</button>' +
        '<details class="conversation-actions"><summary aria-label="对话操作">⋯</summary><div>' +
        '<button data-conversation-action="rename" data-conversation-id="' + escapeHtml(item.id) + '">编辑名称</button>' +
        '<button data-conversation-action="pin" data-conversation-id="' + escapeHtml(item.id) + '">' + (item.pinned ? '取消置顶' : '置顶') + '</button>' +
        '<button data-conversation-action="delete" data-conversation-id="' + escapeHtml(item.id) + '">删除</button></div></details></div>'
      ).join('');
    const collapsed = localStorage.getItem('masp.project.collapsed.' + project.id) === 'true';
    return '<div class="project-group"><div class="project-row"><button class="project-collapse" data-project-collapse="' + escapeHtml(project.id) + '" aria-expanded="' + !collapsed + '" aria-label="折叠或展开项目">' + '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>' + '</button><button class="project-link ' +
      (project.id === activeProjId && !conversationId ? 'active' : '') +
      '" data-project="' + escapeHtml(project.id) + '">' + icon('folder') + '<span>' + escapeHtml(project.name) + '</span></button>' +
      '<button class="project-delete" data-project-delete="' + escapeHtml(project.id) + '" title="移除项目" aria-label="移除项目：' + escapeHtml(project.name) + '">' + icon('trash') + '</button></div>' +
      (children && !collapsed ? '<div class="project-conversations">' + children + '</div>' : '') + '</div>';
  }).join('') || '<p class="empty">暂未添加项目文件夹。</p>';
}

function currentProjectId() {
  return draftProjectId || $('#project-select').value || '';
}

function activeWorkspaceId() {
  const pid = currentProjectId();
  if (pid) return pid;
  if (conversationId) return 'temp-' + conversationId;
  return '';
}

function updateContextLabels() {
  const project = projects.find((item) => item.id === draftProjectId);
  $('#context-project-name').textContent = project ? project.name : '选择项目';
  $('#branch-picker').hidden = false;
  renderAgentSelector();
  if (project) {
    loadProjectBranches(project.id).catch((error) => setFeedback('#context-branch-name', error.message, true));
  } else {
    const defaultBranch = dshSettings?.general?.defaultBranch || 'main';
    $('#context-branch-name').textContent = defaultBranch;
    $('#context-branch-options').innerHTML = '<button type="button" class="context-option" data-branch="' + escapeHtml(defaultBranch) + '"><span>' + icon('branch') + '<span><strong>' + escapeHtml(defaultBranch) + '</strong><small>默认分支</small></span></span><span class="branch-selected">' + icon('check') + '</span></button>';
  }
}

async function loadProjectBranches(projectId) {
  const data = await api('/projects/' + encodeURIComponent(projectId) + '/branches');
  if (projectId !== draftProjectId) return;
  $('#context-branch-name').textContent = data.current || 'main';
  $('#context-branch-options').innerHTML = data.branches.map((name) =>
    '<button type="button" class="context-option" data-branch="' + escapeHtml(name) + '"><span>' + icon('branch') + '<span><strong>' + escapeHtml(name) + '</strong>' + (name === data.current ? '<small>未提交：' + data.dirty_count + ' 个文件</small>' : '') + '</span></span>' + (name === data.current ? '<span class="branch-selected">' + icon('check') + '</span>' : '') + '</button>'
  ).join('') || '<p class="empty">没有可用分支。</p>';
}

function renderContextProjects(filter = '') {
  const query = filter.trim().toLocaleLowerCase();
  const found = projects.filter((project) => !isSpuriousConvItem(project) && project.name.toLocaleLowerCase().includes(query));
  $('#context-project-options').innerHTML = found.map((project) =>
    '<button type="button" class="context-option ' + (draftProjectId === project.id ? 'selected' : '') + '" data-context-project="' + escapeHtml(project.id) + '"><span>' + icon('folder') + '<span><strong>' + escapeHtml(project.name) + '</strong><small>' + escapeHtml(project.repository || '') + '</small></span></span>' + (draftProjectId === project.id ? '<span class="branch-selected">' + icon('check') + '</span>' : '') + '</button>'
  ).join('') || '<p class="empty">没有匹配的项目。</p>';
}

function splitFilePathInfo(rawPath) {
  const norm = String(rawPath || '').replace(/\\/g, '/');
  const idx = norm.lastIndexOf('/');
  const name = idx >= 0 ? norm.slice(idx + 1) : norm;
  const dir = idx >= 0 ? norm.slice(0, idx) : '';
  const lowerName = name.toLowerCase();
  if (lowerName.startsWith('.git')) {
    return { norm, name: name || norm, dir, ext: 'git', badgeText: 'GIT' };
  }
  const dotIdx = name.lastIndexOf('.');
  const ext = dotIdx >= 0 ? name.slice(dotIdx + 1).toLowerCase() : '';
  const badgeMap = {
    js: 'JS', cjs: 'JS', mjs: 'JS', jsx: 'JSX',
    ts: 'TS', tsx: 'TSX',
    py: 'PY',
    html: '<>', htm: '<>',
    css: 'CSS', scss: 'CSS',
    json: '{}', yaml: 'YML', yml: 'YML', toml: 'TML',
    md: 'MD', txt: 'TXT', sh: 'SH', ps1: 'PS',
    git: 'GIT',
  };
  const badgeText = badgeMap[ext] || (ext ? ext.slice(0, 3).toUpperCase() : 'FILE');
  return { norm, name: name || norm, dir, ext: ext || 'txt', badgeText };
}

function renderFileTypeBadge(rawPath) {
  const info = splitFilePathInfo(rawPath);
  return '<span class="ide-file-badge ext-' + escapeHtml(info.ext) + '">' + escapeHtml(info.badgeText) + '</span>';
}

function highlightCodeLine(rawLine, ext = '') {
  const text = String(rawLine ?? '');
  if (!text) return ' ';
  const trimmed = text.trimStart();
  if ((ext === 'py' || ext === 'sh' || ext === 'yaml' || ext === 'yml' || ext === 'toml') && trimmed.startsWith('#')) {
    return '<span class="tok-com">' + escapeHtml(text) + '</span>';
  }
  if (['js', 'cjs', 'mjs', 'ts', 'tsx', 'jsx', 'css', 'java', 'c', 'cpp', 'go', 'rs'].includes(ext) && (trimmed.startsWith('//') || trimmed.startsWith('/*') || trimmed.startsWith('*'))) {
    return '<span class="tok-com">' + escapeHtml(text) + '</span>';
  }
  const tokenRegex = /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:import|from|export|default|const|let|var|function|async|await|return|if|else|for|while|switch|case|break|continue|try|catch|finally|throw|new|class|extends|def|elif|except|with|as|pass|raise|yield|lambda|True|False|None|true|false|null|undefined|typeof|instanceof)\b|\b\d+(?:\.\d+)?\b|\b[A-Za-z_$][A-Za-z0-9_$]*(?=\s*\())/g;
  let out = '';
  let lastIdx = 0;
  let match;
  while ((match = tokenRegex.exec(text)) !== null) {
    if (match.index > lastIdx) {
      out += escapeHtml(text.slice(lastIdx, match.index));
    }
    const tok = match[0];
    if (tok.startsWith('"') || tok.startsWith("'") || tok.startsWith('`')) {
      out += '<span class="tok-str">' + escapeHtml(tok) + '</span>';
    } else if (/^\d/.test(tok)) {
      out += '<span class="tok-num">' + escapeHtml(tok) + '</span>';
    } else if (/^(import|from|export|default|const|let|var|function|async|await|return|if|else|for|while|switch|case|break|continue|try|catch|finally|throw|new|class|extends|def|elif|except|with|as|pass|raise|yield|lambda|True|False|None|true|false|null|undefined|typeof|instanceof)$/.test(tok)) {
      out += '<span class="tok-kw">' + escapeHtml(tok) + '</span>';
    } else {
      out += '<span class="tok-fn">' + escapeHtml(tok) + '</span>';
    }
    lastIdx = tokenRegex.lastIndex;
  }
  if (lastIdx < text.length) {
    out += escapeHtml(text.slice(lastIdx));
  }
  return out || ' ';
}

const ideGapStore = new Map();
let ideGapCounter = 0;

function renderIdeCodeRowHtml(filePath, ln, ext) {
  const kind = ln.kind || 'ctx';
  const lineNo = ln.new_lineno != null ? ln.new_lineno : (ln.old_lineno != null ? ln.old_lineno : '');
  const codeHtml = highlightCodeLine(ln.text ?? '', ext);
  return '<div class="ide-code-row kind-' + escapeHtml(kind) + '">' +
    '<span class="ide-ln">' + lineNo + '</span>' +
    '<span class="ide-code-cell">' + codeHtml + '</span>' +
  '</div>';
}

function buildFallbackDiffReviewFromUnified(rawDiff) {
  const lines = String(rawDiff || '').split('\n');
  const diffLines = [];
  let oldLn = 1;
  let newLn = 1;
  let added = 0;
  let removed = 0;
  for (const line of lines) {
    if (!line || line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++')) continue;
    if (line.startsWith('@@')) {
      const m = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (m) {
        oldLn = Number(m[1]);
        newLn = Number(m[2]);
      }
      continue;
    }
    if (line.startsWith('+')) {
      added += 1;
      diffLines.push({ kind: 'add', old_lineno: null, new_lineno: newLn++, text: line.slice(1), selectable: false });
    } else if (line.startsWith('-')) {
      removed += 1;
      diffLines.push({ kind: 'del', old_lineno: oldLn++, new_lineno: null, text: line.slice(1), selectable: false });
    } else {
      diffLines.push({ kind: 'ctx', old_lineno: oldLn++, new_lineno: newLn++, text: line.startsWith(' ') ? line.slice(1) : line, selectable: false });
    }
  }
  return { added, removed, has_changes: added > 0 || removed > 0, diff_lines: diffLines };
}

function renderGitDiffLinesHtml(filePath, diffReview) {
  const info = splitFilePathInfo(filePath);
  const lines = diffReview?.diff_lines || [];
  if (!lines.length) {
    return '<div class="ide-file-issues"><span class="muted">该文件与基准版本无行级差异。</span></div>';
  }
  const rowsHtml = lines.map((ln) => {
    if (ln.kind === 'gap') {
      const hidden = Array.isArray(ln.hidden_lines) ? ln.hidden_lines : [];
      const count = Number(ln.hidden_count || hidden.length || 0);
      if (!hidden.length) {
        return '<div class="ide-diff-expander"><span>' + escapeHtml(ln.text || ('... ' + count + ' unchanged lines ...')) + '</span></div>';
      }
      const gapKey = 'gap-' + (++ideGapCounter);
      ideGapStore.set(gapKey, {
        filePath,
        ext: info.ext,
        remainingLines: [...hidden],
      });
      return '<div class="ide-diff-expander" data-gap-key="' + escapeHtml(gapKey) + '">' +
        '<button type="button" class="ide-expand-step" data-expand-step="10">↕ +10</button>' +
        '<button type="button" class="ide-expand-all" data-expand-all="true">+' + count + ' more lines</button>' +
      '</div>';
    }
    return renderIdeCodeRowHtml(filePath, ln, info.ext);
  }).join('');
  return '<div class="ide-code-table git-diff-box">' + rowsHtml + '</div>';
}

function renderIdeFileCardHtml(filePath, diffReview, options = {}) {
  const info = splitFilePathInfo(filePath);
  const dr = diffReview || { added: 0, removed: 0, diff_lines: [] };
  const added = Number(dr.added ?? options.added ?? 0);
  const removed = Number(dr.removed ?? options.removed ?? 0);
  const statsHtml = (added || removed || options.forceDiffStats)
    ? '<span class="ide-file-stats"><span class="diff-add">+' + added + '</span><span class="diff-del">-' + removed + '</span></span>'
    : (options.totalLines ? '<span class="ide-file-dir">' + Number(options.totalLines) + ' 行</span>' : '');
  const statusPill = options.statusPillHtml || '';
  const issuesBanner = options.issuesHtml || '';
  const tableHtml = options.customBodyHtml || renderGitDiffLinesHtml(filePath, dr);
  const openAttr = options.defaultOpen ? ' open' : '';
  return '<details class="ide-file-card review-result-card" data-ide-file-card="' + escapeHtml(filePath) + '" data-review-card="' + escapeHtml(filePath) + '"' + openAttr + '>' +
    '<summary class="ide-file-header">' +
      '<div class="ide-file-header-left">' +
        renderFileTypeBadge(filePath) +
        '<span class="ide-file-name" title="' + escapeHtml(filePath) + '">' + escapeHtml(info.name) + '</span>' +
        (info.dir ? '<span class="ide-file-dir">' + escapeHtml(info.dir) + '</span>' : '') +
      '</div>' +
      '<div class="ide-file-header-right">' +
        statusPill +
        statsHtml +
        '<svg class="ide-card-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>' +
      '</div>' +
    '</summary>' +
    issuesBanner +
    tableHtml +
  '</details>';
}

function repositoryEntries(entries) {
  return entries.map((item) => {
    if (item.type === 'directory') {
      return '<details class="tree-folder" data-directory="' + escapeHtml(item.path) + '"><summary>' + icon('folder') + '<span>' + escapeHtml(item.name) + '</span></summary><div class="tree-children"></div></details>';
    }
    const info = splitFilePathInfo(item.path || item.name);
    return '<button type="button" class="workspace-entry ide-sidebar-item" data-entry-type="file" data-path="' + escapeHtml(item.path) + '">' +
      renderFileTypeBadge(item.path || item.name) +
      '<span class="ide-file-name">' + escapeHtml(item.name || info.name) + '</span>' +
      (info.dir ? '<span class="ide-file-dir">' + escapeHtml(info.dir) + '</span>' : '') +
    '</button>';
  }).join('') || '<p class="empty">此目录为空。</p>';
}

let cachedWorkspaceChanges = { status: '', diff: '', files: [] };

let lastReviewedFilesData = [];

const INTERNAL_WORKFLOW_DOC_NAMES = new Set([
  'task.md',
  'plan.md',
  'approved_plan.md',
  'glossary.md',
  'style-guide.md',
  'shared_dev_spec.md',
  'verification_report.md',
  'delivery_report.md',
]);

function isInternalWorkflowDoc(filePath) {
  const norm = String(filePath || '').replace(/\\/g, '/').trim().toLowerCase();
  const base = norm.includes('/') ? norm.slice(norm.lastIndexOf('/') + 1) : norm;
  return norm.startsWith('.masp/') || INTERNAL_WORKFLOW_DOC_NAMES.has(base);
}

async function loadWorkspaceFiles(folder = workspaceFolder) {
  const wsId = activeWorkspaceId();
  const projectId = currentProjectId();
  workspaceFolder = folder;
  selectedWorkspaceFile = '';
  if ($('#workspace-file-actions')) $('#workspace-file-actions').hidden = true;
  if ($('#workspace-file-content')) {
    $('#workspace-file-content').hidden = true;
    $('#workspace-file-content').innerHTML = '';
  }
  updateHeader();
  if (!wsId) {
    $('#workspace-root-label').textContent = '临时工作区';
    $('#workspace-file-list').innerHTML = '<p class="empty">选择项目或发送消息后即可浏览工作区文件。</p>';
    $('#repo-root').textContent = '未选择项目';
    $('#repo-tree').innerHTML = '<p class="empty">选择项目后显示文件树。</p>';
    return;
  }
  const project = projects.find((item) => item.id === projectId);
  $('#workspace-root-label').textContent = project?.repository || ('temporary/' + conversationId);
  $('#workspace-breadcrumbs').innerHTML = '<button data-folder="">根目录</button>' +
    (folder ? ' <span>›</span> ' + folder.split('/').map((part, index, all) =>
      '<button data-folder="' + escapeHtml(all.slice(0, index + 1).join('/')) + '">' + escapeHtml(part) + '</button>'
    ).join(' <span>›</span> ') : '');
  try {
    const entries = await api('/projects/' + encodeURIComponent(wsId) +
      '/workspace/files?path=' + encodeURIComponent(folder));
    const treeHtml = repositoryEntries(entries);
    $('#workspace-file-list').innerHTML = treeHtml;
    $('#repo-root').textContent = project?.repository || ('temporary/' + conversationId);
    if (!folder) $('#repo-tree').innerHTML = treeHtml;
  } catch (error) { $('#workspace-file-list').textContent = error.message; }
}

async function openWorkspaceFile(path, switchTab = true) {
  const wsId = activeWorkspaceId();
  if (!wsId) return toast('请先选择项目或开始对话。', true);
  try {
    const file = await api('/projects/' + encodeURIComponent(wsId) + '/workspace/file?path=' +
      encodeURIComponent(path));
    selectedWorkspaceFile = file.path;
    const info = splitFilePathInfo(file.path);
    if (/\.(md|markdown)$/i.test(file.path)) {
      const preview = $('#workspace-file-content');
      preview.replaceChildren();
      const body = document.createElement('div');
      body.className = 'markdown-body workspace-markdown-preview';
      renderMarkdownElement(body, file.content ?? '');
      preview.append(body);
      preview.hidden = false;
      if (switchTab) { document.body.classList.remove('inspector-closed'); showWorkspacePanel('files', false); }
      return;
    }
    const rawLines = String(file.content ?? '').split('\n');
    const rowsHtml = rawLines.map((lineText, idx) =>
      renderIdeCodeRowHtml(file.path, { kind: 'ctx', old_lineno: idx + 1, new_lineno: idx + 1, text: lineText }, info.ext)
    ).join('');
    $('#workspace-file-content').innerHTML = renderIdeFileCardHtml(file.path, null, {
      totalLines: rawLines.length,
      customBodyHtml: '<div class="ide-code-table">' + rowsHtml + '</div>',
      defaultOpen: true,
    });
    $('#workspace-file-content').hidden = false;
    if ($('#workspace-file-actions')) $('#workspace-file-actions').hidden = false;
    updateHeader();
    document.querySelectorAll('#workspace-file-list [data-path]').forEach((btn) =>
      btn.classList.toggle('active', btn.dataset.path === file.path));
    if (switchTab) {
      document.body.classList.remove('inspector-closed');
      showWorkspacePanel('files', false);
    }
  } catch (error) { toast(error.message, true); }
}

function renderChangesCardsHtml(files) {
  if (!files || !files.length) {
    return '<p class="empty">当前没有未提交的代码差异。</p>';
  }
  return files.map((f) => {
    const dr = f.diff_review || buildFallbackDiffReviewFromUnified(f.diff || '');
    return renderIdeFileCardHtml(f.path, dr, {
      added: f.added,
      removed: f.removed,
      forceDiffStats: true,
      defaultOpen: false,
    });
  }).join('');
}

let currentViewTurnMsgId = null;

async function loadWorkspaceChanges(turnMsgId = null) {
  currentViewTurnMsgId = turnMsgId;
  const wsId = activeWorkspaceId();
  if (!wsId) {
    $('#workspace-diff').innerHTML = '<p class="empty">选择项目或开始对话后查看代码差异。</p>';
    return;
  }
  try {
    let result;
    if (turnMsgId && conversationId) {
      result = await api('/conversations/' + encodeURIComponent(conversationId) + '/messages/' + encodeURIComponent(turnMsgId) + '/changes');
    } else {
      result = await api('/projects/' + encodeURIComponent(wsId) + '/workspace/changes');
    }
    cachedWorkspaceChanges = result;
    const files = result.files || [];
    if ($('#workspace-changes-summary')) {
      const totalAdd = files.reduce((s, f) => s + Number(f.added || 0), 0);
      const totalDel = files.reduce((s, f) => s + Number(f.removed || 0), 0);
      $('#workspace-changes-summary').innerHTML = files.length
        ? '共 ' + files.length + ' 个文件改动 · <span class="diff-add">+' + totalAdd + '</span> <span class="diff-del">-' + totalDel + '</span>'
        : '文件改动概览';
    }
    if (!files.length) {
      $('#workspace-diff').innerHTML = '<p class="empty">' + escapeHtml(result.diff || '该轮次无代码文件差异。') + '</p>';
    } else {
      $('#workspace-diff').innerHTML = renderChangesCardsHtml(files);
    }
  } catch (error) {
    $('#workspace-diff').innerHTML = '<p class="feedback error">' + escapeHtml(error.message) + '</p>';
  }
}

async function loadWorkspaceReview() {
  const wsId = activeWorkspaceId();
  if (!wsId) {
    $('#workspace-review-content').innerHTML = '<p class="empty">请先选择项目或开始对话。</p>';
    return;
  }
  try {
    const [entries, changes] = await Promise.all([
      api('/projects/' + encodeURIComponent(wsId) + '/workspace/files?path=' + encodeURIComponent(workspaceFolder || '')),
      api('/projects/' + encodeURIComponent(wsId) + '/workspace/changes').catch(() => ({ files: [] })),
    ]);
    const changedPaths = (changes.files || []).map((f) => f.path).filter((p) => p && !isInternalWorkflowDoc(p));
    const fileCandidates = [...changedPaths];
    for (const item of (entries || [])) {
      if (item.type === 'file' && !isInternalWorkflowDoc(item.path) && !fileCandidates.includes(item.path)) {
        fileCandidates.push(item.path);
      }
    }
    if (selectedWorkspaceFile && !isInternalWorkflowDoc(selectedWorkspaceFile) && !fileCandidates.includes(selectedWorkspaceFile)) {
      fileCandidates.unshift(selectedWorkspaceFile);
    }
    if (changedPaths.length > 0) {
      await runSelectedFilesReview(changedPaths.slice(0, 12));
    } else if (fileCandidates.length > 0) {
      await runSelectedFilesReview(fileCandidates.slice(0, 8));
    } else {
      $('#workspace-review-content').innerHTML = '<p class="empty">当前工作区暂无可审查文件。</p>';
    }
  } catch (error) { $('#workspace-review-content').textContent = error.message; }
}

let selectedReviewProfileId = '';
let lastReviewedPaths = [];

async function runSelectedFilesReview(explicitPaths = null) {
  const wsId = activeWorkspaceId();
  if (!wsId) return toast('请先选择项目或开始对话。', true);
  let paths = explicitPaths;
  if (!paths || !paths.length) {
    const changed = (cachedWorkspaceChanges.files || []).map((f) => f.path).filter((p) => p && !isInternalWorkflowDoc(p));
    paths = changed.length ? changed : (lastReviewedPaths.length ? lastReviewedPaths : (selectedWorkspaceFile ? [selectedWorkspaceFile] : []));
  }
  if (!paths.length) {
    await loadWorkspaceReview();
    return;
  }
  lastReviewedPaths = [...paths];
  const activeReviewProfile = selectedReviewProfileId || team?.review_profile_id || team?.main_profile_id || $('#chat-model-select')?.value || profiles[0]?.id || 'env-default';
  selectedReviewProfileId = activeReviewProfile;
  $('#workspace-review-content').innerHTML = '<p class="empty">正在执行代码审查与差异比对…</p>';
  try {
    const res = await api('/projects/' + encodeURIComponent(wsId) + '/workspace/review-files', 'POST', {
      paths,
      review_profile_id: activeReviewProfile,
    });
    const items = res.results || res.files || [];
    lastReviewedFilesData = items;
    const ocrLoaded = res.ocr_status?.loaded !== false;
    const summary = res.summary || {
      total: items.length,
      passed: items.filter((i) => i.status === 'passed').length,
      warnings: items.filter((i) => i.status === 'warning').length,
      failed: items.filter((i) => i.status === 'failed').length,
    };
    const modelOptionsHtml = (profiles && profiles.length
      ? profiles
      : [{ id: 'env-default', name: '默认模型', model: 'DeepSeek' }]
    ).map((p) => {
      const sel = p.id === activeReviewProfile ? ' selected' : '';
      const display = modelDisplayName(p);
      const label = (display && display !== p.name) ? (p.name + ' · ' + display) : (p.name || display);
      return '<option value="' + escapeHtml(p.id) + '"' + sel + '>' + escapeHtml(label) + '</option>';
    }).join('');
    const ocrConsoleCard =
      '<div class="review-console-card">' +
        '<div class="review-console-bar">' +
          '<div class="review-console-stats">' +
            '<span class="review-engine-dot ' + (ocrLoaded ? 'is-ready' : 'is-builtin') + '"></span>' +
            '<span class="review-stat-total">审查 ' + Number(summary.total || items.length) + ' 项</span>' +
            '<span class="stat-pass">通过 ' + Number(summary.passed || 0) + '</span>' +
            (summary.warnings ? '<span class="stat-warn">提示 ' + Number(summary.warnings) + '</span>' : '') +
            (summary.failed ? '<span class="stat-fail">待修复 ' + Number(summary.failed) + '</span>' : '') +
          '</div>' +
          '<div class="review-console-btn-row">' +
            '<button type="button" class="review-console-btn" data-open-add-review-model="true" title="添加或管理审查模型">+ 模型</button>' +
            '<button type="button" class="review-console-btn primary" data-rerun-open-code-review="true">重新审查</button>' +
          '</div>' +
        '</div>' +
        '<div class="review-model-row">' +
          '<span class="review-model-label">审查模型</span>' +
          '<div class="review-model-select-wrap">' +
            '<select id="workspace-review-model-select" class="review-model-select" aria-label="选择审查模型">' +
              modelOptionsHtml +
            '</select>' +
          '</div>' +
        '</div>' +
      '</div>';
    $('#workspace-review-content').innerHTML = ocrConsoleCard + (items.map((item) => {
      const issuesHtml = (item.issues || []).length
        ? '<div class="ide-file-issues"><ul>' + item.issues.map((iss) => '<li>[' + escapeHtml(iss.severity) + ' 行 ' + Number(iss.line || 1) + '] ' + escapeHtml(iss.message) + '</li>').join('') + '</ul></div>'
        : '';
      const dr = item.diff_review || {};
      const statusPillHtml = '<span class="review-status-pill ' + escapeHtml(item.status || 'passed') + '">' +
        (item.status === 'passed' ? '通过' : (item.status === 'warning' ? '提示' : '待修复')) +
      '</span>';
      return renderIdeFileCardHtml(item.path, dr, {
        added: dr.added,
        removed: dr.removed,
        forceDiffStats: true,
        totalLines: item.lines,
        statusPillHtml,
        issuesHtml,
        defaultOpen: false,
      });
    }).join('') || '<p class="empty">未返回审查结果。</p>');
    const modelSel = $('#workspace-review-model-select');
    if (modelSel) {
      enhanceSelect(modelSel);
      modelSel.addEventListener('change', async () => {
        selectedReviewProfileId = modelSel.value;
        if (team) {
          team.review_profile_id = selectedReviewProfileId;
          if ($('#review-profile')) {
            $('#review-profile').value = selectedReviewProfileId;
            refreshSelectMenu($('#review-profile'));
          }
          const projId = currentProjectId();
          if (projId && team.agents?.length) {
            api('/projects/' + encodeURIComponent(projId) + '/team', 'PUT', {
              requirement: team.requirement || '项目协作开发任务',
              main_profile_id: team.main_profile_id || selectedReviewProfileId,
              review_profile_id: selectedReviewProfileId,
              review_mode: 'open-code-review',
              agents: team.agents,
              max_concurrency: team.max_concurrency || 2,
              conversation_id: conversationId || null,
            }).then((saved) => { team = saved; }).catch(() => {});
          }
        }
        toast('已切换审查模型，正在重新审查…');
        await runSelectedFilesReview(lastReviewedPaths);
      });
    }
  } catch (error) {
    $('#workspace-review-content').innerHTML = '<p class="feedback error">' + escapeHtml(error.message) + '</p>';
  }
}

function setBrowserPage() {}

function showWorkspacePanel(name, refresh = true, turnMsgId = null) {
  document.body.classList.remove('inspector-closed');
  document.querySelectorAll('[data-workspace-panel]').forEach((button) =>
    button.classList.toggle('selected', button.dataset.workspacePanel === name));
  document.querySelectorAll('.workspace-panel').forEach((panel) =>
    panel.hidden = panel.id !== 'workspace-' + name);
  if (name === 'files' && refresh) loadWorkspaceFiles();
  if (name === 'changes' && refresh) loadWorkspaceChanges(turnMsgId);
  if (name === 'review' && refresh) loadWorkspaceReview();
}

function showLeftTool(name) {
  if (['plugins', 'skills', 'mcp'].includes(name)) return openCustomizationPage(name);
  closeCustomizationPage();
  document.body.classList.add('sidebar-tools-mode');
  document.body.classList.remove('sidebar-closed');
  const repository = name === 'repository';
  document.querySelectorAll('[data-rail]').forEach((item) => item.classList.toggle('rail-active', item.dataset.rail === name));
  $('#settings-link').classList.remove('rail-active');
  $('#repo-browser').hidden = !repository;
  for (const panel of settingsPanels) $('#' + panel + '-panel').hidden = panel !== name;
  $('#left-tool-name').textContent = repository
    ? '仓库'
    : ({ team: 'Agent 团队', models: '模型', skills: '技能', mcp: 'MCP 服务', plugins: '插件中心', runs: '运行' }[name] || name);
  if (name === 'repository') loadWorkspaceFiles('');
  if (name === 'team') loadTeam();
  if (name === 'models') renderModelList();
  if (name === 'skills') loadSkills();
  if (name === 'mcp') loadMcpServers();
  if (name === 'plugins') loadPlugins();
  if (name === 'runs') loadRuns();
}

const customizationPanelHomes = new Map();
let customizationSection = 'plugins';
const customizationSearchIcon = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/></svg>';
const attachmentMenuIcon = '<svg class="composer-menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M8 8v9a4 4 0 0 0 8 0V6a3 3 0 0 0-6 0v10a2 2 0 0 0 4 0V8"/></svg>';
$('#customization-close').id = 'customization-search-toggle';
$('#customization-search-toggle').innerHTML = customizationSearchIcon;
$('#customization-search-toggle').setAttribute('aria-label', '搜索自定义');
$('#customization-search-toggle').title = '搜索';
for (const [name, title] of [['skills', '技能'], ['mcp', 'MCP 服务']]) {
  const toolbar = document.createElement('div'); toolbar.className = 'custom-section-heading';
  toolbar.innerHTML = '<h2>' + title + '</h2><input type="search" id="custom-' + name + '-search" placeholder="搜索' + title + '" aria-label="搜索' + title + '">';
  $('#' + name + '-panel').prepend(toolbar);
  toolbar.querySelector('input').addEventListener('input', event => {
    const query = event.target.value.trim().toLocaleLowerCase();
    $('#' + (name === 'skills' ? 'skill' : 'mcp') + '-list').querySelectorAll('.model-card').forEach(card => card.hidden = !card.textContent.toLocaleLowerCase().includes(query));
  });
}
function closeCustomizationPage() {
  $('#customization-page').hidden = true;
  document.body.classList.remove('customization-open');
  for (const [panel, home] of customizationPanelHomes) { home.append(panel); panel.hidden = true; }
}
async function openCustomizationPage(name = 'plugins') {
  customizationSection = name;
  closeSettingsPage();
  document.body.classList.remove('sidebar-tools-mode');
  document.body.classList.add('customization-open');
  $('#customization-page').hidden = false;
  for (const key of ['plugins', 'skills', 'mcp']) {
    const panel = $('#' + key + '-panel');
    if (!customizationPanelHomes.has(panel)) customizationPanelHomes.set(panel, panel.parentElement);
    $('#customization-content').append(panel);
    panel.hidden = key !== name;
  }
  document.querySelectorAll('[data-customization-panel]').forEach(button => button.classList.toggle('selected', button.dataset.customizationPanel === name));
  document.querySelectorAll('[data-rail]').forEach(button => button.classList.toggle('rail-active', button.dataset.rail === 'plugins'));
  if (name === 'plugins') { await loadPlugins(); await loadMarket(); }
  if (name === 'skills') await loadSkills();
  if (name === 'mcp') await loadMcpServers();
  try {
    const data = await api('/dsh/plugins' + (currentProjectId() ? '?project_id=' + encodeURIComponent(currentProjectId()) : ''));
    $('#customization-installed').innerHTML = (data.installed || []).map(item => '<button type="button" data-customization-installed="' + escapeHtml(item.id) + '">' + escapeHtml(item.name) + '</button>').join('') || '<p>尚未安装插件</p>';
  } catch (error) { $('#customization-installed').textContent = error.message; }
}
$('#customization-search-toggle').addEventListener('click', () => {
  const input = $(customizationSection === 'plugins' ? '#market-search' : '#custom-' + customizationSection + '-search');
  input?.focus(); input?.select();
});
$('#settings-browse-market').addEventListener('click', () => openCustomizationPage('plugins'));
$('#settings-extension-search').addEventListener('input', event => {
  const query = event.target.value.trim().toLocaleLowerCase();
  $('#settings-plugin-inventory').querySelectorAll('.dsh-plugin-card').forEach(card => card.hidden = !card.textContent.toLocaleLowerCase().includes(query));
});
const settingsExtensionPage = document.querySelector('[data-settings-page="extensions"]');
const settingsInventoryGroup = $('#settings-plugin-inventory').closest('.settings-group-card');
settingsExtensionPage.insertBefore(settingsInventoryGroup, settingsExtensionPage.querySelector('.settings-group-title'));
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('#customization-page').hidden) closeCustomizationPage(); });
document.querySelectorAll('[data-customization-panel]').forEach(button => button.addEventListener('click', () => openCustomizationPage(button.dataset.customizationPanel)));
$('#customization-installed').addEventListener('click', async event => {
  const button = event.target.closest('[data-customization-installed]');
  if (!button) return;
  await openCustomizationPage('plugins');
  openInstalledDetail(button.dataset.customizationInstalled);
});

let activeSettingsSection = 'general';

function clearSettingsHighlights(root) {
  if (!root) return;
  root.querySelectorAll('mark.settings-search-mark').forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    parent.replaceChild(document.createTextNode(mark.textContent || ''), mark);
    parent.normalize();
  });
}

function highlightElementText(element, query) {
  if (!element || !query) return;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${escaped})`, 'gi');
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  let current = walker.nextNode();
  while (current) {
    if (current.nodeValue && regex.test(current.nodeValue)) {
      textNodes.push(current);
    }
    regex.lastIndex = 0;
    current = walker.nextNode();
  }
  for (const node of textNodes) {
    const frag = document.createDocumentFragment();
    const parts = node.nodeValue.split(regex);
    for (let i = 0; i < parts.length; i += 1) {
      if (i % 2 === 1) {
        const mark = document.createElement('mark');
        mark.className = 'settings-search-mark';
        mark.textContent = parts[i];
        frag.appendChild(mark);
      } else if (parts[i]) {
        frag.appendChild(document.createTextNode(parts[i]));
      }
    }
    node.parentNode?.replaceChild(frag, node);
  }
}

function filterSettingsInPlace(rawQuery = '') {
  const container = $('#settings-view .settings-content');
  if (!container) return;
  clearSettingsHighlights(container);
  $('#settings-search-empty')?.remove();
  const query = String(rawQuery || '').trim();
  const lower = query.toLowerCase();
  const pages = [...container.querySelectorAll('[data-settings-page]')];

  if (!query) {
    pages.forEach((page) => {
      page.hidden = page.dataset.settingsPage !== activeSettingsSection;
      page.querySelectorAll('.setting-row, .settings-group-card, .settings-group-title, .dsh-plugin-card, .model-card').forEach((el) => {
        el.hidden = false;
      });
    });
    return;
  }

  let totalMatchedPages = 0;
  for (const page of pages) {
    const pageHeading = page.querySelector('h2')?.textContent || '';
    const pageMatchesHeader = pageHeading.toLowerCase().includes(lower);
    let pageHasHit = false;

    const rows = [...page.querySelectorAll('.setting-row')];
    for (const row of rows) {
      const text = (row.textContent || '').toLowerCase();
      const matched = pageMatchesHeader || text.includes(lower);
      row.hidden = !matched;
      if (matched) {
        pageHasHit = true;
        highlightElementText(row.querySelector('.setting-info'), query);
      }
    }

    const embeddedCards = [...page.querySelectorAll('.dsh-plugin-card, .model-card')];
    for (const card of embeddedCards) {
      const text = (card.textContent || '').toLowerCase();
      const matched = pageMatchesHeader || text.includes(lower);
      card.hidden = !matched;
      if (matched) {
        pageHasHit = true;
        highlightElementText(card.querySelector('strong'), query);
        highlightElementText(card.querySelector('small'), query);
      }
    }

    page.querySelectorAll('.settings-group-card').forEach((groupCard) => {
      const hasVisibleChild = [...groupCard.querySelectorAll('.setting-row, .dsh-plugin-card, .model-card')].some((el) => !el.hidden);
      groupCard.hidden = !hasVisibleChild;
      const prevTitle = groupCard.previousElementSibling;
      if (prevTitle?.classList?.contains('settings-group-title')) {
        prevTitle.hidden = !hasVisibleChild;
      }
    });

    page.hidden = !pageHasHit;
    if (pageHasHit) {
      totalMatchedPages += 1;
      if (pageMatchesHeader) highlightElementText(page.querySelector('h2'), query);
    }
  }

  if (totalMatchedPages === 0) {
    const emptyEl = document.createElement('p');
    emptyEl.id = 'settings-search-empty';
    emptyEl.className = 'empty';
    emptyEl.textContent = '没有找到匹配的设置项。';
    container.appendChild(emptyEl);
  }
}

function applyLocale(locale = 'zh-CN') { setLocale(locale); }

function openSettingsPage(section = 'general') {
  activeSettingsSection = section;
  document.body.classList.remove('sidebar-tools-mode');
  document.body.classList.remove('sidebar-closed');
  document.body.classList.add('settings-open');
  document.querySelectorAll('[data-rail]').forEach((item) => item.classList.remove('rail-active'));
  $('#settings-link').classList.add('rail-active');
  $('#settings-view').hidden = false;
  $('#thread').hidden = true;
  $('.composer-wrap').hidden = true;
  if ($('#settings-search')?.value) {
    $('#settings-search').value = '';
  }
  document.querySelectorAll('[data-settings-section]').forEach((button) =>
    button.classList.toggle('selected', button.dataset.settingsSection === section));
  filterSettingsInPlace('');
  if (section === 'models') renderModelList();
  if (section === 'extensions') loadPlugins();
}

function closeSettingsPage() {
  document.body.classList.remove('settings-open');
  $('#settings-link').classList.remove('rail-active');
  $('#settings-view').hidden = true;
  $('#thread').hidden = false;
  $('.composer-wrap').hidden = false;
}

function applyThemeAndDensity(themeCfg = {}) {
  const mode = themeCfg.mode || 'dark';
  const prefersLight = window.matchMedia?.('(prefers-color-scheme: light)')?.matches;
  const isLight = mode === 'light' || (mode === 'system' && prefersLight);
  document.documentElement.dataset.theme = isLight ? 'light' : 'dark';
  document.body.classList.toggle('theme-light', isLight);
  document.body.classList.toggle('compact-density', Boolean(themeCfg.compactDensity));
}

async function loadDshSettings() {
  try {
    dshSettings = await api('/dsh/settings');
    if ($('#dsh-locale')) $('#dsh-locale').value = dshSettings.general?.locale || 'zh-CN';
    if ($('#dsh-send-enter')) $('#dsh-send-enter').checked = dshSettings.general?.sendWithEnter !== false;
    if ($('#dsh-restore-session')) $('#dsh-restore-session').checked = Boolean(dshSettings.general?.restoreLastSession);
    if ($('#dsh-default-branch')) $('#dsh-default-branch').value = dshSettings.general?.defaultBranch || 'main';
    applyLocale(dshSettings.general?.locale || 'zh-CN');

    if ($('#dsh-preset-template')) $('#dsh-preset-template').value = dshSettings.agentPreset?.template || 'architect';
    if ($('#dsh-preset-name')) $('#dsh-preset-name').value = dshSettings.agentPreset?.name || 'Micro-Multi 主控架构师';
    if ($('#dsh-preset-instructions')) $('#dsh-preset-instructions').value = dshSettings.agentPreset?.instructions || '';

    if (dshSettings.permissions?.defaultMode) {
      const mode = dshSettings.permissions.defaultMode;
      if ($('#setting-access')) $('#setting-access').value = mode;
      if ($('#access-select')) $('#access-select').value = mode;
      updateAccessControl(mode);
      updateAccessDescription(mode);
    }
    if ($('#dsh-block-git')) $('#dsh-block-git').checked = dshSettings.permissions?.blockDestructiveGit !== false;

    if (dshSettings.workspace?.linkProjects !== undefined && $('#setting-link-projects')) {
      $('#setting-link-projects').checked = Boolean(dshSettings.workspace.linkProjects);
    }
    if (dshSettings.shell?.timeoutSeconds && $('#setting-command-timeout')) {
      $('#setting-command-timeout').value = String(dshSettings.shell.timeoutSeconds);
    }

    if ($('#dsh-max-tool-steps')) $('#dsh-max-tool-steps').value = String(dshSettings.agentLoop?.maxToolSteps || 30);
    if ($('#dsh-autonomous-hours')) $('#dsh-autonomous-hours').value = String(dshSettings.agentLoop?.autonomousHours || 8);
    if ($('#dsh-recovery-attempts')) $('#dsh-recovery-attempts').value = String(dshSettings.agentLoop?.recoveryMaxAttempts ?? 2);

    const subConc = Number(dshSettings.subagent?.maxConcurrent || 2);
    if ($('#dsh-subagent-concurrency')) {
      if ([1, 2, 3, 4].includes(subConc)) {
        $('#dsh-subagent-concurrency').value = String(subConc);
        $('#dsh-subagent-concurrency-custom').hidden = true;
      } else {
        $('#dsh-subagent-concurrency').value = 'custom';
        $('#dsh-subagent-concurrency-custom').hidden = false;
        $('#dsh-subagent-concurrency-custom').value = String(subConc);
      }
    }

    if (dshSettings.context?.maxContextTokens) {
      contextMaxTokens = Number(dshSettings.context.maxContextTokens) || 64000;
      localStorage.setItem('masp.contextMaxTokens', String(contextMaxTokens));
      if ($('#context-limit-select')) $('#context-limit-select').value = String(contextMaxTokens);
    }
    if (dshSettings.context?.autoCompact !== undefined) {
      contextAutoCompact = Boolean(dshSettings.context.autoCompact);
      localStorage.setItem('masp.contextAutoCompact', String(contextAutoCompact));
      if ($('#context-auto-compact')) $('#context-auto-compact').checked = contextAutoCompact;
    }

    const sc = dshSettings.shortcuts || {};
    if ($('#dsh-shortcut-search')) $('#dsh-shortcut-search').value = String(sc.globalSearch || 'Ctrl+K').replace(/\s+/g, '');
    if ($('#dsh-shortcut-new-chat')) $('#dsh-shortcut-new-chat').value = String(sc.newChat || 'Ctrl+N').replace(/\s+/g, '');
    if ($('#dsh-shortcut-settings')) $('#dsh-shortcut-settings').value = String(sc.openSettings || 'Ctrl+,').replace(/\s+/g, '');
    if ($('#dsh-shortcut-send')) {
      const sendCombo = String(sc.sendMessage || (dshSettings.general?.sendWithEnter === false ? 'Ctrl+Enter' : 'Enter')).replace(/\s+/g, '');
      $('#dsh-shortcut-send').value = sendCombo === 'Ctrl+Enter' ? 'Ctrl+Enter' : 'Enter';
    }

    if ($('#dsh-theme-mode')) $('#dsh-theme-mode').value = dshSettings.theme?.mode || 'dark';
    if ($('#dsh-compact-density')) $('#dsh-compact-density').checked = Boolean(dshSettings.theme?.compactDensity);
    if ($('#dsh-session-log-enabled')) $('#dsh-session-log-enabled').checked = dshSettings.sessionLog?.enabled !== false;

    applyThemeAndDensity(dshSettings.theme || {});
    refreshSelectMenus();
    refreshContextUsage().catch(() => {});
  } catch {}
}

let settingsSaveQueue = Promise.resolve();
let settingsSaveRevision = 0;
function persistDshSettingsPatch(patch) {
  const revision = ++settingsSaveRevision;
  dshSettings = { ...(dshSettings || {}) };
  for (const [key, value] of Object.entries(patch)) {
    dshSettings[key] = typeof value === 'object' && value !== null
      ? { ...(dshSettings[key] || {}), ...value } : value;
  }
  // Apply locally immediately; serialize writes so rapid switches cannot lose settings.
  applyThemeAndDensity(dshSettings.theme || {});
  if (patch.general?.locale) applyLocale(patch.general.locale);
  settingsSaveQueue = settingsSaveQueue.catch(() => {}).then(async () => {
    try {
      const saved = await api('/dsh/settings', 'PUT', patch);
      if (revision === settingsSaveRevision) {
        dshSettings = saved;
        applyThemeAndDensity(saved.theme || {});
      }
      if (patch.general?.defaultBranch) updateContextLabels();
    } catch (error) {
      toast(error.message, true);
    }
  });
  return settingsSaveQueue;
}

function initializeSettings() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('masp.settings') || '{}'); } catch {}
  $('#setting-access').value = saved.access || 'commands';
  $('#access-select').value = saved.access || 'commands';
  updateAccessControl(saved.access || 'commands');
  updateAccessDescription($('#setting-access').value);
  $('#setting-link-projects').checked = saved.linkProjects !== false;
  $('#setting-command-timeout').value = String(saved.commandTimeout || 120);
  $('#app-version').textContent = window.maspDesktop?.version || '0.1.0';
  const persist = () => {
    const settings = {
      access: $('#setting-access').value,
      linkProjects: $('#setting-link-projects').checked,
      commandTimeout: Number($('#setting-command-timeout').value),
    };
    localStorage.setItem('masp.settings', JSON.stringify(settings));
    $('#access-select').value = settings.access;
    updateAccessControl(settings.access);
    updateAccessDescription(settings.access);
    persistDshSettingsPatch({
      permissions: {
        defaultMode: settings.access,
        blockDestructiveGit: $('#dsh-block-git')?.checked ?? true,
      },
      workspace: {
        linkProjects: settings.linkProjects,
      },
      general: {
        linkProjects: settings.linkProjects,
      },
      shell: {
        timeoutSeconds: settings.commandTimeout,
      },
    });
  };
  for (const id of ['setting-access', 'setting-link-projects', 'setting-command-timeout', 'dsh-block-git']) {
    $('#' + id)?.addEventListener('change', persist);
  }
  for (const id of ['dsh-locale', 'dsh-send-enter', 'dsh-restore-session', 'dsh-default-branch']) {
    $('#' + id)?.addEventListener('change', () => {
      const sendWithEnter = $('#dsh-shortcut-send').value === 'Enter';
      if ($('#dsh-shortcut-send')) {
        $('#dsh-shortcut-send').value = sendWithEnter ? 'Enter' : 'Ctrl+Enter';
        refreshSelectMenu($('#dsh-shortcut-send'));
      }
      persistDshSettingsPatch({
        general: {
          locale: $('#dsh-locale').value,
          sendWithEnter,
          restoreLastSession: $('#dsh-restore-session').checked,
          defaultBranch: $('#dsh-default-branch').value.trim() || 'main',
        },
        shortcuts: {
          sendMessage: sendWithEnter ? 'Enter' : 'Ctrl+Enter',
        },
      });
    });
  }
  for (const id of ['dsh-theme-mode', 'dsh-compact-density']) {
    $('#' + id)?.addEventListener('change', () => {
      const themePatch = {
        mode: $('#dsh-theme-mode').value,
        compactDensity: $('#dsh-compact-density').checked,
      };
      applyThemeAndDensity(themePatch);
      persistDshSettingsPatch({ theme: themePatch });
    });
  }
  const saveShortcutsNow = async () => {
    const globalSearch = $('#dsh-shortcut-search')?.value || 'Ctrl+K';
    const newChat = $('#dsh-shortcut-new-chat')?.value || 'Ctrl+N';
    const openSettings = $('#dsh-shortcut-settings')?.value || 'Ctrl+,';
    const sendMessage = $('#dsh-shortcut-send')?.value || 'Enter';
    const sendWithEnter = sendMessage === 'Enter';
    if ($('#dsh-send-enter')) $('#dsh-send-enter').checked = sendWithEnter;
    await persistDshSettingsPatch({
      shortcuts: { globalSearch, newChat, openSettings, sendMessage },
      general: { sendWithEnter },
    });
    setFeedback('#dsh-shortcuts-feedback', '快捷键已保存并立即生效。');
  };
  for (const id of ['dsh-shortcut-search', 'dsh-shortcut-new-chat', 'dsh-shortcut-settings', 'dsh-shortcut-send']) {
    $('#' + id)?.addEventListener('change', saveShortcutsNow);
  }
  $('#dsh-reset-shortcuts')?.addEventListener('click', async () => {
    if ($('#dsh-shortcut-search')) $('#dsh-shortcut-search').value = 'Ctrl+K';
    if ($('#dsh-shortcut-new-chat')) $('#dsh-shortcut-new-chat').value = 'Ctrl+N';
    if ($('#dsh-shortcut-settings')) $('#dsh-shortcut-settings').value = 'Ctrl+,';
    if ($('#dsh-shortcut-send')) $('#dsh-shortcut-send').value = 'Enter';
    refreshSelectMenus();
    await saveShortcutsNow();
  });
  const savePresetNow = async () => {
    await persistDshSettingsPatch({
      agentPreset: {
        template: $('#dsh-preset-template').value,
        name: $('#dsh-preset-name').value.trim() || 'Micro-Multi 主控架构师',
        instructions: $('#dsh-preset-instructions').value.trim(),
      },
    });
    setFeedback('#dsh-preset-feedback', '智能体预设已保存并将在后续对话中生效。');
  };
  $('#dsh-preset-template')?.addEventListener('change', () => {
    const tpl = $('#dsh-preset-template').value;
    const templates = {
      architect: {
        name: 'Micro-Multi 主控架构师',
        instructions: '始终优先保持代码最小改动、契约先行与可验证性。首轮对话提出任务时合理规划子 Agent 分工。',
      },
      fullstack: {
        name: '全栈敏捷工程师',
        instructions: '前后端协同推进，优先跑通端到端数据流与自动化测试。',
      },
      reviewer: {
        name: '契约与安全审计专家',
        instructions: '严格核查边界条件、输入校验、类型安全与潜在回归风险。',
      },
    };
    if (templates[tpl]) {
      $('#dsh-preset-name').value = templates[tpl].name;
      $('#dsh-preset-instructions').value = templates[tpl].instructions;
    }
    savePresetNow();
  });
  $('#dsh-preset-name')?.addEventListener('change', savePresetNow);
  $('#dsh-save-preset')?.addEventListener('click', savePresetNow);

  const saveWorkspaceLoopNow = async () => {
    const rawConc = $('#dsh-subagent-concurrency').value === 'custom'
      ? Number($('#dsh-subagent-concurrency-custom').value)
      : Number($('#dsh-subagent-concurrency').value);
    const maxConcurrent = Math.max(1, Math.min(64, rawConc || 2));
    await persistDshSettingsPatch({
      agentLoop: {
        maxToolSteps: Math.max(5, Math.min(50, Number($('#dsh-max-tool-steps').value) || 30)),
        autonomousHours: Number($('#dsh-autonomous-hours').value || 8),
        recoveryMaxAttempts: Math.max(0, Math.min(5, Number($('#dsh-recovery-attempts').value))),
      },
      subagent: {
        maxConcurrent,
      },
    });
    setFeedback('#dsh-workspace-feedback', '工作区与多智能体并发策略已保存。');
  };
  $('#dsh-subagent-concurrency')?.addEventListener('change', () => {
    $('#dsh-subagent-concurrency-custom').hidden = $('#dsh-subagent-concurrency').value !== 'custom';
    saveWorkspaceLoopNow();
  });
  $('#dsh-subagent-concurrency-custom')?.addEventListener('change', saveWorkspaceLoopNow);
  $('#dsh-max-tool-steps')?.addEventListener('change', saveWorkspaceLoopNow);
  $('#dsh-autonomous-hours')?.addEventListener('change', saveWorkspaceLoopNow);
  $('#dsh-recovery-attempts')?.addEventListener('change', saveWorkspaceLoopNow);
  $('#dsh-save-workspace')?.addEventListener('click', saveWorkspaceLoopNow);

  $('#dsh-session-log-enabled')?.addEventListener('change', async () => {
    const enabled = Boolean($('#dsh-session-log-enabled').checked);
    await persistDshSettingsPatch({
      sessionLog: { enabled },
    });
    setFeedback('#dsh-session-feedback', enabled ? '已开启会话与工具日志记录。' : '已暂停记录新的工具日志。');
  });

  $('#dsh-export-session')?.addEventListener('click', async () => {
    if (!conversationId) {
      setFeedback('#dsh-session-feedback', '当前新聊天尚未发送消息，暂无可导出的会话记录。', true);
      return;
    }
    try {
      const msgs = await api('/conversations/' + encodeURIComponent(conversationId) + '/messages');
      const blob = new Blob([JSON.stringify({ conversation_id: conversationId, messages: msgs }, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = conversationId + '-session-log.json';
      a.click();
      URL.revokeObjectURL(url);
      setFeedback('#dsh-session-feedback', '会话日志已导出。');
    } catch (error) {
      setFeedback('#dsh-session-feedback', error.message, true);
    }
  });

  $('#dsh-compact-session')?.addEventListener('click', async () => {
    if (!conversationId) {
      setFeedback('#dsh-compact-feedback', '当前新聊天尚未发送消息，无需压缩上下文。', true);
      return;
    }
    try {
      setFeedback('#dsh-compact-feedback', '正在生成结构化检查点并压缩历史上下文…');
      const res = await api('/conversations/' + encodeURIComponent(conversationId) + '/compact', 'POST', { keep_recent: 4 });
      if (res.compacted) {
        setFeedback('#dsh-compact-feedback', `已压缩上下文：${res.original_count} 条消息精简为 ${res.retained_count} 条。`);
        await openConversation(conversationId, { record: false });
        openSettingsPage('session-log');
      } else {
        setFeedback('#dsh-compact-feedback', `当前对话仅 ${res.original_count} 条消息，保持完整上下文即可。`);
      }
    } catch (error) {
      setFeedback('#dsh-compact-feedback', error.message, true);
    }
  });
}

function updateAccessDescription(mode) {
  const descriptions = {
    read: '请求批准: 默认只读浏览。遇到文件修改、删除或终端命令时将弹出交互式批准窗口询问您。',
    files: '帮我批准: 读取与文件修改自动执行，终端命令和扩展操作需用户逐次确认。',
    commands: '完全访问: 完全放开 Shell 终端与全部工具权限，不限制命令白名单，允许执行任意脚本与操作。',
  };
  $('#access-description').textContent = descriptions[mode] || descriptions.read;
}

function updateAccessControl(mode = $('#access-select').value) {
  const labels = { read: '请求批准', files: '帮我批准', commands: '完全访问' };
  $('#access-label').textContent = labels[mode] || labels.read;
  if ($('#access-trigger')) {
    $('#access-trigger').dataset.mode = mode;
    $('#access-trigger').setAttribute('aria-label', labels[mode] || labels.read);
  }
  document.querySelectorAll('[data-access-value]').forEach((option) => {
    const selected = option.dataset.accessValue === mode;
    option.setAttribute('aria-selected', String(selected));
    option.hidden = false;
  });
}

function refreshSelectMenu(select) {
  if (!select?.dataset?.selectMenuId) return;
  const menu = document.getElementById(select.dataset.selectMenuId);
  const trigger = document.querySelector('[aria-controls="' + select.dataset.selectMenuId + '"]');
  if (!menu || !trigger) return;
  const selected = [...select.options].find((option) => option.value === select.value) || select.options[0];
  trigger.querySelector('.select-trigger-label').textContent = selected?.textContent.trim() || '选择…';
  trigger.title = selected?.textContent.trim() || '';
  if (select.id === 'chat-model-select') trigger.setAttribute('aria-label', '选择模型：' + trigger.title);
  trigger.disabled = select.disabled;
  menu.innerHTML = '';
  [...select.options].forEach((option) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'select-option';
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', String(option.value === select.value));
    item.disabled = option.disabled;
    item.dataset.selectValue = option.value;
    item.textContent = option.textContent.trim();
    menu.append(item);
  });
}

function refreshSelectMenus() {
  document.querySelectorAll('select[data-select-menu-id]').forEach(refreshSelectMenu);
}

function enhanceSelect(select) {
  if (select.dataset.selectMenuId || select.id === 'access-select' ||
      select.closest('.project-select-hidden, .plugin-slot-host, .plugin-client-root, #plugin-runtime-roots')) return;
  const id = 'select-menu-' + (++selectMenuNumber);
  select.dataset.selectMenuId = id;
  select.classList.add('native-select-hidden');
  select.setAttribute('aria-hidden', 'true');
  select.tabIndex = -1;
  const host = select.parentElement;
  host.classList.add('custom-select-host');
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'select-trigger';
  trigger.setAttribute('aria-haspopup', 'listbox');
  trigger.setAttribute('aria-expanded', 'false');
  trigger.setAttribute('aria-controls', id);
  const label = document.createElement('span');
  label.className = 'select-trigger-label';
  const chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  chevron.setAttribute('viewBox', '0 0 16 16');
  chevron.setAttribute('aria-hidden', 'true');
  chevron.innerHTML = '<path d="m4 6 4 4 4-4"/>';
  trigger.append(label, chevron);
  const menu = document.createElement('div');
  menu.id = id;
  menu.className = 'select-popover';
  menu.setAttribute('role', 'listbox');
  menu.hidden = true;
  host.append(trigger, menu);
  select.addEventListener('change', () => refreshSelectMenu(select));
  new MutationObserver(() => refreshSelectMenu(select)).observe(select, { childList: true, subtree: true });
  refreshSelectMenu(select);
}

function installSelectMenus() {
  const initialize = (root = document) => {
    if (root.closest?.('.masp-markdown, .plugin-client-root')) return;
    if (root.matches?.('select')) enhanceSelect(root);
    root.querySelectorAll?.('select').forEach(enhanceSelect);
  };
  initialize();
  new MutationObserver((records) => records.forEach((record) =>
    record.addedNodes.forEach((node) => { if (node.nodeType === Node.ELEMENT_NODE) initialize(node); })
  )).observe(document.body, { childList: true, subtree: true });
  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('.select-trigger');
    const option = event.target.closest('.select-option');
    if (option) {
      const menu = option.closest('.select-popover');
      const select = document.querySelector('[data-select-menu-id="' + menu.id + '"]');
      if (select) {
        select.value = option.dataset.selectValue;
        select.dispatchEvent(new Event('input', { bubbles: true }));
        select.dispatchEvent(new Event('change', { bubbles: true }));
        refreshSelectMenu(select);
      }
      menu.hidden = true;
      document.querySelector('[aria-controls="' + menu.id + '"]')?.setAttribute('aria-expanded', 'false');
      return;
    }
    if (trigger) {
      const menu = document.getElementById(trigger.getAttribute('aria-controls'));
      const opening = menu.hidden;
      document.querySelectorAll('.select-popover:not([hidden])').forEach((openMenu) => {
        openMenu.hidden = true;
        document.querySelector('[aria-controls="' + openMenu.id + '"]')?.setAttribute('aria-expanded', 'false');
      });
      if (opening) {
        menu.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        const rect = trigger.getBoundingClientRect();
        const isCompactSelect = Boolean(trigger.closest('.context-popover-row'));
        const isReviewSelect = Boolean(trigger.closest('.review-model-select-wrap'));
        const minW = isCompactSelect ? 148 : (isReviewSelect ? 200 : 220);
        const width = Math.min(Math.max(rect.width, minW), innerWidth - 24);
        menu.style.width = width + 'px';
        menu.style.maxHeight = '300px';
        menu.style.left = '0px';
        menu.style.top = '0px';
        const cbRect = menu.getBoundingClientRect();
        const height = Math.min(menu.scrollHeight || 160, 300);
        const targetLeft = Math.max(12, Math.min(rect.left, innerWidth - width - 12));
        const targetTop = rect.top >= height + 14 ? (rect.top - height - 6) : (rect.bottom + 6);
        menu.style.left = Math.round(targetLeft - cbRect.left) + 'px';
        menu.style.top = Math.round(targetTop - cbRect.top) + 'px';
        menu.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
      }
      return;
    }
    document.querySelectorAll('.select-popover:not([hidden])').forEach((menu) => {
      menu.hidden = true;
      document.querySelector('[aria-controls="' + menu.id + '"]')?.setAttribute('aria-expanded', 'false');
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.select-popover:not([hidden])').forEach((menu) => {
      menu.hidden = true;
      document.querySelector('[aria-controls="' + menu.id + '"]')?.setAttribute('aria-expanded', 'false');
    });
  });
}

function renderAttachments() {
  $('#attachment-list').innerHTML = pendingAttachments.map((item, index) =>
    '<span class="attachment-chip">' + (item.kind === 'image' ? '<img class="attachment-preview" alt="" src="' + escapeHtml(item.data_url) + '">' : '') + escapeHtml(item.name) +
    '<button type="button" data-remove-attachment="' + index + '" aria-label="移除附件">×</button></span>'
  ).join('');
}

const lastTrackedLabels = {
  model: '',
  agent: '',
  access: '',
};

function getSelectOptionLabel(selectEl, fallback = '') {
  if (!selectEl) return fallback;
  const opt = [...(selectEl.options || [])].find((o) => o.value === selectEl.value) || selectEl.options?.[0];
  return (opt ? opt.textContent : selectEl.value || fallback).trim();
}

function getAccessModeLabel(mode) {
  const map = { read: '请求批准', files: '帮我批准', commands: '完全访问' };
  return map[mode] || mode || '请求批准';
}

function syncTrackedSelectorLabels() {
  lastTrackedLabels.model = getSelectOptionLabel($('#chat-model-select'), '');
  lastTrackedLabels.agent = getSelectOptionLabel($('#agent-select'), '');
  lastTrackedLabels.access = getAccessModeLabel($('#access-select')?.value);
}

function modelDisplayName(profile) {
  let display = profile?.display_model || profile?.model || '';
  try { const wire = JSON.parse(display); if (Array.isArray(wire) && wire.length === 2) display = wire[1]; } catch {}
  return String(display);
}

function renderSelectors() {
  projects = (projects || []).filter((p) => !isSpuriousConvItem(p));
  const currentProject = draftProjectId || $('#project-select').value;
  $('#project-select').innerHTML = '<option value="">通用对话</option>' +
    projects.map((p) => '<option value="' + escapeHtml(p.id) + '">' + escapeHtml(p.name) + '</option>').join('');
  $('#project-select').value = currentProject || '';
  renderContextProjects($('#context-project-search')?.value || '');
  updateContextLabels();
  const options = profiles.map((p) =>
    '<option value="' + escapeHtml(p.id) + '">' + escapeHtml(p.name) + ' · ' + escapeHtml(modelDisplayName(p)) + '</option>'
  ).join('');
  for (const selector of ['#chat-model-select', '#main-profile']) {
    const element = $(selector);
    const current = element.value;
    element.innerHTML = options || '<option value="">先添加模型</option>';
    if (profiles.some((p) => p.id === current)) element.value = current;
  }
  const review = $('#review-profile');
  const previousReview = review.value;
  review.innerHTML = '<option value="">沿用主 Agent 模型</option>' + options;
  refreshSelectMenus();
  if (profiles.some((p) => p.id === previousReview)) review.value = previousReview;
  syncTrackedSelectorLabels();
  renderProjectList();
  renderModelList();
  updateHeader();
}

function renderModelList() {
  const html = profiles.map((profile) =>
    '<div class="model-card"><strong>' + escapeHtml(profile.name) + '</strong><small>' +
    escapeHtml(modelDisplayName(profile)) + '<br>' + escapeHtml(profile.base_url) + '</small><div class="row-actions">' +
    '<button type="button" data-probe="' + escapeHtml(profile.id) + '">检测连接</button>' +
    (profile.id === 'env-default' ? '' : '<button type="button" data-edit-profile="' + escapeHtml(profile.id) + '">编辑</button>') +
    '</div><p class="feedback model-card-feedback" data-probe-result="' + escapeHtml(profile.id) + '" role="status"></p></div>'
  ).join('') || '<p class="empty">尚未配置模型。添加一个兼容 OpenAI 格式的 API。</p>';
  $('#model-list').innerHTML = html;
  if ($('#settings-model-list')) $('#settings-model-list').innerHTML = html;
}

function agentCard(agent) {
  const options = '<option value=""' + (!agent.model_profile_id ? ' selected' : '') + '>跟随当前主模型</option>' + profiles.map((profile) =>
    '<option value="' + escapeHtml(profile.id) + '"' +
    (profile.id === agent.model_profile_id ? ' selected' : '') + '>' +
    escapeHtml(profile.name) + ' · ' + escapeHtml(modelDisplayName(profile)) + '</option>'
  ).join('');
  return '<article class="agent-card" data-agent="' + escapeHtml(agent.id) + '">' +
    '<div class="agent-heading"><strong>' + icon('team') + ' 子 Agent</strong><button type="button" data-remove-agent="' + escapeHtml(agent.id) + '">移除</button></div>' +
    '<label>标识<input class="agent-id" value="' + escapeHtml(agent.id) + '" required pattern="[a-z][a-z0-9_-]*"></label>' +
    '<label>名称<input class="agent-name" value="' + escapeHtml(agent.name) + '" required></label>' +
    '<label>职责<textarea class="agent-responsibility" rows="2" required>' + escapeHtml(agent.responsibility) + '</textarea></label>' +
    '<label>提示词<textarea class="agent-system-prompt" rows="3">' + escapeHtml(agent.system_prompt || '') + '</textarea></label>' +
    '<label>模型<select class="agent-profile">' + options + '</select></label>' +
    '<label>负责路径<input class="agent-paths" value="' + escapeHtml((agent.owned_paths || []).join(', ')) + '" placeholder="逗号分隔，可留空"></label>' +
    '<label class="check-row"><input class="agent-locked" type="checkbox"' + (agent.locked ? ' checked' : '') + '>重新规划时保留此 Agent</label></article>';
}

function modalAgentCard(agent, index) {
  const options = '<option value=""' + (!agent.model_profile_id ? ' selected' : '') + '>跟随当前主模型</option>' + profiles.map((profile) =>
    '<option value="' + escapeHtml(profile.id) + '"' +
    (profile.id === agent.model_profile_id ? ' selected' : '') + '>' +
    escapeHtml(profile.name) + ' · ' + escapeHtml(modelDisplayName(profile)) + '</option>'
  ).join('');
  return '<article class="modal-agent-card" data-modal-agent-index="' + index + '">' +
    '<div class="agent-heading"><strong>子 Agent #' + (index + 1) + '</strong><button type="button" data-modal-remove-agent="' + index + '">移除</button></div>' +
    '<label>名称<input class="modal-agent-name" value="' + escapeHtml(agent.name) + '"></label>' +
    '<label>职责分工<textarea class="modal-agent-responsibility" rows="2">' + escapeHtml(agent.responsibility) + '</textarea></label>' +
    '<label>提示词<textarea class="modal-agent-system-prompt" rows="3">' + escapeHtml(agent.system_prompt || '') + '</textarea></label>' +
    '<label>绑定模型<select class="modal-agent-profile">' + options + '</select></label>' +
    '<label>负责路径<input class="modal-agent-paths" value="' + escapeHtml((agent.owned_paths || []).join(', ')) + '" placeholder="逗号分隔"></label>' +
    '</article>';
}

function buildMindmapSvg(count, invert = false) {
  if (!count) return '';
  const width = 600;
  const height = 34;
  const centerX = width / 2;
  const paths = [];
  for (let i = 0; i < count; i++) {
    const targetX = count === 1 ? centerX : Math.round((width / (count * 2)) * (2 * i + 1));
    const startX = invert ? targetX : centerX;
    const endX = invert ? centerX : targetX;
    const d = `M ${startX} 0 C ${startX} 18, ${endX} 16, ${endX} ${height}`;
    paths.push('<path d="' + d + '"/>');
  }
  return '<svg class="mindmap-svg" viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" aria-hidden="true">' + paths.join('') + '</svg>';
}

let currentActiveRun = null;
let currentRunEvents = [];
let modalWorkflowZoom = 1;

function resolveWorkflowAgentStatus(agent, index) {
  if (!currentActiveRun) {
    return { state: 'ready', label: team?.status === 'approved' ? '已就绪' : '待确认' };
  }
  const runState = String(currentActiveRun.state || '');
  const tasks = currentActiveRun.tasks || [];
  const runAgents = currentActiveRun.agents || [];
  const matchedTask = tasks[index] || tasks.find((t) =>
    t.agent_id === agent.id ||
    t.spec?.owner_role === agent.id ||
    t.spec?.title?.includes(agent.name)
  );
  const matchedAgent = runAgents.find((a) => a.id === agent.id || a.role === agent.name || a.role === agent.id);
  const rawState = String(matchedTask?.state || matchedAgent?.state || '').toUpperCase();
  if (rawState.includes('RUN') || rawState.includes('EXEC')) {
    return { state: 'running', label: '并行执行中' };
  }
  if (rawState.includes('SUCCEED') || rawState.includes('COMPLET') || rawState.includes('DONE') || rawState.includes('MERGED') || rawState.includes('SUBMIT')) {
    return { state: 'completed', label: '已完成' };
  }
  if (rawState.includes('FAIL') || rawState.includes('ERROR') || rawState.includes('BLOCK')) {
    return { state: 'failed', label: '异常' };
  }
  if (runState === 'SUCCEEDED' || runState === 'HUMAN_REVIEW_REQUIRED') return { state: 'completed', label: '已完成' };
  if (runState === 'RUNNING' || runState === 'PLANNING') return { state: 'running', label: '并行调度中' };
  return { state: 'ready', label: '待命' };
}

function formatRunStateInfo(rawState) {
  const s = String(rawState || '').toUpperCase();
  if (s === 'SUCCEEDED' || s === 'COMPLETED' || s === 'MERGED' || s === 'SUBMITTED') {
    return { label: '已完成', cls: 'state-succeeded', desc: '全部子任务代码开发与审查均已完成并合并至工作区。' };
  }
  if (s === 'PLANNING') {
    return { label: '正在规划分工', cls: 'state-planning', desc: '主 Agent 正在拆解需求、制定契约并分配并行子任务。' };
  }
  if (s === 'RUNNING' || s === 'EXECUTING') {
    return { label: '并行执行中', cls: 'state-running', desc: '子 Agent 正在独立工作区并发编写与自检代码。' };
  }
  if (s === 'FINAL_VERIFY' || s === 'REVIEWING') {
    return { label: '审查与合流中', cls: 'state-running', desc: '正在使用 Open Code Review 校验代码差异并合并至主分支。' };
  }
  if (s === 'FAILED') {
    return { label: '执行中断', cls: 'state-failed', desc: '子任务执行遇到异常，可点击下方按钮重新运行或提出微调。' };
  }
  if (s === 'CANCELLED') {
    return { label: '已手动中止', cls: 'state-blocked', desc: '本轮多 Agent 协作任务已被用户中止。' };
  }
  if (s === 'HUMAN_REVIEW_REQUIRED') {
    return { label: '已自动复核', cls: 'state-succeeded', desc: '已通过 Open Code Review 自动完成审查并同步至工作区。' };
  }
  if (s === 'BLOCKED') {
    return { label: '等待处理', cls: 'state-blocked', desc: '任务存在依赖或策略阻断，等待确认。' };
  }
  return { label: '待命', cls: 'state-planning', desc: '等待启动执行。' };
}

function formatFriendlyRunError(rawError) {
  const text = String(rawError || '').trim();
  if (!text) return '';
  if (/ReadTimeout|timeout|TimedOut/i.test(text)) {
    return '模型响应超时: 生成多文件代码耗时较长，系统已自动启用长连接流式容错保护，请点击下方"重新运行"继续完成。';
  }
  if (/ConnectError|Connection|Network/i.test(text)) {
    return '模型接口网络连接异常: 请检查模型配置的 Base URL 与 API Key 是否可用后点击"重新运行"。';
  }
  return text.replace(/^Model request failed:\s*/i, '模型调用异常: ');
}

function formatRunEventLabel(ev) {
  const type = String(ev?.type || '');
  const p = ev?.payload || {};
  if (type === 'run.state') {
    return '协作阶段切换为 · ' + formatRunStateInfo(p.state).label;
  }
  if (type === 'plan.completed') {
    return '主 Agent 完成任务拆解 · 共 ' + Number(p.task_count || 0) + ' 个并行子任务';
  }
  if (type === 'task.started') {
    return '子 Agent 启动子任务 · ' + (p.title || p.agent_id || '模块开发');
  }
  if (type === 'task.attempt') {
    return '子 Agent 完成第 ' + Number(p.attempt || 1) + ' 轮代码编写与单元自检';
  }
  if (type === 'task.review') {
    return 'Open Code Review 静态与契约校验 · ' + (p.approved !== false ? '通过' : '需修复');
  }
  if (type === 'task.merged') {
    return '子 Agent 改动已合并至工作区 (' + Number((p.changed_files || []).length) + ' 个文件)';
  }
  if (type === 'task.completed') {
    return '子任务交付完成 · ' + (p.title || p.task_id || '');
  }
  if (type === 'task.retry') {
    return '子 Agent 正在根据审查反馈自动修复重试';
  }
  if (type === 'final.verify') {
    return '执行工作区整体构建与最终验证';
  }
  if (type === 'artifact.packaged') {
    return '本轮工程交付产物已打包完成';
  }
  if (type === 'run.failed') {
    return '协作执行中断 · ' + formatFriendlyRunError(p.error);
  }
  return '执行步骤更新 · ' + (p.message || p.state || '已完成');
}

function updateHeaderRunStatus() {
  const badge = $('#header-run-status');
  if (!badge) return;
  badge.textContent = '';
  badge.hidden = true;
}

function renderWorkflowMindmap(currentTeam = team) {
  const sidebarTarget = $('#sidebar-team-workflow');
  const modalTarget = $('#team-workflow');
  if ($('#modal-workflow-zoom-label')) {
    $('#modal-workflow-zoom-label').textContent = Math.round(modalWorkflowZoom * 100) + '%';
  }
  updateHeaderRunStatus();
  const pid = currentProjectId();
  const hasProjectTeam = Boolean(pid && currentTeam?.agents?.length && (!currentTeam.project_id || currentTeam.project_id === pid));
  const hasProjectRun = Boolean(pid && selectedRunId && currentActiveRun?.tasks?.length && (!currentActiveRun.project_id || currentActiveRun.project_id === pid));
  const effectiveTeam = hasProjectTeam ? currentTeam : (
    hasProjectRun ? {
      requirement: currentActiveRun.request?.requirement || '当前多 Agent 任务',
      max_concurrency: currentActiveRun.tasks.length,
      main_profile_id: $('#main-profile')?.value || '',
      status: 'approved',
      agents: currentActiveRun.tasks.map((t, idx) => ({
        id: t.agent_id || ('agent_' + (idx + 1)),
        name: t.title || t.spec?.title || ('子 Agent ' + (idx + 1)),
        responsibility: t.spec?.description || '独立并发执行模块开发与自测',
        model_profile_id: '',
        owned_paths: t.spec?.allowed_paths || [],
      })),
    } : null
  );

  if (!effectiveTeam?.agents?.length) {
    if ($('#workflow-live-badge')) {
      $('#workflow-live-badge').textContent = pid ? '当前对话尚未组建子 Agent · 0%' : '未运行项目 · 0%';
    }
    const emptyMsg = pid
      ? '当前对话尚未组建子 Agent 团队。在首轮发送开发需求后，主 Agent 将自动规划本对话专属的子 Agent 并生成思维导图。'
      : '当前尚未运行项目。请先选择项目并运行开发任务，工作流思维导图将根据当前对话生成。';
    const emptyHtml = '<div class="workflow-empty-hint"><p class="empty">' + emptyMsg + '</p></div>';
    if (sidebarTarget) sidebarTarget.innerHTML = emptyHtml;
    if (modalTarget) modalTarget.innerHTML = emptyHtml;
    return;
  }

  const mainModel = profiles.find((p) => p.id === effectiveTeam.main_profile_id)?.name || '默认主模型';
  const reqSummary = (effectiveTeam.requirement || '当前项目任务').slice(0, 72);
  const runState = String(currentActiveRun?.state || '');
  const hasMergeEvent = currentRunEvents.some((ev) => String(ev.type || '').includes('merge') || String(ev.type || '').includes('review'));
  const statuses = effectiveTeam.agents.map((agent, index) => resolveWorkflowAgentStatus(agent, index));
  const totalAgents = Math.max(1, statuses.length);
  const completedCount = statuses.filter((s) => s.state === 'completed').length;
  const runningCount = statuses.filter((s) => s.state === 'running').length;
  let progressPct = 0;
  if (runState === 'SUCCEEDED') {
    progressPct = 100;
  } else if (runState === 'FINAL_VERIFY' || hasMergeEvent) {
    progressPct = Math.max(85, Math.round((completedCount / totalAgents) * 90));
  } else if (completedCount > 0 || runningCount > 0) {
    progressPct = Math.min(95, Math.round(((completedCount + runningCount * 0.45) / totalAgents) * 85) + 10);
  } else if (runState === 'PLANNING' || runState === 'RUNNING') {
    progressPct = 15;
  } else if (effectiveTeam.status === 'approved') {
    progressPct = 10;
  }
  if ($('#workflow-live-badge')) {
    $('#workflow-live-badge').textContent = '实时进度 ' + progressPct + '% · 点击节点可直接微调';
  }

  const mainBadge = runState === 'PLANNING'
    ? '<span class="workflow-stage-badge status-running">正在拆解与制定契约 · ' + progressPct + '%</span>'
    : '<span class="workflow-stage-badge status-completed">统一开发原则已锁定 · 总进度 ' + progressPct + '%</span>';
  const reviewLabel = effectiveTeam.review_mode === 'open-code-review' ? 'Open Code Review 审查' : (effectiveTeam.review_mode === 'internal' ? '结构化审查' : '必要检查与风险复核');
  const parallelLimit = Math.min(effectiveTeam.agents.length, Number(effectiveTeam.max_concurrency || dshSettings?.subagent?.maxConcurrent || 4));
  const reviewBadge = runState === 'SUCCEEDED'
    ? '<span class="workflow-stage-badge status-completed">' + reviewLabel + '与主 Agent 合并完成 · 100%</span>'
    : (hasMergeEvent || runState === 'FINAL_VERIFY'
      ? '<span class="workflow-stage-badge status-running">' + reviewLabel + '与合流进行中 · ' + progressPct + '%</span>'
      : '<span class="workflow-stage-badge status-ready">等待并行子任务汇合 · ' + completedCount + '/' + totalAgents + ' 完成</span>');

  const nodes = effectiveTeam.agents.map((agent, index) => {
    const modelName = agent.model_profile_id ? (modelDisplayName(profiles.find((p) => p.id === agent.model_profile_id)) || '模型配置不可用') : ('跟随主模型 · ' + (modelDisplayName(profiles.find((p) => p.id === $('#chat-model-select').value)) || '默认'));
    const owned = (agent.owned_paths || []).length ? '范围: ' + agent.owned_paths.join(', ') : '范围: 全局工作区';
    const st = statuses[index];
    const nodePct = st.state === 'completed' ? '100%' : (st.state === 'running' ? '50%' : '0%');
    return '<article class="workflow-node node-' + st.state + '" data-workflow-agent-index="' + index + '" title="点击操作此子 Agent 节点">' +
      '<div class="workflow-node-top">' +
        '<span class="workflow-node-index">#' + (index + 1) + '</span>' +
        '<span class="workflow-node-status status-' + st.state + '">' + escapeHtml(st.label + ' · ' + nodePct) + '</span>' +
      '</div>' +
      '<strong>' + escapeHtml(agent.name) + '</strong>' +
      '<small>' + escapeHtml(agent.responsibility) + '</small>' +
      '<span class="node-paths">' + escapeHtml(owned) + '</span>' +
      '<em>模型: ' + escapeHtml(modelName) + '</em>' +
      '</article>';
  }).join('');

  const flowHtml =
    '<div class="mindmap-flow" style="transform: scale(' + modalWorkflowZoom + '); transform-origin: top center;">' +
      '<div class="mindmap-stage stage-input"><strong>任务输入</strong><small>' + escapeHtml(reqSummary) + '</small></div>' +
      '<div class="mindmap-stem"></div>' +
      '<div class="mindmap-stage stage-main"><strong>' + icon('sparkle') + ' 主 Agent · 统一开发原则 · 并发调度</strong>' + mainBadge + '<small>模型: ' + escapeHtml(mainModel) + '</small></div>' +
      buildMindmapSvg(effectiveTeam.agents.length, false) +
      '<div class="workflow-agents">' + nodes + '</div>' +
      buildMindmapSvg(effectiveTeam.agents.length, true) +
      '<div class="mindmap-stage stage-review"><strong>' + reviewLabel + ' · 主 Agent 合并改动</strong>' + reviewBadge + '<small>最多并发: ' + escapeHtml(parallelLimit) + ' 个子 Agent</small></div>' +
    '</div>';

  if (modalTarget) modalTarget.innerHTML = flowHtml;
  if (sidebarTarget) {
    sidebarTarget.innerHTML = flowHtml.replace('style="transform: scale(' + modalWorkflowZoom + '); transform-origin: top center;"', '');
  }
}

function renderModalTeamEditor() {
  if (!team) return;
  const conc = Number(team.max_concurrency || 2);
  if ([1, 2, 3, 4].includes(conc)) {
    $('#modal-team-concurrency').value = String(conc);
    $('#modal-team-concurrency-custom').hidden = true;
  } else {
    $('#modal-team-concurrency').value = 'custom';
    $('#modal-team-concurrency-custom').hidden = false;
    $('#modal-team-concurrency-custom').value = String(conc);
  }
  refreshSelectMenu($('#modal-team-concurrency'));
  $('#modal-agent-list').innerHTML = (team.agents || []).map(modalAgentCard).join('');
}

function syncModalEditorToTeam() {
  if (!team) return;
  const rawConc = $('#modal-team-concurrency').value === 'custom'
    ? Number($('#modal-team-concurrency-custom').value)
    : Number($('#modal-team-concurrency').value);
  team.max_concurrency = Math.max(1, Math.min(64, rawConc || 2));
  const cards = [...document.querySelectorAll('[data-modal-agent-index]')];
  team.agents = cards.map((card, idx) => {
    const existing = team.agents[idx] || {};
    return {
      ...existing,
      id: existing.id || ('agent_' + (idx + 1)),
      name: card.querySelector('.modal-agent-name').value.trim() || ('子 Agent ' + (idx + 1)),
      responsibility: card.querySelector('.modal-agent-responsibility').value.trim() || '负责模块实现与测试',
      system_prompt: card.querySelector('.modal-agent-system-prompt').value,
      model_profile_id: card.querySelector('.modal-agent-profile').value || '',
      owned_paths: card.querySelector('.modal-agent-paths').value.split(',').map((s) => s.trim()).filter(Boolean),
      locked: Boolean(existing.locked),
    };
  });
  renderTeam();
  teamDirty = true;
  renderWorkflowMindmap(team);
}

function openTeamReview(options = {}) {
  modalWorkflowZoom = 1;
  renderWorkflowMindmap(team);
  renderModalTeamEditor();
  const hasTeam = Boolean(currentProjectId() && (team?.agents?.length || currentActiveRun?.tasks?.length));
  $('#team-review-editor').hidden = !hasTeam || !options.openEditor;
  $('#team-review-inline-edit').textContent = $('#team-review-editor').hidden ? '在窗口内编辑节点' : '收起窗口内编辑';
  if (options.fullscreen) {
    $('#team-review-dialog')?.classList.add('workflow-fullscreen');
  }
  if (!$('#team-review-dialog').open) $('#team-review-dialog').showModal();
}

function handleWorkflowNodeClick(event) {
  const node = event.target.closest('[data-workflow-agent-index]');
  if (!node) return;
  const idx = Number(node.dataset.workflowAgentIndex);
  if (!$('#team-review-dialog').open) {
    openTeamReview({ openEditor: true });
  } else if ($('#team-review-editor').hidden) {
    $('#team-review-editor').hidden = false;
    $('#team-review-inline-edit').textContent = '收起窗口内编辑';
    renderModalTeamEditor();
  }
  const targetCard = document.querySelector('[data-modal-agent-index="' + idx + '"]');
  if (targetCard) {
    targetCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
    targetCard.querySelector('.modal-agent-name')?.focus();
  }
}

$('#sidebar-team-workflow')?.addEventListener('click', handleWorkflowNodeClick);
$('#team-workflow')?.addEventListener('click', handleWorkflowNodeClick);
$('#workflow-fullscreen-open')?.addEventListener('click', () => openTeamReview({ fullscreen: true }));
$('#runs-open-workflow')?.addEventListener('click', () => openTeamReview({ fullscreen: true }));
$('#modal-workflow-zoom-in')?.addEventListener('click', () => {
  modalWorkflowZoom = Math.min(1.6, Number((modalWorkflowZoom + 0.15).toFixed(2)));
  if ($('#modal-workflow-zoom-label')) $('#modal-workflow-zoom-label').textContent = Math.round(modalWorkflowZoom * 100) + '%';
  renderWorkflowMindmap(team);
});
$('#modal-workflow-zoom-out')?.addEventListener('click', () => {
  modalWorkflowZoom = Math.max(0.6, Number((modalWorkflowZoom - 0.15).toFixed(2)));
  if ($('#modal-workflow-zoom-label')) $('#modal-workflow-zoom-label').textContent = Math.round(modalWorkflowZoom * 100) + '%';
  renderWorkflowMindmap(team);
});
$('#modal-workflow-zoom-reset')?.addEventListener('click', () => {
  modalWorkflowZoom = 1;
  if ($('#modal-workflow-zoom-label')) $('#modal-workflow-zoom-label').textContent = '100%';
  renderWorkflowMindmap(team);
});
$('#modal-workflow-fullscreen-toggle')?.addEventListener('click', () => {
  $('#team-review-dialog')?.classList.toggle('workflow-fullscreen');
});
$('#team-review-close').addEventListener('click', () => {
  $('#team-review-dialog').classList.remove('workflow-fullscreen');
  $('#team-review-dialog').close();
});
$('#team-review-inline-edit').addEventListener('click', () => {
  const editor = $('#team-review-editor');
  editor.hidden = !editor.hidden;
  $('#team-review-inline-edit').textContent = editor.hidden ? '在窗口内编辑节点' : '收起窗口内编辑';
  if (!editor.hidden) renderModalTeamEditor();
});
$('#team-review-editor').addEventListener('input', () => {
  $('#modal-team-concurrency-custom').hidden = $('#modal-team-concurrency').value !== 'custom';
  syncModalEditorToTeam();
});
$('#team-review-editor').addEventListener('change', () => {
  $('#modal-team-concurrency-custom').hidden = $('#modal-team-concurrency').value !== 'custom';
  syncModalEditorToTeam();
});
$('#modal-add-agent').addEventListener('click', () => {
  if (!team) return;
  const idx = (team.agents || []).length + 1;
  team.agents.push({
    id: 'agent_' + idx,
    name: '子 Agent ' + idx,
    responsibility: '负责独立模块开发与单元验证',
    model_profile_id: team.main_profile_id || $('#main-profile').value,
    owned_paths: [],
    locked: false,
  });
  renderModalTeamEditor();
  renderTeam();
  teamDirty = true;
  renderWorkflowMindmap(team);
});
$('#modal-agent-list').addEventListener('click', (event) => {
  const removeBtn = event.target.closest('[data-modal-remove-agent]');
  if (!removeBtn || !team) return;
  const index = Number(removeBtn.dataset.modalRemoveAgent);
  if (team.agents.length <= 1) return toast('团队至少需要保留 1 个子 Agent。', true);
  team.agents.splice(index, 1);
  renderModalTeamEditor();
  renderTeam();
  teamDirty = true;
  renderWorkflowMindmap(team);
});
$('#team-review-edit')?.addEventListener('click', () => {
  $('#team-review-dialog').close();
  showLeftTool('team');
  const adv = $('#team-advanced-details');
  if (adv) adv.open = true;
});

let suppressAbortBanner = false;
let activeTurnSequence = 0;
let activeTurnStartedAt = 0;

async function confirmAndStartTeamExecution() {
  const versionBeforeEdit = team?.version;
  const projectId = currentProjectId();
  if (!projectId) throw new Error('请先选择或创建项目');
  if (!conversationId) {
    await createConversation(projectId);
  }
  if ($('#team-review-dialog')?.open && !$('#team-review-editor').hidden) {
    syncModalEditorToTeam();
  }
  if (teamDirty || !team?.version) await saveTeam();
  if (team.status !== 'approved') {
    team = await api('/projects/' + encodeURIComponent(projectId) + '/team/approve', 'POST', {
      conversation_id: conversationId || null,
      version: team.version,
    });
  }
  renderTeam();
  document.querySelectorAll('.plan-approval-card').forEach((card) => {
    if (Number(card.dataset.teamVersion) === Number(versionBeforeEdit)) createOrUpdatePlanApprovalCard(card, team);
    else card.querySelector('[data-inline-approve-plan]')?.setAttribute('disabled', '');
  });
  if ($('#team-review-dialog')?.open) {
    $('#team-review-dialog').classList.remove('workflow-fullscreen');
    $('#team-review-dialog').close();
  }
  if ($('#agent-select') && $('#agent-select').value === 'main_only') {
    $('#agent-select').value = '';
    refreshSelectMenu($('#agent-select'));
    syncTrackedSelectorLabels();
  }
  renderWorkflowMindmap(team);
  setFeedback('#team-feedback', '子 Agent 团队已确认并启动并行执行。');
  toast('已确认子 Agent 分工，开始执行');
  if (busy && activeChatAbortController) {
    suppressAbortBanner = true;
    activeChatAbortController.abort();
    await new Promise((resolve) => setTimeout(resolve, 60));
    busy = false;
  }
  await send('已确认子 Agent 分工，立即并行执行', [], { executeTeamNow: true });
  return team;
}

$('#team-review-approve').addEventListener('click', async () => {
  try {
    await confirmAndStartTeamExecution();
  } catch (error) { toast(error.message, true); }
});
$('#team-review-start-now')?.addEventListener('click', async () => {
  try {
    await confirmAndStartTeamExecution();
  } catch (error) { toast(error.message, true); }
});

function renderTeam() {
  const projectId = currentProjectId();
  $('#team-status').textContent = (team && team.agents?.length)
    ? '版本 ' + team.version + ' · ' + (team.status === 'approved' ? '当前对话已确认' : '待确认')
    : (projectId ? '首轮对话组建团队' : '选择项目开始');
  $('#team-requirement').value = team?.requirement || '';
  const concurrency = team?.max_concurrency || Number(dshSettings?.subagent?.maxConcurrent || 2);
  if ([1, 2, 3, 4].includes(concurrency)) {
    $('#team-concurrency').value = String(concurrency);
    $('#team-concurrency-custom').hidden = true;
  } else {
    $('#team-concurrency').value = 'custom';
    $('#team-concurrency-custom').hidden = false;
    $('#team-concurrency-custom').value = String(concurrency);
  }
  if (team?.main_profile_id) $('#main-profile').value = team.main_profile_id;
  $('#review-profile').value = team?.review_profile_id || '';
  $('#review-mode').value = team?.review_mode || dshSettings?.review?.defaultMode || 'adaptive';
  $('#agent-list').innerHTML = team?.agents?.map(agentCard).join('') || '<p class="empty">当前对话暂无子 Agent。首轮发送需求将自动组建。</p>';
  refreshSelectMenus();
  renderAgentSelector();
  renderWorkflowMindmap(team);
  teamDirty = false;
}

function collectTeam() {
  const agents = [...document.querySelectorAll('[data-agent]')].map((card) => ({
    id: card.querySelector('.agent-id').value.trim(),
    name: card.querySelector('.agent-name').value.trim(),
    responsibility: card.querySelector('.agent-responsibility').value.trim(),
    system_prompt: card.querySelector('.agent-system-prompt').value,
    model_profile_id: card.querySelector('.agent-profile').value,
    owned_paths: card.querySelector('.agent-paths').value.split(',').map((v) => v.trim()).filter(Boolean),
    locked: card.querySelector('.agent-locked').checked,
  }));
  return {
    requirement: $('#team-requirement').value.trim(),
    main_profile_id: $('#main-profile').value,
    review_profile_id: $('#review-profile').value || null,
    review_mode: $('#review-mode').value,
    max_concurrency: Number($('#team-concurrency').value === 'custom' ? $('#team-concurrency-custom').value : $('#team-concurrency').value),
    agents,
    version: team?.version ?? null,
    conversation_id: conversationId || null,
  };
}

async function loadTeam() {
  const projectId = currentProjectId();
  team = null;
  if (projectId && conversationId) {
    try {
      const loaded = await api('/projects/' + encodeURIComponent(projectId) + '/team?conversation_id=' + encodeURIComponent(conversationId));
      team = (loaded && Array.isArray(loaded.agents) && loaded.agents.length > 0) ? loaded : null;
    } catch (error) {
      if (!error.message.includes('Unknown team')) setFeedback('#team-feedback', error.message, true);
    }
  }
  if (!projectId && conversationId) {
    team = conversations.find(item => item.id === conversationId)?.team || null;
  }
  renderTeam();
  await loadRuns();
  await loadSkills();
}

async function loadSkills() {
  const projectId = currentProjectId();
  try {
    const skills = await api('/skills' + (projectId ? '?project_id=' + encodeURIComponent(projectId) : ''));
    $('#skill-list').innerHTML = skills.map((skill) =>
      '<div class="model-card"><strong>' + escapeHtml(skill.name) + '</strong><small>' +
      escapeHtml(skill.scope) + '</small><details class="skill-description"><summary><span>' + escapeHtml(skill.description) + '</span></summary></details></div>'
    ).join('') || '<p class="empty">当前没有技能。可在项目内添加 .agents/skills/名称/SKILL.md，或使用下方表单。</p>';
  } catch (error) { setFeedback('#skill-feedback', error.message, true); }
}

async function loadMcpServers() {
  try {
    const projectId = currentProjectId();
    const [userServers, dshData] = await Promise.all([
      api('/mcp-servers?include_builtin=true' + (projectId ? '&project_id=' + encodeURIComponent(projectId) : '')),
      api('/dsh/plugins' + (projectId ? '?project_id=' + encodeURIComponent(projectId) : '')),
    ]);
    const allServers = dshData?.mcp_servers || userServers;
    $('#mcp-list').innerHTML = allServers.map((server) => {
      const isBuiltin = Boolean(server.builtin || server.id === 'builtin-masp-workspace');
      const isProj = String(server.id || '').startsWith('proj-mcp-');
      const cmdDesc = isBuiltin
        ? '内置工作区服务 · 支持文件浏览、代码编辑、全局搜索、网页搜索与终端命令'
        : (server.transport === 'http' ? server.url : (server.command + ' ' + (server.args || []).join(' ')));
      return '<div class="model-card" data-mcp="' + escapeHtml(server.id) + '">' +
        '<div class="dsh-plugin-head"><strong>' + escapeHtml(server.name) + '</strong>' +
        '<span class="dsh-plugin-badge ' + (isBuiltin ? 'official' : '') + '">' +
        (isBuiltin ? '内置 MCP' : (isProj ? '项目 .mcp.json' : '外部 MCP')) + '</span></div>' +
        '<small>' + escapeHtml(cmdDesc) + '<br>' + (server.enabled ? '已启用 Agent 调用' : '未启用') + (server.last_error ? '<br>' + escapeHtml('连接失败：' + server.last_error) : '') + '</small>' +
        '<div class="row-actions">' +
        '<button type="button" data-mcp-probe="' + escapeHtml(server.id) + '">检测工具</button>' +
        (isBuiltin
          ? '<button type="button" data-dsh-toggle="@masp/workspace-mcp" data-dsh-enabled="' + (!server.enabled) + '">' + (server.enabled ? '停用' : '启用') + '</button>'
          : (isProj ? '' :
            '<button type="button" data-mcp-toggle="' + escapeHtml(server.id) + '">' + (server.enabled ? '停用' : '启用') + '</button>' +
            '<button type="button" data-mcp-delete="' + escapeHtml(server.id) + '">删除</button>')) +
        '</div>' +
        '<p class="feedback mcp-card-feedback" data-mcp-result="' + escapeHtml(server.id) + '" role="status"></p>' +
        '</div>';
    }).join('') || '<p class="empty">还没有 MCP 服务。</p>';
    window.maspMcpServers = userServers;
  } catch (error) { setFeedback('#mcp-feedback', error.message, true); }
}

function renderDshPluginInventory() {
  if (!dshPluginInventory) return;
  const official = dshPluginInventory.official || [];
  const installed = dshPluginInventory.installed || [];
  const mcpList = dshPluginInventory.mcp_servers || [];
  const skills = dshPluginInventory.skills || [];

  const renderCard = (item, badgeText, isOfficial = false) => {
    const comps = (item.components || []).map((c) =>
      '<span class="dsh-component-chip">' + escapeHtml(c.type + ': ' + c.name) + '</span>'
    ).join('');
    const probeBtn = item.server_id
      ? '<button type="button" data-dsh-probe-mcp="' + escapeHtml(item.server_id) + '">检测工具</button>'
      : '';
    const deleteBtn = (!isOfficial && item.id && String(item.id).startsWith('bundle-'))
      ? '<button type="button" data-dsh-delete-bundle="' + escapeHtml(item.id) + '">移除</button>'
      : '';
    return '<div class="dsh-plugin-card" data-dsh-card="' + escapeHtml(item.id) + '">' +
      '<div class="dsh-plugin-head"><strong>' + escapeHtml(item.name) + '</strong>' +
      '<span class="dsh-plugin-badge ' + (isOfficial ? 'official' : '') + '">' + escapeHtml(badgeText) + '</span></div>' +
      '<small>' + escapeHtml(item.description || '') + '</small>' +
      (comps ? '<details class="plugin-component-details" data-plugin-fold="' + escapeHtml(item.id) + '"><summary>' + translateUiText('组件') + ' (' + (item.components || []).length + ')</summary><div class="dsh-components">' + comps + '</div></details>' : '') +
      '<div class="row-actions">' +
        '<button type="button" data-extension-detail="' + escapeHtml(item.id) + '">详情与配置</button>' + probeBtn +
        ('<button type="button" role="switch" aria-checked="' + Boolean(item.enabled) + '" class="extension-switch" data-dsh-toggle="' + escapeHtml(item.id) + '" data-dsh-enabled="' + (!item.enabled) + '" aria-label="' + escapeHtml(item.name) + '">' + (item.enabled ? '已启用' : '已停用') + '</button>') +
        deleteBtn +
      '</div>' +
      (item.server_id ? '<p class="feedback plugin-card-feedback" data-dsh-probe-result="' + escapeHtml(item.server_id) + '" role="status"></p>' : '') +
      '</div>';
  };

  let html = '';
  if (activePluginTab === 'all' || activePluginTab === 'official') {
    html += official.map((item) => renderCard(item, '内置功能', true)).join('');
  }
  if (activePluginTab === 'all' || activePluginTab === 'installed') {
    html += installed.map((item) => renderCard(item, item.kind === 'json-tool' ? '工具插件' : '已安装扩展', false)).join('');
  }
  if (activePluginTab === 'all' || activePluginTab === 'mcp') {
    html += mcpList.filter((m) => !m.builtin).map((m) =>
      '<div class="dsh-plugin-card"><div class="dsh-plugin-head"><strong>' + escapeHtml(m.name) + '</strong><span class="dsh-plugin-badge">MCP 服务</span></div>' +
      '<small>' + escapeHtml(m.transport === 'http' ? m.url : (m.command + ' ' + (m.args || []).join(' '))) + '</small>' +
      '<div class="row-actions"><button type="button" data-dsh-probe-mcp="' + escapeHtml(m.id) + '">检测工具</button></div>' +
      '<p class="feedback plugin-card-feedback" data-dsh-probe-result="' + escapeHtml(m.id) + '" role="status"></p></div>'
    ).join('');
  }
  if (activePluginTab === 'all' || activePluginTab === 'skills') {
    html += '<details class="plugin-skill-details" data-plugin-fold="skills"' + (activePluginTab === 'skills' ? ' open' : '') + '><summary>' + translateUiText('技能') + ' (' + skills.length + ')</summary>' + skills.map((s) =>
      '<div class="dsh-plugin-card"><div class="dsh-plugin-head"><strong>' + escapeHtml(s.name) + '</strong><span class="dsh-plugin-badge">SKILL.md</span></div>' +
      '<small>' + escapeHtml(s.scope + ' · ' + s.description) + '</small></div>'
    ).join('') + '</details>';
  }
  if ($('#dsh-plugin-overview')) {
    $('#dsh-plugin-overview').innerHTML = html || '<p class="empty">当前分类下暂无插件。</p>';
  }
  if ($('#settings-plugin-inventory')) {
    const allCards = [
      ...official.map((item) => renderCard(item, '内置功能', true)),
      ...installed.map((item) => renderCard(item, item.kind === 'json-tool' ? '工具插件' : '已安装扩展', false)),
    ].join('');
    $('#settings-plugin-inventory').innerHTML = allCards || '<p class="empty">暂无已加载插件。</p>';
  }
  document.querySelectorAll('details[data-plugin-fold]').forEach(detail => {
    const key = 'micro-multi-plugin-fold:' + detail.dataset.pluginFold;
    try { const saved = sessionStorage.getItem(key); if (saved !== null) detail.open = saved === 'true'; } catch (_) {}
    detail.addEventListener('toggle', () => { try { sessionStorage.setItem(key, String(detail.open)); } catch (_) {} });
  });

}

let extensionRefreshPending = false;
let extensionRefreshRunning = false;
function scheduleExtensionRefresh() {
  extensionRefreshPending = true;
  if (extensionRefreshRunning) return;
  extensionRefreshRunning = true;
  void (async () => {
    while (extensionRefreshPending) {
      extensionRefreshPending = false;
      await Promise.allSettled([loadPlugins(), loadMcpServers(), loadSkills()]);
    }
  })().finally(() => { extensionRefreshRunning = false; });
}


let conversationPluginEpoch=0;
const conversationPluginMounts=new Map();
let conversationPluginRefresh=Promise.resolve();
function pluginSelectedModel(){
  const profile=profiles.find(item=>item.id===$('#chat-model-select').value);
  if(!profile)return null;
  try{const wire=JSON.parse(profile.model);if(Array.isArray(wire)&&wire.length===2)return {provider:wire[0],model:wire[1]};}catch{}
  return {provider:profile.provider||'micro-multi',model:profile.model};
}
async function importPluginClient(id,revision){
  const url='/api/dsh/plugins/'+encodeURIComponent(id)+'/surface/client.js?revision='+encodeURIComponent(revision||'');
  try{return await import(url);}catch(error){
    // Diagnose a failed build without downloading every successful module twice.
    const response=await fetch(url);
    if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(detail||'插件客户端 HTTP '+response.status);}
    await response.body?.cancel();
    // Browsers retain failed module imports. A fresh URL permits recovery after
    // transient transport or build failures, with only one retry per attempt.
    return import(url+'&retry='+Date.now());
  }
}
function refreshConversationPlugins(){
  const epoch=++conversationPluginEpoch;
  const work=conversationPluginRefresh.catch(()=>{}).then(()=>mountConversationPlugins(epoch));
  conversationPluginRefresh=work;
  return work;
}
async function mountConversationPlugins(epoch){
  if(epoch!==conversationPluginEpoch)return;
  const installed=dshPluginInventory?.installed||[];
  const wanted=new Map(installed.filter(item=>item.enabled&&item.runtime==='native-cordis-host').map(item=>[item.id,item]));
  for(const [id,entry] of conversationPluginMounts){
    const item=wanted.get(id);
    if(!item||entry.key!==conversationId+'|'+item.updated_at){await entry.dispose();entry.root.remove();entry.style.remove();conversationPluginMounts.delete(id);}
  }
  for(const [id,item] of wanted){
    if(epoch!==conversationPluginEpoch)return;
    if(conversationPluginMounts.has(id))continue;
    let root,style,dispose;
    try{
      const surface=await api('/dsh/plugins/'+encodeURIComponent(id)+'/surface');
      if(!surface.available||epoch!==conversationPluginEpoch)continue;
      const client=await importPluginClient(id,surface.client_revision||item.updated_at);
      if(epoch!==conversationPluginEpoch)return;
      root=document.createElement('div');$('#plugin-runtime-roots').append(root);
      style=document.createElement('link');style.rel='stylesheet';style.href='/api/dsh/plugins/'+encodeURIComponent(id)+'/surface/client.css?revision='+encodeURIComponent(surface.client_revision||item.updated_at||'');document.head.append(style);
      const targets={'conversation.input.dock':$('#plugin-input-dock'),'conversation.input.overlay':$('#plugin-input-overlay'),'conversation.input.activity':$('#plugin-input-activity'),'conversation.input.plan':$('#plugin-input-plan'),'conversation.input.permission':$('#plugin-input-permission'),'conversation.session.header.actions':$('#plugin-header-actions'),'conversation.session.header.utilities':$('#plugin-header-actions'),'conversation.session.header.corner':$('#plugin-header-actions'),'conversation.input.model':$('#plugin-model-options'),'conversation.input.left':$('#plugin-composer-left'),'conversation.input.right':$('#plugin-composer-right'),'conversation.composer.dock':$('#plugin-composer-dock'),'shell.overlay':$('#plugin-overlay-root'),'shell.bottom':$('#plugin-shell-bottom'),'shell.leading':$('#plugin-shell-leading'),'conversation.header.actions':$('#plugin-header-actions')};
      dispose=await client.mount(root,{rpcUrl:'/api/dsh/plugins/'+encodeURIComponent(id)+'/rpc',sessionId:conversationId,mode:'conversation',targets,modelOptions:surface.provides_models,model:pluginSelectedModel});
      if(epoch!==conversationPluginEpoch){await dispose();root.remove();style.remove();return;}
      conversationPluginMounts.set(id,{dispose,root,style,key:conversationId+'|'+item.updated_at});
    }catch(error){await dispose?.();root?.remove();style?.remove();console.error('插件前端加载失败',item.name,error);}
  }
}

async function loadPlugins() {
  try {
    const projectId = currentProjectId();
    const [plugins, dshData] = await Promise.all([
      api('/plugins'),
      api('/dsh/plugins' + (projectId ? '?project_id=' + encodeURIComponent(projectId) : '')),
    ]);
    dshPluginInventory = dshData;
    renderDshPluginInventory();
    $('#plugin-list').innerHTML = plugins.map((plugin) =>
      '<div class="model-card"><strong>' + escapeHtml(plugin.name) + '</strong><small>' +
      escapeHtml(plugin.description) + '<br>' + escapeHtml(plugin.command) +
      ' · ' + (plugin.enabled ? '已启用' : '未启用') +
      '</small><div class="row-actions"><button type="button" data-plugin-toggle="' +
      escapeHtml(plugin.id) + '">' + (plugin.enabled ? '停用' : '启用') +
      '</button><button type="button" data-plugin-delete="' + escapeHtml(plugin.id) +
      '">删除</button></div></div>'
    ).join('');
    window.maspPlugins = plugins;
    void refreshConversationPlugins();
  } catch (error) { setFeedback('#plugin-feedback', error.message, true); }
}

async function saveTeam() {
  const projectId = currentProjectId();
  if (!projectId) throw new Error('先创建并选择项目');
  if (!conversationId) {
    await createConversation(projectId);
  }
  team = await api('/projects/' + encodeURIComponent(projectId) + '/team', 'PUT', collectTeam());
  $('#chat-model-select').value=team.main_profile_id;refreshSelectMenu($('#chat-model-select'));
  const conversation=conversations.find(item=>item.id===conversationId);if(conversation)conversation.model_profile_id=team.main_profile_id;
  renderTeam();
  setFeedback('#team-feedback', '团队配置已保存，可继续微调或点击确认开始执行。');
  return team;
}

async function loadRuns() {
  const projectId = currentProjectId();
  currentActiveRun = null;
  currentRunEvents = [];
  if (!projectId || !conversationId) {
    selectedRunId = null;
    if ($('#run-detail')) $('#run-detail').innerHTML = '';
    $('#run-list').innerHTML = '<p class="empty">' + (projectId ? '当前新对话暂无多 Agent 执行记录。发送首轮需求后自动记录。' : '选择项目后查看当前对话的多 Agent 执行记录。') + '</p>';
    renderWorkflowMindmap(team);
    return;
  }
  try {
    const runs = await api('/projects/' + encodeURIComponent(projectId) + '/runs?conversation_id=' + encodeURIComponent(conversationId));
    $('#run-list').innerHTML = runs.map((run, idx) => {
      const st = formatRunStateInfo(run.state);
      const reqText = (run.request?.requirement || '多 Agent 协作任务').slice(0, 80);
      return '<button class="run-card wide" data-run="' + escapeHtml(run.id) + '">' +
        '<div class="run-summary-top">' +
          '<strong>第 ' + (runs.length - idx) + ' 轮协作</strong>' +
          '<span class="run-status-pill ' + st.cls + '">' + escapeHtml(st.label) + '</span>' +
        '</div>' +
        '<small>' + escapeHtml(reqText) + '</small>' +
        '<span>查看子 Agent 进度、代码验证与改动 →</span></button>';
    }).join('') || '<p class="empty">当前对话暂无多 Agent 执行记录。</p>';
    if (selectedRunId && runs.some((r) => r.id === selectedRunId)) {
      await showRun(selectedRunId);
    } else if (runs[0]) {
      selectedRunId = runs[0].id;
      await showRun(runs[0].id);
    } else {
      selectedRunId = null;
      if ($('#run-detail')) $('#run-detail').innerHTML = '';
      renderWorkflowMindmap(team);
    }
  } catch (error) { $('#run-list').textContent = error.message; }
}

async function showRun(id) {
  selectedRunId = id;
  const [run, events] = await Promise.all([
    api('/runs/' + encodeURIComponent(id)),
    api('/runs/' + encodeURIComponent(id) + '/events'),
  ]);
  currentActiveRun = run;
  currentRunEvents = events;
  renderWorkflowMindmap(team);

  const st = formatRunStateInfo(run.state);
  const friendlyError = formatFriendlyRunError(run.error);
  const tasksHtml = (run.tasks || []).map((task, idx) => {
    const taskSt = formatRunStateInfo(task.state);
    const title = task.title || task.spec?.title || ('子任务 #' + (idx + 1));
    const owner = task.agent_id || task.spec?.owner_role || ('子 Agent ' + (idx + 1));
    const desc = task.spec?.description || '';
    return '<div class="run-task-card">' +
      '<div class="run-task-head">' +
        '<strong>' + escapeHtml(title) + '</strong>' +
        '<span class="run-status-pill ' + taskSt.cls + '">' + escapeHtml(taskSt.label) + '</span>' +
      '</div>' +
      '<small class="muted">负责角色: ' + escapeHtml(owner) + (desc ? ' · ' + escapeHtml(desc.slice(0, 60)) : '') + '</small>' +
    '</div>';
  }).join('');

  const uniqueAgentsMap = new Map();
  for (const agent of (run.agents || [])) {
    const key = String(agent.role || '子 Agent');
    uniqueAgentsMap.set(key, agent);
  }
  const agentsHtml = [...uniqueAgentsMap.values()].map((agent) => {
    const agSt = formatRunStateInfo(agent.state);
    return '<div class="run-task-card">' +
      '<div class="run-task-head">' +
        '<strong>' + escapeHtml(agent.role || '子 Agent') + '</strong>' +
        '<span class="run-status-pill ' + agSt.cls + '">' + escapeHtml(agSt.label) + '</span>' +
      '</div>' +
      '<small class="muted">使用模型: ' + escapeHtml(agent.model || '默认主模型') + '</small>' +
    '</div>';
  }).join('');

  const checksHtml = (run.final_checks || []).map((check) => {
    const passed = check.passed || check.status === 'passed' || check.status === '通过';
    return '<div class="run-task-card">' +
      '<div class="run-task-head">' +
        '<strong>' + escapeHtml(check.command || check.name || '工作区语法与契约检查') + '</strong>' +
        '<span class="run-status-pill ' + (passed ? 'state-succeeded' : 'state-failed') + '">' + (passed ? '验证通过' : '需关注') + '</span>' +
      '</div>' +
    '</div>';
  }).join('');

  const recentEventsHtml = events.slice(-20).map((item) => {
    const timeStr = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : '';
    return '<div class="run-event-row">' +
      '<span>' + escapeHtml(formatRunEventLabel(item)) + '</span>' +
      '<span class="muted">' + escapeHtml(timeStr) + '</span>' +
    '</div>';
  }).join('');

  const terminal = ['SUCCEEDED', 'FAILED', 'BLOCKED', 'CANCELLED', 'HUMAN_REVIEW_REQUIRED'].includes(run.state);
  if (terminal && runStream) {
    runStream.close();
    runStream = null;
    loadWorkspaceFiles(workspaceFolder).catch(() => {});
    loadWorkspaceChanges().catch(() => {});
  }
  const controls = terminal
    ? '<button class="primary" data-run-action="retry">重新运行此任务</button>'
    : (run.control === 'paused'
      ? '<button class="primary" data-run-action="resume">继续执行</button><button data-run-action="cancel">中止任务</button>'
      : (run.control === 'cancelling'
        ? '<span class="muted">正在安全中止任务…</span>'
        : '<button data-run-action="pause">暂停</button><button data-run-action="cancel">中止任务</button>'));

  $('#run-detail').innerHTML =
    '<div class="run-detail">' +
      '<div class="run-summary-card">' +
        '<div class="run-summary-top">' +
          '<strong>多 Agent 协作执行状态</strong>' +
          '<span class="run-status-pill ' + st.cls + '">' + escapeHtml(st.label) + '</span>' +
        '</div>' +
        '<p>' + escapeHtml(run.request?.requirement || '当前项目开发任务') + '</p>' +
        '<small class="muted">' + escapeHtml(st.desc) + '</small>' +
      '</div>' +
      (friendlyError ? '<div class="run-error-box">' + escapeHtml(friendlyError) + '</div>' : '') +
      '<div class="row-actions">' +
        controls +
        '<button type="button" data-followup="' + escapeHtml(run.id) + '">在对话中继续微调</button>' +
        (run.artifact_id ? '<a class="subtle-button" href="/api/artifacts/' + encodeURIComponent(run.artifact_id) + '/download">导出交付包</a>' : '') +
      '</div>' +
      '<div class="run-section-title">并行子任务分工 (' + (run.tasks || []).length + ')</div>' +
      '<div class="run-task-list">' + (tasksHtml || '<p class="empty">正在规划并分配子任务…</p>') + '</div>' +
      '<div class="run-section-title">参与协作的 Agent</div>' +
      '<div class="run-task-list">' + (agentsHtml || '<p class="empty">等待子 Agent 启动…</p>') + '</div>' +
    '</div>';
}

function watchRun(id) {
  if (runStream) runStream.close();
  runStream = new EventSource('/api/runs/' + encodeURIComponent(id) + '/stream');
  runStream.onmessage = () => { showRun(id).catch(() => {}); };
  runStream.addEventListener('complete', () => {
    if (runStream) {
      runStream.close();
      runStream = null;
    }
    loadRuns();
    loadWorkspaceFiles(workspaceFolder).catch(() => {});
    loadWorkspaceChanges().catch(() => {});
  });
  runStream.onerror = () => {
    if (runStream) {
      runStream.close();
      runStream = null;
    }
  };
}

function updateSendButtonState() {
  const btn = $('#send');
  if (btn) {
    btn.disabled = false;
    if (busy) {
      btn.classList.add('is-running');
      btn.title = '点击暂停并中止当前对话';
      btn.setAttribute('aria-label', '点击暂停并中止当前对话');
      btn.innerHTML = '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><rect x="3.8" y="3.8" width="8.4" height="8.4" rx="1.6" fill="currentColor"/></svg>';
    } else {
      btn.classList.remove('is-running');
      btn.title = '发送';
      btn.setAttribute('aria-label', '发送');
      btn.innerHTML = '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13V3M4.5 6.5 8 3l3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    }
  }
  updateHeaderRunStatus();
}

async function abortActiveChatTurn() {
  if (!busy) return;
  userAbortedCurrentTurn = true;
  if (conversationId) {
    api('/conversations/' + encodeURIComponent(conversationId) + '/cancel', 'POST', {}).catch(() => {});
  }
  if (selectedRunId && currentActiveRun && !['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(currentActiveRun.state)) {
    api('/runs/' + encodeURIComponent(selectedRunId) + '/cancel', 'POST', {}).catch(() => {});
  }
  if (activeChatAbortController) {
    try { activeChatAbortController.abort(); } catch { /* ignore */ }
  }
}

function formatTokenCount(n) {
  const num = Number(n || 0);
  if (num >= 1000) return (num / 1000).toFixed(num >= 10000 ? 0 : 1) + 'K';
  return String(num);
}

let lastContextUsedTokens = 0;

async function refreshContextUsage(usagePayload = null) {
  let data = usagePayload;
  if (!data) {
    if (!conversationId) {
      data = { used_tokens: 0, max_tokens: contextMaxTokens, percent: 0, message_count: 0 };
    } else {
      try {
        data = await api('/conversations/' + encodeURIComponent(conversationId) + '/context-usage?max_tokens=' + encodeURIComponent(contextMaxTokens));
      } catch {
        data = { used_tokens: lastContextUsedTokens, max_tokens: contextMaxTokens, percent: 0, message_count: 0 };
      }
    }
  }
  const used = Number(data.used_tokens ?? lastContextUsedTokens ?? 0);
  lastContextUsedTokens = used;
  const max = Number(contextMaxTokens || data.max_tokens || 64000);
  const pct = Math.min(100, Math.max(0, Number(max > 0 ? (used / max) * 100 : (data.percent ?? data.usage_percent ?? 0))));
  const circumference = 40.84;
  const offset = circumference - (pct / 100) * circumference;
  if ($('#context-ring-fg')) {
    $('#context-ring-fg').style.strokeDashoffset = String(offset.toFixed(2));
  }
  if ($('#context-usage-ring-fg')) {
    $('#context-usage-ring-fg').style.strokeDashoffset = String(offset.toFixed(2));
  }
  if ($('#context-usage-label')) {
    $('#context-usage-label').textContent = formatTokenCount(used) + ' / ' + formatTokenCount(max);
  }
  if ($('#context-usage-detail')) {
    $('#context-usage-detail').textContent = used.toLocaleString() + ' / ' + max.toLocaleString() + ' tokens · ' + pct.toFixed(1) + '%';
  }
  if ($('#context-usage-numbers')) {
    $('#context-usage-numbers').textContent = used.toLocaleString() + ' / ' + max.toLocaleString() + ' tokens';
  }
  if ($('#context-meter-fill')) {
    $('#context-meter-fill').style.width = pct + '%';
  }
  if ($('#context-usage-bar-fill')) {
    $('#context-usage-bar-fill').style.width = pct + '%';
  }
  if ($('#context-limit-select') && $('#context-limit-select').value !== String(max)) {
    $('#context-limit-select').value = String(max);
    refreshSelectMenu($('#context-limit-select'));
  }
}

let pendingApprovalRetry = null;
let approvalDecisionInFlight = false;
const toolApprovalQueue = [];
function openToolApprovalDialog(approvalData) {
  if (!approvalData?.approval_id || pendingApprovalRetry?.approval_id === approvalData.approval_id || toolApprovalQueue.some(a => a.approval_id === approvalData.approval_id)) return;
  toolApprovalQueue.push(approvalData);
  showNextToolApproval();
}
function showNextToolApproval() {
  if (pendingApprovalRetry || !toolApprovalQueue.length) return;
  pendingApprovalRetry = toolApprovalQueue.shift();
  const approval = pendingApprovalRetry;
  $('#tool-approval-reason').textContent = approval.reason || '需要用户确认本次操作';
  let argumentPreview = approval.arguments || '';
  try { argumentPreview = JSON.stringify(JSON.parse(argumentPreview || '{}'), null, 2); } catch {}
  $('#tool-approval-detail').textContent = approval.tool + '\n' + argumentPreview;
  $('#tool-approval-allow-files').hidden = approval.required_mode === 'commands';
  $('#tool-approval-allow-files').classList.toggle('primary', approval.required_mode !== 'commands');
  $('#tool-approval-allow-commands').hidden = approval.required_mode !== 'commands';
  if (!$('#tool-approval-dialog').open) $('#tool-approval-dialog').showModal();
}
async function decideToolApproval(allow, mode = 'files') {
  const approval = pendingApprovalRetry;
  if (!approval || approvalDecisionInFlight) return;
  approvalDecisionInFlight = true;
  try {
    await api('/conversations/' + encodeURIComponent(approval.conversation_id) + '/approvals/' + encodeURIComponent(approval.approval_id), 'POST', {allow, mode});
  } catch(error) {
    toast(error.message, true);
    if (error.status !== 409) return;
  } finally { approvalDecisionInFlight = false; }
  pendingApprovalRetry = null;
  $('#tool-approval-dialog').close();
  showNextToolApproval();
}
$('#tool-approval-reject').addEventListener('click', () => decideToolApproval(false));
$('#tool-approval-allow-files').addEventListener('click', () => decideToolApproval(true, 'files'));
$('#tool-approval-allow-commands').addEventListener('click', () => decideToolApproval(true, 'commands'));
$('#tool-approval-dialog').addEventListener('cancel', event => {event.preventDefault();decideToolApproval(false);});

let liveWatchGeneration = 0;
let liveWatchTimer = null;
let liveWatchOwnsBusy = false;
function stopLiveTurnWatch() {
  liveWatchGeneration++;
  clearTimeout(liveWatchTimer);
  if (liveWatchOwnsBusy) { busy = false; updateSendButtonState(); }
  liveWatchOwnsBusy = false;
}
async function watchLiveTurn(id) {
  stopLiveTurnWatch();
  const generation = liveWatchGeneration;
  let checkpoint = '';
  const poll = async () => {
    if (generation !== liveWatchGeneration || conversationId !== id) return;
    try {
      const state = await api('/conversations/' + encodeURIComponent(id) + '/live');
      if (generation !== liveWatchGeneration || conversationId !== id) return;
      const message = state.message;
      const signature = message ? message.checkpoint_at + ':' + message.execution_status : '';
      if (message && signature !== checkpoint) {
        checkpoint = signature;
        const previous = [...thread.querySelectorAll('article.message')].find(item => item.dataset.messageId === message.id)
          || (liveWatchOwnsBusy ? thread.querySelector('article.message.assistant:last-of-type') : null);
        const scrollTop = thread.scrollTop;
        const follow = thread.scrollHeight - scrollTop - thread.clientHeight < 110;
        const expanded = previous ? [...previous.querySelectorAll('details')].map(detail => detail.open) : [];
        const bubble = renderMessage('assistant', message.content, '', message.tool_events || [], {
          messageId: message.id, executionStatus: message.execution_status, segments: message.segments,
          thinking: message.thinking, subagentEvents: message.subagent_events,
          turnDiff: message.turn_diff, aborted: message.aborted,
        });
        const article = bubble.closest('article');
        if (previous) previous.replaceWith(article);
        [...article.querySelectorAll('details')].forEach((detail, index) => { if (expanded[index] !== undefined) detail.open = expanded[index]; });
        thread.scrollTop = follow ? thread.scrollHeight : scrollTop;
      }
      if (state.active) {
        busy = true; liveWatchOwnsBusy = true;
        activeTurnStartedAt = Date.now() - 1000;
        updateSendButtonState();
        for (const approval of state.approvals || []) openToolApprovalDialog({ ...approval, approval_id: approval.id });
        liveWatchTimer = setTimeout(poll, 1000);
      } else if (liveWatchOwnsBusy) {
        liveWatchOwnsBusy = false; busy = false; updateSendButtonState();
        conversations = await api('/conversations'); renderConversationList();
      }
    } catch (error) {
      if (generation === liveWatchGeneration && liveWatchOwnsBusy) liveWatchTimer = setTimeout(poll, 1500);
    }
  };
  await poll();
}

let userExplicitlyUnboundProject = false;

function detachLiveTransport() {
  if (!activeChatAbortController) return;
  activeTurnSequence++;
  activeChatAbortController.abort();
  activeChatAbortController = null;
  busy = false;
  updateSendButtonState();
}

async function startNewChat(initialProjectId = undefined) {
  detachLiveTransport();
  stopLiveTurnWatch();
  closeSettingsPage();
  if (runStream) {
    runStream.close();
    runStream = null;
  }
  feedbackRunId = null;
  conversationId = null;
  selectedRunId = null;
  currentActiveRun = null;
  currentRunEvents = [];
  team = null;
  teamDirty = false;
  lastReviewedFilesData = [];
  selectedWorkspaceFile = '';
  if ($('#run-detail')) $('#run-detail').innerHTML = '';
  if ($('#team-feedback')) $('#team-feedback').textContent = '';
  if (initialProjectId !== undefined) {
    userExplicitlyUnboundProject = !initialProjectId;
    draftProjectId = initialProjectId || null;
  } else if (userExplicitlyUnboundProject) {
    draftProjectId = null;
  } else {
    draftProjectId = draftProjectId || $('#project-select')?.value || projects[0]?.id || null;
  }
  $('#project-select').value = draftProjectId || '';
  updateContextLabels();
  if (draftProjectId) await createConversation(draftProjectId);
  renderConversationList();
  thread.replaceChildren();
  await loadTeam();
  await loadWorkspaceFiles('');
  await refreshContextUsage({ used_tokens: 0, max_tokens: contextMaxTokens, usage_percent: 0, message_count: 0 });
  syncTrackedSelectorLabels();
  void refreshConversationPlugins();
  welcome();
}

async function openConversation(id, options = {}) {
  detachLiveTransport();
  stopLiveTurnWatch();
  closeSettingsPage();
  if (!id) {
    await startNewChat(draftProjectId || $('#project-select')?.value || projects[0]?.id || null);
    return;
  }
  if (runStream) {
    runStream.close();
    runStream = null;
  }
  if (options.record !== false && (trailIndex < 0 || conversationTrail[trailIndex] !== id)) {
    conversationTrail = conversationTrail.slice(0, trailIndex + 1);
    conversationTrail.push(id);
    trailIndex = conversationTrail.length - 1;
  }
  updateNavigationButtons();
  feedbackRunId = null;
  conversationId = id;
  void refreshConversationPlugins();
  localStorage.setItem('masp.lastConversationId', id);
  selectedRunId = null;
  currentActiveRun = null;
  currentRunEvents = [];
  team = null;
  teamDirty = false;
  lastReviewedFilesData = [];
  if ($('#run-detail')) $('#run-detail').innerHTML = '';
  const item = conversations.find((conversation) => conversation.id === id);
  if (item) {
    draftProjectId = item.project_id || null;
    $('#project-select').value = item.project_id || '';
    if (item.model_profile_id) $('#chat-model-select').value = item.model_profile_id;
    refreshSelectMenus();
  }
  updateContextLabels();
  renderConversationList();
  thread.replaceChildren();
  await loadTeam();
  await loadWorkspaceFiles('');
  syncTrackedSelectorLabels();
  const messages = await api('/conversations/' + encodeURIComponent(id) + '/messages');
  for (const message of [...messages].sort((a, b) => a.created_at.localeCompare(b.created_at))) {
    renderMessage(
      message.role,
      message.content,
      '',
      message.tool_events || [],
      {
        messageId: message.id,
        attachments: message.attachments || [],
        executionStatus: message.execution_status,
        segments: message.segments || null,
        turnDiff: message.turn_diff || null,
        executionPlan: message.execution_plan || null,
        aborted: Boolean(message.aborted),
        thinking: message.thinking || null,
        subagentEvents: message.subagent_events || [],
      },
    );
  }
  if (!messages.length) welcome();
  updateHeader();
  updateChatTurnRail();
  refreshContextUsage().catch(() => {});
  void watchLiveTurn(id);
}

async function createConversation(projectId = draftProjectId) {
  const boundProject = projectId || null;
  const item = await api('/conversations', 'POST', {
    project_id: boundProject,
    model_profile_id: $('#chat-model-select').value || null,
    title: '新对话',
  });
  conversations.unshift(item);
  conversationId = item.id;
  void refreshConversationPlugins();
  draftProjectId = boundProject;
  $('#project-select').value = boundProject || '';
  if (trailIndex < 0 || conversationTrail[trailIndex] !== item.id) {
    conversationTrail = conversationTrail.slice(0, trailIndex + 1);
    conversationTrail.push(item.id);
    trailIndex = conversationTrail.length - 1;
  }
  updateNavigationButtons();
  localStorage.setItem('masp.lastConversationId', item.id);
  renderConversationList();
  return item;
}

let userScrolledUpDuringStream = false;

function isThreadNearBottom(threshold = 90) {
  if (!thread) return true;
  return (thread.scrollHeight - thread.scrollTop - thread.clientHeight) <= threshold;
}

if (thread) {
  thread.addEventListener('wheel', (event) => {
    if (event.deltaY < 0 || event.target.closest('.tool-step-detail, .thinking-activity-body, .subagent-step-detail')) {
      userScrolledUpDuringStream = true;
    } else if (isThreadNearBottom(60)) {
      userScrolledUpDuringStream = false;
    }
  }, { passive: true });
  thread.addEventListener('pointerdown', (event) => {
    if (event.target.closest('summary, [data-toggle-step], [data-toggle-subagent]')) userScrolledUpDuringStream = true;
  });
  thread.addEventListener('scroll', () => {
    if (isThreadNearBottom(50)) {
      userScrolledUpDuringStream = false;
    } else if ((thread.scrollHeight - thread.scrollTop - thread.clientHeight) > 110) {
      userScrolledUpDuringStream = true;
    }
  }, { passive: true });
}

const streamingMarkdownTimers = new WeakMap();
let workspaceRefreshTimer = null;
function scheduleWorkspaceRefresh() {
  if (workspaceRefreshTimer !== null) return;
  workspaceRefreshTimer = setTimeout(() => {
    workspaceRefreshTimer = null;
    loadWorkspaceFiles(workspaceFolder).catch(() => {});
    loadWorkspaceChanges().catch(() => {});
  }, 300);
}
let streamScrollFrame = null;
function scheduleThreadScroll() {
  if (streamScrollFrame !== null) return;
  streamScrollFrame = requestAnimationFrame(() => {
    streamScrollFrame = null;
    if (!userScrolledUpDuringStream) thread.scrollTop = thread.scrollHeight;
  });
}
function scheduleStreamingMarkdown(element) {
  if (streamingMarkdownTimers.has(element)) return;
  const timer = setTimeout(() => {
    streamingMarkdownTimers.delete(element);
    if (element.isConnected) renderMarkdownElement(element, visibleAssistantContent(element.dataset.rawContent || ''));
  }, Math.min(240, 50 + Math.floor((element.dataset.rawContent || '').length / 1000) * 10));
  streamingMarkdownTimers.set(element, timer);
}

async function send(content, attachments = [], options = {}) {
  if (busy || (!content.trim() && !attachments.length)) return;
  if (!content.trim()) content = document.documentElement.lang === "en-US" ? "Please inspect the attachments." : "请查看这些附件。";
  const myTurnId = ++activeTurnSequence;
  activeTurnStartedAt = Date.now();
  busy = true;
  isChatExecutionPaused = false;
  updatePauseButtons(false);
  userAbortedCurrentTurn = false;
  suppressAbortBanner = false;
  userScrolledUpDuringStream = false;
  const myAbortController = new AbortController();
  activeChatAbortController = myAbortController;
  updateSendButtonState();
  let turnContainer = null;
  try {
    const existingConversation = conversations.find(item => item.id === conversationId);
    const activeProjectId = existingConversation && Number(existingConversation.message_count || 0) > 0
      ? (existingConversation.project_id || null)
      : (draftProjectId || $('#project-select').value || null);
    if (activeProjectId && !draftProjectId) {
      draftProjectId = activeProjectId;
      $('#project-select').value = activeProjectId;
      updateContextLabels();
    }
    if (!conversationId) {
      await createConversation(activeProjectId);
      await loadWorkspaceFiles('');
    }
    thread.querySelector('.welcome')?.remove();
    renderMessage('user', content, '', [], { attachments });
    let currentBubble = renderMessage('assistant', '', 'typing');
    turnContainer = currentBubble.closest('.assistant-turn') || currentBubble.parentElement;
    let currentBubbleText = '';
    let activeThinkingGroupEl = null;
    let activePlanCardEl = null;
    let activeExecutionPlanEl = null;
    let activeSubagentGroupEl = null;
    let activeSubagentEvents = [];
    let activeToolGroupEl = null;
    let activeToolEvents = [];
    let allTurnToolEvents = [];
    let lastItemType = null;
    let abortBannerShown = false;
    let internalPlanning = false;

    const response = await fetch('/api/conversations/' + encodeURIComponent(conversationId) + '/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: myAbortController.signal,
      body: JSON.stringify({
        content,
        previous_run_id: feedbackRunId,
        agent_id: activeProjectId ? ($('#agent-select').value || null) : null,
        model_profile_id: $('#chat-model-select').value || null,
        access_mode: $('#access-select').value,
        project_id: activeProjectId,
        command_timeout_seconds: Number($('#setting-command-timeout').value),
        max_context_tokens: contextMaxTokens,
        auto_compact: contextAutoCompact,
        autonomous_hours: Number($('#dsh-autonomous-hours')?.value || 8),
        review_team_plan: true,
        execute_team_now: Boolean(options.executeTeamNow),
        team_version: options.executeTeamNow ? team?.version : null,
        execute_plan_now: Boolean(options.executePlanNow),
        plan_id: options.planId || null,
        main_only: $('#agent-select')?.value === 'main_only',
        attachments,
      }),
    });
    const receivedTurnId = response.headers.get('X-Turn-ID');
    if (receivedTurnId && turnContainer) turnContainer.closest('article').dataset.messageId = receivedTurnId;
    feedbackRunId = null;
    if (!response.ok) {
      let errMsg = '模型请求失败 · HTTP ' + response.status;
      try {
        const rawText = await response.text();
        if (rawText) {
          try {
            const parsedErr = JSON.parse(rawText);
            errMsg = parsedErr.detail || parsedErr.message || errMsg;
          } catch {
            errMsg = rawText.trim().slice(0, 240) || errMsg;
          }
        }
      } catch {}
      throw new Error(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg));
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const part of parts) {
        const data = part.split('\n').filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim()).join('\n');
        if (!data) continue;
        const parsed = JSON.parse(data);
        if (part.includes('event: planning')) {
          internalPlanning = Boolean(parsed.internal);
          if (internalPlanning) {
            activeThinkingGroupEl = createOrUpdateThinkingGroup(activeThinkingGroupEl, {kind:'work',status:'running'});
            if (!activeThinkingGroupEl.parentElement && turnContainer) turnContainer.insertBefore(activeThinkingGroupEl,currentBubble);
          }
          continue;
        }
        if (part.includes('event: work')) {
          activeThinkingGroupEl = createOrUpdateThinkingGroup(activeThinkingGroupEl, parsed);
          if (!activeThinkingGroupEl.parentElement && turnContainer) turnContainer.insertBefore(activeThinkingGroupEl,currentBubble);
          continue;
        }
        if (part.includes('event: execution_plan')) {
          activeExecutionPlanEl = renderExecutionPlanCard(parsed);
          if (activeExecutionPlanEl && turnContainer) {
            turnContainer.insertBefore(activeExecutionPlanEl, currentBubble);
          }
          continue;
        }
        if (part.includes('event: plan_step_update')) {
          const stepEl = activeExecutionPlanEl?.querySelector('#plan-step-' + parsed.step_number);
          if (stepEl) {
            stepEl.classList.toggle('is-done', parsed.status === 'done');
            stepEl.classList.toggle('is-running', parsed.status === 'running');
            const badgeEl = stepEl.querySelector('.plan-step-badge');
            if (badgeEl) {
              if (parsed.status === 'done') {
                badgeEl.className = 'plan-step-badge is-done';
                badgeEl.textContent = '✓ 已完成';
              } else if (parsed.status === 'running') {
                badgeEl.className = 'plan-step-badge is-running';
                badgeEl.textContent = '● 执行中';
              }
            }
          }
          continue;
        }
        if (part.includes('event: model_recovery')) {
          const reasonLabel = {model_length_capped: '模型输出被截断', reasoning_only: '模型仅返回思考', empty_response: '模型返回空响应', stream_interrupted: '模型连接中断'}[parsed.reason] || '模型暂时未完成';
          setFeedback('#team-feedback', reasonLabel + '，正在自动恢复第 ' + parsed.attempt + ' 次…');
          continue;
        }
        if (part.includes('event: paused')) {
          isChatExecutionPaused = true;
          updatePauseButtons(true);
          toast(parsed.message || '对话已暂停');
          continue;
        }
        if (part.includes('event: resumed')) {
          isChatExecutionPaused = false;
          updatePauseButtons(false);
          toast(parsed.message || '对话已恢复');
          continue;
        }
        if (part.includes('event: team')) {
          team = parsed;
          renderTeam();
          if (parsed.status === 'draft' && parsed.agents?.length) {
            activePlanCardEl = createOrUpdatePlanApprovalCard(activePlanCardEl, parsed);
            if (activePlanCardEl && !activePlanCardEl.parentElement && turnContainer) turnContainer.insertBefore(activePlanCardEl, currentBubble);
          }
          continue;
        }
        if (part.includes('event: thinking')) {
          if (internalPlanning) continue;
          activeThinkingGroupEl = createOrUpdateThinkingGroup(activeThinkingGroupEl, parsed);
          if (activeThinkingGroupEl && !activeThinkingGroupEl.parentElement && turnContainer) {
            turnContainer.insertBefore(activeThinkingGroupEl, turnContainer.firstChild);
          }
          continue;
        }
        if (part.includes('event: native-runtime')) {
          if (parsed.reason === 'workspace_coordination') toast(parsed.detail);
          continue;
        }
        if (part.includes('event: subagent_progress')) {
          const existingIdx = activeSubagentEvents.findIndex((e) => e.agent_id === parsed.agent_id);
          if (existingIdx >= 0) activeSubagentEvents[existingIdx] = parsed;
          else activeSubagentEvents.push(parsed);
          activeSubagentGroupEl = createOrUpdateSubagentGroup(activeSubagentGroupEl, activeSubagentEvents);
          if (activeSubagentGroupEl && !activeSubagentGroupEl.parentElement && turnContainer) {
            turnContainer.insertBefore(activeSubagentGroupEl, currentBubble);
          }
          continue;
        }
        if (part.includes('event: approval_required')) {
          openToolApprovalDialog(parsed, content, attachments);
          continue;
        }
        if (part.includes('event: plugins')) {
          scheduleExtensionRefresh();
          continue;
        }
        if (part.includes('event: run')) {
          selectedRunId = parsed.run_id;
          loadRuns().catch(() => {});
          watchRun(parsed.run_id);
          continue;
        }
        if (part.includes('event: compaction')) {
          const notice = document.createElement('div');
          notice.className = 'turn-diff-summary';
          notice.innerHTML = '<span>上下文已智能压缩 · 保留最近 ' + Number(parsed.kept_messages || parsed.retained_count || 0) + ' 条消息</span>';
          turnContainer?.appendChild(notice);
          toast('上下文已自动压缩');
          continue;
        }
        if (part.includes('event: context_usage')) {
          refreshContextUsage(parsed).catch(() => {});
          continue;
        }
        if (part.includes('event: turn_diff')) {
          const diffEl = createTurnDiffElement(parsed, allTurnToolEvents, parsed.message_id);
          if (diffEl && turnContainer) turnContainer.appendChild(diffEl);
          loadWorkspaceFiles(workspaceFolder).catch(() => {});
          loadWorkspaceChanges(parsed.message_id || null).catch(() => {});
          continue;
        }
        if (part.includes('event: aborted')) {
          userAbortedCurrentTurn = true;
          if (!abortBannerShown && !suppressAbortBanner && turnContainer) {
            turnContainer.appendChild(createAbortBannerElement(parsed.reason || '用户手动中止'));
            abortBannerShown = true;
          }
          continue;
        }
        if (part.includes('event: title') && parsed.title) {
          const item = conversations.find((x) => x.id === conversationId);
          if (item) {
            item.title = parsed.title;
            item.message_count = Math.max(2, Number(item.message_count || 0));
            item.project_id = activeProjectId;
          }
          renderConversationList();
          renderProjectList();
          updateHeader();
          continue;
        }
        if (parsed.delta) {
          if (internalPlanning) continue;
          if (lastItemType === 'tool' && currentBubbleText.trim().length > 0) {
            currentBubble.classList.remove('typing');
            currentBubble = document.createElement('div');
            currentBubble.className = 'bubble markdown-body typing';
            turnContainer.appendChild(currentBubble);
            currentBubbleText = '';
            activeToolGroupEl = null;
            activeToolEvents = [];
          }
          currentBubbleText += parsed.delta;
          currentBubble.dataset.rawContent = currentBubbleText;
          scheduleStreamingMarkdown(currentBubble);
          lastItemType = 'text';
        }
        if (parsed.detail) throw new Error(parsed.detail);
        if (parsed.name && parsed.status) {
          if (lastItemType === 'text' && currentBubbleText.trim().length > 0) {
            currentBubble.classList.remove('typing');
            activeToolGroupEl = null;
            activeToolEvents = [];
          }
          if (parsed.status === 'running') {
            if (activeToolEvents.length >= 100 && !activeToolEvents.some(e => e.status === 'running')) {
              activeToolGroupEl = null;
              activeToolEvents = [];
            }
            activeToolEvents.push(parsed);
          } else {
            const runningIdx = activeToolEvents.findIndex((e) =>
              e.name === parsed.name &&
              String(e.agent_id || '') === String(parsed.agent_id || '') &&
              e.status === 'running'
            );
            if (runningIdx >= 0) activeToolEvents[runningIdx] = parsed;
            else activeToolEvents.push(parsed);
            allTurnToolEvents.push(parsed);
          }
          activeToolGroupEl = createOrUpdateToolGroup(activeToolGroupEl, activeToolEvents);
          if (!activeToolGroupEl.parentElement && turnContainer) {
            if (!currentBubbleText.trim().length && currentBubble.parentElement === turnContainer) {
              turnContainer.insertBefore(activeToolGroupEl, currentBubble);
            } else {
              turnContainer.appendChild(activeToolGroupEl);
            }
          }
          lastItemType = 'tool';
          if ((parsed.status === 'complete' || parsed.status === 'completed') && (parsed.category === 'edit' || parsed.category === 'command')) {
            scheduleWorkspaceRefresh();
          }
        }
      }
      if (!userScrolledUpDuringStream) scheduleThreadScroll();
      if (done) break;
    }
    if (currentBubbleText) {
      currentBubble.dataset.rawContent = currentBubbleText;
      renderMarkdownElement(currentBubble, visibleAssistantContent(currentBubbleText));
      currentBubble.classList.remove('typing');
    } else {
      currentBubble.remove();
    }
    updateChatTurnRail();
    conversations = await api('/conversations');
    renderConversationList();
  } catch (error) {
    if (myTurnId !== activeTurnSequence) return;
    const bubble = turnContainer?.querySelector('.bubble.typing') || thread.querySelector('.bubble.typing');
    if (error.name === 'AbortError' || userAbortedCurrentTurn) {
      if (bubble) {
        if (!bubble.textContent?.trim()) bubble.remove();
        else bubble.classList.remove('typing');
      }
      if (!suppressAbortBanner && turnContainer && !turnContainer.querySelector('.abort-banner')) {
        turnContainer.appendChild(createAbortBannerElement('用户手动中止'));
      }
    } else if (bubble) {
      const existing = bubble.textContent || '';
      renderMarkdownElement(bubble, (existing ? existing + '\n\n' : '') + translateUiText(error.message));
      bubble.classList.remove('typing');
    } else {
      renderMessage('assistant', translateUiText(error.message));
    }
  } finally {
    if (myTurnId === activeTurnSequence) {
      busy = false;
      pendingApprovalRetry = null;
      toolApprovalQueue.length = 0;
      if ($('#tool-approval-dialog').open) $('#tool-approval-dialog').close();
      activeChatAbortController = null;
      updateSendButtonState();
      updateChatTurnRail();
      refreshContextUsage().catch(() => {});
      $('#prompt').focus();
      if (!userAbortedCurrentTurn && conversationId) {
        const id = conversationId;
        setTimeout(() => { if (!busy && conversationId === id) void watchLiveTurn(id); }, 0);
      }
    }
  }
}

$('#send').addEventListener('click', (event) => {
  if (!busy) return;
  event.preventDefault();
  event.stopPropagation();
  if (Date.now() - activeTurnStartedAt < 350) return;
  abortActiveChatTurn();
});
$('#composer').addEventListener('submit', (event) => {
  event.preventDefault();
  if (busy) return;
  const input = $('#prompt');
  if (!input.value.trim() && !pendingAttachments.length) return;
  const text = input.value;
  const attachments = pendingAttachments;
  pendingAttachments = [];
  renderAttachments();
  input.value = '';
  const executePlanNow = event.currentTarget.dataset.executePlanNow === 'true';
  const planId = event.currentTarget.dataset.planId || null;
  delete event.currentTarget.dataset.executePlanNow;
  delete event.currentTarget.dataset.planId;
  send(text, attachments, { executePlanNow, planId });
});
function matchesShortcut(event, rawCombo) {
  const combo = String(rawCombo || '').replace(/\s+/g, '');
  if (!combo) return false;
  const parts = combo.split('+');
  const keyTarget = parts[parts.length - 1].toLowerCase();
  const needCtrl = parts.some((p) => p.toLowerCase() === 'ctrl' || p.toLowerCase() === 'cmd');
  const needAlt = parts.some((p) => p.toLowerCase() === 'alt');
  const needShift = parts.some((p) => p.toLowerCase() === 'shift');
  const hasCtrl = Boolean(event.ctrlKey || event.metaKey);
  if (hasCtrl !== needCtrl || Boolean(event.altKey) !== needAlt || Boolean(event.shiftKey) !== needShift) {
    return false;
  }
  return String(event.key || '').toLowerCase() === keyTarget;
}

$('#prompt').addEventListener('keydown', (event) => {
  if (event.isComposing || event.keyCode === 229) return;
  const sendCombo = String(dshSettings?.shortcuts?.sendMessage || (dshSettings?.general?.sendWithEnter === false ? 'Ctrl+Enter' : 'Enter')).replace(/\s+/g, '');
  if (sendCombo === 'Ctrl+Enter') {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      if (busy) return;
      $('#composer').requestSubmit();
    }
    return;
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    if (busy) return;
    $('#composer').requestSubmit();
  }
});
$('#new-chat').addEventListener('click', () => startNewChat(null));
$('#project-select').addEventListener('change', async () => {
  draftProjectId = $('#project-select').value || null;
  updateContextLabels();
  renderProjectList();
  await loadTeam();
  await loadWorkspaceFiles('');
  if (!conversationId) welcome();
});
$('#context-project-trigger').addEventListener('click', () => {
  $('#context-project-menu').hidden = !$('#context-project-menu').hidden;
  $('#context-branch-menu').hidden = true;
  renderContextProjects();
  $('#context-project-search').focus();
});
document.addEventListener('click', (event) => {
  if (event.target.closest('.context-picker')) return;
  $('#context-project-menu').hidden = true;
  $('#context-branch-menu').hidden = true;
});
document.addEventListener('keydown', (event) => {
  const sc = dshSettings?.shortcuts || {};
  const searchCombo = sc.globalSearch || 'Ctrl+K';
  const newChatCombo = sc.newChat || 'Ctrl+N';
  const settingsCombo = sc.openSettings || 'Ctrl+,';
  if (matchesShortcut(event, searchCombo)) {
    event.preventDefault();
    if (!$('#search-dialog').open) $('#search-dialog').showModal();
    $('#conversation-search').focus();
    return;
  }
  if (matchesShortcut(event, newChatCombo)) {
    event.preventDefault();
    startNewChat(null);
    return;
  }
  if (matchesShortcut(event, settingsCombo)) {
    event.preventDefault();
    openSettingsPage('general');
    return;
  }
  if (event.key !== 'Escape') return;
  $('#context-project-menu').hidden = true;
  $('#context-branch-menu').hidden = true;
});
$('#context-branch-trigger').addEventListener('click', () => {
  $('#context-branch-menu').hidden = !$('#context-branch-menu').hidden;
  $('#context-project-menu').hidden = true;
  $('#context-branch-search').focus();
});
$('#context-project-search').addEventListener('input', () => renderContextProjects($('#context-project-search').value));
$('#context-branch-search').addEventListener('input', () => {
  const query = $('#context-branch-search').value.trim().toLowerCase();
  $('#context-branch-options').querySelectorAll('[data-branch]').forEach((item) => item.hidden = !item.dataset.branch.toLowerCase().includes(query));
});
document.querySelector('.context-bar').addEventListener('click', async (event) => {
  const action = event.target.closest('[data-context-action]')?.dataset.contextAction;
  if (action === 'new-project') { $('#context-project-menu').hidden = true; $('#project-dialog').showModal(); return; }
  if (action === 'no-project') {
    if (conversationId && conversations.find((item) => item.id === conversationId)?.message_count) return toast('已开始的对话不能更改项目。请点击“新聊天”。', true);
    userExplicitlyUnboundProject = true;
    draftProjectId = null;
    $('#project-select').value = '';
    $('#context-project-menu').hidden = true;
    updateContextLabels();
    renderProjectList();
    await loadTeam();
    await loadWorkspaceFiles('');
    welcome();
    return;
  }
  const projectId = event.target.closest('[data-context-project]')?.dataset.contextProject;
  if (projectId) {
    if (conversationId && conversations.find((item) => item.id === conversationId)?.message_count) return toast('已开始的对话不能更改项目。请点击“新聊天”。', true);
    userExplicitlyUnboundProject = false;
    draftProjectId = projectId;
    $('#project-select').value = projectId;
    $('#context-project-menu').hidden = true;
    updateContextLabels();
    renderProjectList();
    await loadTeam();
    await loadWorkspaceFiles('');
    if (!conversationId) welcome();
    return;
  }
  const branch = event.target.closest('[data-branch]')?.dataset.branch;
  if (branch) {
    if (!draftProjectId) {
      $('#context-branch-name').textContent = branch;
      $('#context-branch-menu').hidden = true;
      return;
    }
    try {
      const data = await api('/projects/' + encodeURIComponent(draftProjectId) + '/branches', 'POST', { name: branch });
      $('#context-branch-name').textContent = data.current;
      $('#context-branch-menu').hidden = true;
      await loadProjectBranches(draftProjectId);
      toast('已切换到分支 ' + data.current);
    } catch (error) { toast(error.message, true); }
    return;
  }
  if (action === 'new-branch') {
    if (!draftProjectId) return toast('请先选择一个项目文件夹。', true);
    $('#context-branch-menu').hidden = true;
    setFeedback('#branch-feedback', '');
    const branchInput = $('#branch-name-input');
    if (branchInput) branchInput.value = '';
    $('#branch-dialog')?.showModal();
    branchInput?.focus();
  }
});
$('#close-branch-dialog')?.addEventListener('click', () => $('#branch-dialog')?.close());
$('#branch-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!draftProjectId) {
    $('#branch-dialog')?.close();
    return toast('请先选择一个项目文件夹。', true);
  }
  const name = ($('#branch-name-input')?.value || '').trim();
  if (!name) return setFeedback('#branch-feedback', '请输入新分支名称。', true);
  try {
    const data = await api('/projects/' + encodeURIComponent(draftProjectId) + '/branches', 'POST', { name, create: true });
    $('#context-branch-name').textContent = data.current;
    $('#branch-dialog')?.close();
    await loadProjectBranches(draftProjectId);
    toast('已创建并切换到分支 ' + data.current);
  } catch (error) {
    setFeedback('#branch-feedback', error.message, true);
  }
});
$('#chat-model-select')?.addEventListener('change', () => {
  const prev = lastTrackedLabels.model;
  const next = getSelectOptionLabel($('#chat-model-select'), '');
  if (prev && next && prev !== next) {
    appendSwitchNotice(prev, next);
  }
  lastTrackedLabels.model = next;
  if (team) renderWorkflowMindmap(team);
});
$('#agent-select').addEventListener('change', () => {
  const prevAgent = lastTrackedLabels.agent;
  const nextAgent = getSelectOptionLabel($('#agent-select'), '');
  if (prevAgent && nextAgent && prevAgent !== nextAgent) {
    appendSwitchNotice(prevAgent, nextAgent);
  }
  lastTrackedLabels.agent = nextAgent;
  const val = $('#agent-select').value;
  if (val === 'main_only') {
    refreshSelectMenus();
    lastTrackedLabels.model = getSelectOptionLabel($('#chat-model-select'), '');
    $('#prompt').placeholder = '仅使用主 Agent 处理本轮任务';
    return;
  }
  const agent = team?.agents?.find((item) => item.id === val);
  const profile = agent?.model_profile_id;
  if (profile) $('#chat-model-select').value = profile;
  refreshSelectMenus();
  lastTrackedLabels.model = getSelectOptionLabel($('#chat-model-select'), '');
  $('#prompt').placeholder = agent ? '指定给 ' + agent.name + ' 发送任务' : '随心输入 (主 Agent 自动统筹子 Agent)';
});
$('#projects').addEventListener('click', async (event) => {
  const fold = event.target.closest('[data-project-collapse]');
  if (fold) {
    const key = 'masp.project.collapsed.' + fold.dataset.projectCollapse;
    localStorage.setItem(key, String(localStorage.getItem(key) !== 'true'));
    renderProjectList(); return;
  }
  const action = event.target.closest('[data-conversation-action]');
  if (action) {
    const id = action.dataset.conversationId;
    const item = conversations.find(conv => conv.id === id);
    if (!item) return;
    try {
      if (action.dataset.conversationAction === 'delete') {
        if (busy) return toast('请等待当前回复完成后再删除对话。', true);
        await api('/conversations/' + encodeURIComponent(id), 'DELETE', {});
        lastDeletedConversation = id;
        conversations = conversations.filter(conv => conv.id !== id);
        if (conversationId === id) await startNewChat(draftProjectId);
      } else {
        const title = action.dataset.conversationAction === 'rename' ? await renameConversationTitle(item.title) : null;
        if (action.dataset.conversationAction === 'rename' && !title?.trim()) return;
        const updated = await api('/conversations/' + encodeURIComponent(id), 'PATCH', title === null ? { pinned: !item.pinned } : { title: title.trim() });
        Object.assign(item, updated);
      }
      renderConversationList();
      if (action.dataset.conversationAction === 'delete') {
        toast('对话已删除');
        $('#toast').insertAdjacentHTML('beforeend', '<button id="undo-delete">撤销删除</button>');
      }
    } catch (error) { toast(error.message, true); }
    return;
  }
  const conversationButton = event.target.closest('[data-id]');
  if (conversationButton) { await openConversation(conversationButton.dataset.id); return; }
  const deleteId = event.target.closest('[data-project-delete]')?.dataset.projectDelete;
  if (deleteId) {
    if (busy && currentProjectId() === deleteId) return toast('请等待当前回复完成后再移除项目。', true);
    const removed = projects.find((item) => item.id === deleteId);
    try {
      await api('/projects/' + encodeURIComponent(deleteId), 'DELETE', {});
      lastDeletedProject = removed;
      projects = projects.filter((item) => item.id !== deleteId);
      conversations = await api('/conversations');
      if (currentProjectId() === deleteId) {
        $('#project-select').value = '';
        team = null;
        await startNewChat(projects[0]?.id || null);
      }
      renderSelectors();
      renderProjectList();
      renderConversationList();
      toast('项目已移除');
      $('#toast').insertAdjacentHTML('beforeend', '<button id="undo-project-delete">撤销移除</button>');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 12000);
    } catch (error) { toast(error.message, true); }
    return;
  }
  const id = event.target.closest('[data-project]')?.dataset.project;
  if (!id) return;
  userExplicitlyUnboundProject = false;
  if (conversationId && conversations.find((item) => item.id === conversationId)?.message_count && draftProjectId !== id) {
    await startNewChat(id);
    return;
  }
  $('#project-select').value = id;
  draftProjectId = id;
  updateContextLabels();
  renderProjectList();
  await loadTeam();
  await loadWorkspaceFiles('');
  if (!conversationId) welcome();
});

function renameConversationTitle(title) {
  return new Promise(resolve => {
    const dialog = $('#conversation-rename-dialog');
    $('#conversation-rename-input').value = title;
    dialog.returnValue = '';
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'save' ? $('#conversation-rename-input').value : ''), {once:true});
    dialog.showModal();
    $('#conversation-rename-input').select();
  });
}
$('#toast').addEventListener('click', async (event) => {
  if (!event.target.closest('#undo-project-delete') || !lastDeletedProject) return;
  try {
    const restored = await api('/projects/' + encodeURIComponent(lastDeletedProject.id) + '/restore', 'POST', {});
    projects = await api('/projects');
    conversations = await api('/conversations');
    renderSelectors();
    $('#project-select').value = restored.id;
    draftProjectId = restored.id;
    renderProjectList();
    renderConversationList();
    await loadTeam();
    await loadWorkspaceFiles('');
    lastDeletedProject = null;
    toast('项目已恢复');
  } catch (error) { toast(error.message, true); }
});
$('#conversations').addEventListener('click', async (event) => {
  const deletedId = event.target.closest('[data-delete-conversation]')?.dataset.deleteConversation;
  if (deletedId) {
    if (busy) return toast('请等待当前回复完成后再删除对话。', true);
    try {
      await api('/conversations/' + encodeURIComponent(deletedId), 'DELETE', {});
      lastDeletedConversation = deletedId;
      conversations = conversations.filter((item) => item.id !== deletedId);
      conversationTrail = conversationTrail.filter((id) => id !== deletedId);
      trailIndex = Math.min(trailIndex, conversationTrail.length - 1);
      if (conversationId === deletedId) await startNewChat(draftProjectId);
      renderConversationList();
      toast('对话已删除');
      $('#toast').insertAdjacentHTML('beforeend', '<button id="undo-delete">撤销删除</button>');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 12000);
    } catch (error) { toast(error.message, true); }
    return;
  }
  const id = event.target.closest('[data-id]')?.dataset.id;
  if (id) openConversation(id);
});
$('#toast').addEventListener('click', async (event) => {
  if (!event.target.closest('#undo-delete') || !lastDeletedConversation) return;
  try {
    const restored = await api('/conversations/' + encodeURIComponent(lastDeletedConversation) + '/restore', 'POST', {});
    lastDeletedConversation = null;
    conversations = await api('/conversations');
    await openConversation(restored.id);
    renderConversationList();
    toast('对话已恢复');
  } catch (error) { toast(error.message, true); }
});

$('#back')?.addEventListener('click', async () => {
  if (trailIndex <= 0) return;
  trailIndex -= 1;
  updateNavigationButtons();
  await openConversation(conversationTrail[trailIndex], { record: false });
});
$('#forward')?.addEventListener('click', async () => {
  if (trailIndex >= conversationTrail.length - 1) return;
  trailIndex += 1;
  updateNavigationButtons();
  await openConversation(conversationTrail[trailIndex], { record: false });
});
thread.addEventListener('click', async (event) => {
  const approvePlanBtn = event.target.closest('[data-inline-approve-plan]');
  if (approvePlanBtn) {
    const cardVersion = Number(approvePlanBtn.closest('.plan-approval-card')?.dataset.teamVersion);
    if (cardVersion !== Number(team?.version)) return toast('此方案已被新版替代，请审核最新团队方案。', true);
    try {
      await confirmAndStartTeamExecution();
    } catch (error) {
      toast(error.message, true);
    }
    return;
  }
  const openMindmapBtn = event.target.closest('[data-inline-open-mindmap]');
  if (openMindmapBtn) {
    openTeamReview({ openEditor: true });
    return;
  }
  const stepHead = event.target.closest('[data-toggle-step]');
  if (stepHead) {
    const item = stepHead.closest('.tool-step-item');
    const detail = item?.querySelector('.tool-step-detail');
    if (detail) detail.hidden = !detail.hidden;
    return;
  }
  const subHead = event.target.closest('[data-toggle-subagent]');
  if (subHead) {
    const item = subHead.closest('.subagent-step-item');
    const detail = item?.querySelector('.subagent-step-detail');
    if (detail) detail.hidden = !detail.hidden;
    return;
  }
  const expandTurnBtn = event.target.closest('[data-expand-turn-files]');
  if (expandTurnBtn) {
    const listEl = expandTurnBtn.closest('.turn-edits-list');
    if (!listEl) return;
    const extraRows = [...listEl.querySelectorAll('[data-extra-turn-file]')];
    const isHidden = extraRows.some((r) => r.hidden);
    extraRows.forEach((r) => { r.hidden = !isHidden; });
    const count = Number(expandTurnBtn.dataset.extraCount || extraRows.length);
    expandTurnBtn.innerHTML = isHidden
      ? '<span>收起文件</span><span aria-hidden="true">∧</span>'
      : '<span>再显示 ' + count + ' 个文件</span><span aria-hidden="true">∨</span>';
    return;
  }
  const openTurnFileBtn = event.target.closest('[data-open-turn-file]');
  if (openTurnFileBtn) {
    const filePath = openTurnFileBtn.dataset.openTurnFile;
    const turnMsgId = openTurnFileBtn.closest('[data-turn-msg-id]')?.dataset.turnMsgId || null;
    document.body.classList.remove('inspector-closed');
    showWorkspacePanel('changes', false, turnMsgId);
    await loadWorkspaceChanges(turnMsgId);
    const card = document.querySelector('#workspace-diff [data-ide-file-card="' + CSS.escape(filePath) + '"]');
    if (card) {
      card.open = true;
      card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      await openWorkspaceFile(filePath, true);
    }
    return;
  }
  const reviewTurnBtn = event.target.closest('[data-review-turn-files]');
  if (reviewTurnBtn) {
    const stack = reviewTurnBtn.closest('[data-turn-paths]');
    let paths = [];
    try { paths = JSON.parse(stack?.dataset?.turnPaths || '[]'); } catch {}
    document.body.classList.remove('inspector-closed');
    showWorkspacePanel('review', false);
    await runSelectedFilesReview(paths.length ? paths : null);
    return;
  }
  const revertTurnBtn = event.target.closest('[data-revert-turn-files]');
  if (revertTurnBtn) {
    const wsId = activeWorkspaceId();
    if (!wsId) return toast('请先选择项目或开始对话。', true);
    const stack = revertTurnBtn.closest('[data-turn-paths]');
    let paths = [];
    try { paths = JSON.parse(stack?.dataset?.turnPaths || '[]'); } catch {}
    try {
      const res = await api('/projects/' + encodeURIComponent(wsId) + '/workspace/revert-files', 'POST', { paths });
      toast('已撤销 ' + Number(res.count || paths.length || 0) + ' 个文件的改动');
      await loadWorkspaceFiles(workspaceFolder);
      await loadWorkspaceChanges();
    } catch (error) {
      toast(error.message, true);
    }
    return;
  }
  const openChangesBtn = event.target.closest('[data-open-changes]');
  if (openChangesBtn) {
    const turnMsgId = openChangesBtn.dataset.turnMsgId || openChangesBtn.closest('[data-turn-msg-id]')?.dataset.turnMsgId || null;
    document.body.classList.remove('inspector-closed');
    showWorkspacePanel('changes', true, turnMsgId);
    return;
  }
  const button = event.target.closest('.suggestions button');
  if (!button) return;
  $('#prompt').value = button.textContent;
  $('#composer').requestSubmit();
});

document.querySelectorAll('[data-settings-section]').forEach((button) => button.addEventListener('click', () => {
  openSettingsPage(button.dataset.settingsSection);
}));
$('#settings-close').addEventListener('click', closeSettingsPage);
$('#settings-search').addEventListener('input', () => {
  filterSettingsInPlace($('#settings-search').value);
});
$('#settings-open-models').addEventListener('click', () => { closeSettingsPage(); showLeftTool('models'); });

$('#access-select').addEventListener('change', () => {
  const prevAccess = lastTrackedLabels.access;
  const settings = JSON.parse(localStorage.getItem('masp.settings') || '{}');
  settings.access = $('#access-select').value;
  const nextAccess = getAccessModeLabel(settings.access);
  if (prevAccess && nextAccess && prevAccess !== nextAccess) {
    appendSwitchNotice(prevAccess, nextAccess);
  }
  lastTrackedLabels.access = nextAccess;
  localStorage.setItem('masp.settings', JSON.stringify(settings));
  $('#setting-access').value = settings.access;
  updateAccessDescription(settings.access);
  updateAccessControl(settings.access);
  refreshSelectMenu($('#setting-access'));
  persistDshSettingsPatch({
    permissions: { defaultMode: settings.access },
  });
});
$('#access-trigger').addEventListener('click', () => {
  const open = $('#access-popover').hidden;
  $('#access-popover').hidden = !open;
  $('#access-trigger').setAttribute('aria-expanded', String(open));
});
$('#access-popover').addEventListener('click', (event) => {
  const option = event.target.closest('[data-access-value]');
  if (!option) return;
  $('#access-select').value = option.dataset.accessValue;
  $('#access-select').dispatchEvent(new Event('change', { bubbles: true }));
  $('#access-popover').hidden = true;
  $('#access-trigger').setAttribute('aria-expanded', 'false');
});
document.addEventListener('click', (event) => {
  if (!event.target.closest('.permission-select')) {
    $('#access-popover').hidden = true;
    $('#access-trigger').setAttribute('aria-expanded', 'false');
  }
  if (!event.target.closest('.context-usage-widget') && !event.target.closest('.select-popover')) {
    if ($('#context-usage-popover')) $('#context-usage-popover').hidden = true;
    if ($('#context-usage-trigger')) $('#context-usage-trigger').setAttribute('aria-expanded', 'false');
  }
});

$('#context-usage-trigger')?.addEventListener('click', () => {
  const pop = $('#context-usage-popover');
  if (!pop) return;
  const willOpen = pop.hidden;
  pop.hidden = !willOpen;
  $('#context-usage-trigger').setAttribute('aria-expanded', String(willOpen));
  if (willOpen) refreshContextUsage().catch(() => {});
});
$('#context-limit-select')?.addEventListener('change', () => {
  contextMaxTokens = Number($('#context-limit-select').value || 64000);
  localStorage.setItem('masp.contextMaxTokens', String(contextMaxTokens));
  refreshSelectMenu($('#context-limit-select'));
  refreshContextUsage({ used_tokens: lastContextUsedTokens, max_tokens: contextMaxTokens }).catch(() => {});
  if (conversationId) refreshContextUsage().catch(() => {});
  persistDshSettingsPatch({
    context: { maxContextTokens: contextMaxTokens, autoCompact: contextAutoCompact },
  });
});
$('#context-auto-compact')?.addEventListener('change', () => {
  contextAutoCompact = Boolean($('#context-auto-compact').checked);
  localStorage.setItem('masp.contextAutoCompact', String(contextAutoCompact));
  persistDshSettingsPatch({
    context: { maxContextTokens: contextMaxTokens, autoCompact: contextAutoCompact },
  });
});
$('#context-compact-now')?.addEventListener('click', async () => {
  if (!conversationId) return toast('当前还没有可压缩的对话消息。');
  try {
    const res = await api('/conversations/' + encodeURIComponent(conversationId) + '/compact', 'POST', {});
    await refreshContextUsage();
    const kept = Number(res.retained_count ?? res.kept_messages ?? 0);
    const layerTag = res.layer_used ? (' (' + res.layer_used + ')') : '';
    const notice = document.createElement('div');
    notice.className = 'turn-diff-summary';
    notice.innerHTML = '<span>已手动压缩上下文' + escapeHtml(layerTag) + ' · 保留最近 ' + kept + ' 条消息</span>';
    thread.appendChild(notice);
    thread.scrollTop = thread.scrollHeight;
    toast('上下文已压缩，保留最近 ' + kept + ' 条消息');
  } catch (error) {
    toast(error.message, true);
  }
});

$('#browser-toolbar')?.addEventListener('submit', (event) => {
  event.preventDefault();
  const raw = $('#browser-address')?.value?.trim();
  if (!raw) return;
  setBrowserPage({ url: buildBrowserProxyUrl(raw), displayUrl: raw });
});
$('#browser-back')?.addEventListener('click', () => {
  if (browserHistoryIndex > 0) setBrowserPage(browserHistory[--browserHistoryIndex], false);
});
$('#browser-forward')?.addEventListener('click', () => {
  if (browserHistoryIndex < browserHistory.length - 1) setBrowserPage(browserHistory[++browserHistoryIndex], false);
});
$('#browser-reload')?.addEventListener('click', () => {
  const page = browserHistory[browserHistoryIndex];
  if (page) setBrowserPage(page, false);
});
$('#team-panel').addEventListener('input', () => { teamDirty = true; });
$('#team-concurrency').addEventListener('change', () => { $('#team-concurrency-custom').hidden = $('#team-concurrency').value !== 'custom'; });
$('#team-concurrency-custom').addEventListener('input', () => {
  const n = Number($('#team-concurrency-custom').value);
  if (n < 1 || n > 64) $('#team-concurrency-custom').setCustomValidity('最大并行数应为 1 到 64。');
  else $('#team-concurrency-custom').setCustomValidity('');
});
$('#agent-list').addEventListener('click', (event) => {
  const id = event.target.closest('[data-remove-agent]')?.dataset.removeAgent;
  if (!id) return;
  event.target.closest('[data-agent]').remove();
  teamDirty = true;
});
$('#add-agent').addEventListener('click', () => {
  if (!currentProjectId()) {
    setFeedback('#team-feedback', '请先选择或新建项目，再添加子 Agent。', true);
    return;
  }
  const count = document.querySelectorAll('[data-agent]').length + 1;
  $('#agent-list .empty')?.remove();
  $('#agent-list').insertAdjacentHTML('beforeend', agentCard({
    id: 'agent_' + count, name: '新 Agent', responsibility: '负责指定模块的实现与验证',
    model_profile_id: '', owned_paths: [], locked: false,
  }));
  teamDirty = true;
  setFeedback('#team-feedback', '已添加 Agent 草稿。请配置职责和模型，再保存团队。');
});
$('#generate-team').addEventListener('click', async () => {
  try {
    const projectId = currentProjectId();
    if (!projectId) throw new Error('先创建并选择项目');
    const requirement = $('#team-requirement').value.trim();
    if (requirement.length < 5) throw new Error('先填写统一需求');
    if (!conversationId) {
      await createConversation(projectId);
    }
    setFeedback('#team-feedback', '主 Agent 正在规划当前对话专属的子 Agent 团队…');
    team = await api('/projects/' + encodeURIComponent(projectId) + '/team/generate', 'POST', {
      requirement,
      main_profile_id: $('#main-profile').value,
      max_concurrency: Number($('#team-concurrency').value === 'custom' ? $('#team-concurrency-custom').value : $('#team-concurrency').value),
      conversation_id: conversationId || null,
    });
    renderTeam();
    setFeedback('#team-feedback', '子 Agent 分工草案已生成。点击"确认并开始执行"即可启动并行协作。');
    openTeamReview();
  } catch (error) { setFeedback('#team-feedback', error.message, true); }
});
$('#save-team').addEventListener('click', async () => {
  try { await saveTeam(); } catch (error) { setFeedback('#team-feedback', error.message, true); }
});
$('#approve-team')?.addEventListener('click', async () => {
  try {
    await confirmAndStartTeamExecution();
  } catch (error) { setFeedback('#team-feedback', error.message, true); }
});
$('#start-team')?.addEventListener('click', async () => {
  try {
    await confirmAndStartTeamExecution();
  } catch (error) { setFeedback('#team-feedback', error.message, true); }
});

$('#model-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const values = new FormData(event.target);
  const data = {
    name: values.get('name'), base_url: values.get('base_url'), model: values.get('model'),
    api_key: values.get('api_key') || null,
    temperature: Number(values.get('temperature')), top_p: Number(values.get('top_p')),
    max_output_tokens: Number(values.get('max_output_tokens')),
    timeout_seconds: Number(values.get('timeout_seconds')),
  };
  try {
    await api(editingProfileId ? '/model-profiles/' + encodeURIComponent(editingProfileId) : '/model-profiles',
      editingProfileId ? 'PUT' : 'POST', data);
    editingProfileId = null;
    event.target.reset();
    profiles = await api('/model-profiles');
    renderSelectors();
    renderTeam();
    setFeedback('#model-feedback', '模型配置已保存。');
  } catch (error) { setFeedback('#model-feedback', error.message, true); }
});

async function handleModelListClick(event) {
  const button = event.target.closest('button');
  if (!button) return;
  const profileId = button.dataset.probe;
  const editId = button.dataset.editProfile;
  if (editId) {
    closeSettingsPage();
    showLeftTool('models');
    const profile = profiles.find((item) => item.id === editId);
    if (!profile) return;
    editingProfileId = editId;
    for (const field of ['name', 'base_url', 'model', 'temperature', 'top_p', 'max_output_tokens', 'timeout_seconds']) {
      $('#model-form').elements[field].value = profile[field];
    }
    $('#model-form').elements.api_key.value = '';
    setFeedback('#model-feedback', '正在编辑 ' + profile.name + '；密钥留空表示保留现有密钥。');
  }
  if (profileId) {
    const statusNodes = document.querySelectorAll('[data-probe-result="' + CSS.escape(profileId) + '"]');
    statusNodes.forEach((node) => { node.textContent = '正在检测连接…'; node.classList.remove('error'); });
    try {
      const result = await api('/model-profiles/' + encodeURIComponent(profileId) + '/probe', 'POST', {});
      statusNodes.forEach((node) => { node.textContent = '连接成功：' + result.model + ' · ' + result.reply; });
    } catch (error) {
      statusNodes.forEach((node) => { node.textContent = error.message; node.classList.add('error'); });
    }
  }
}
$('#model-list').addEventListener('click', handleModelListClick);
$('#settings-model-list')?.addEventListener('click', handleModelListClick);

$('#refresh-runs').addEventListener('click', loadRuns);
$('#skill-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const values = new FormData(event.target);
  try {
    await api('/skills', 'POST', {
      name: values.get('name'),
      content: values.get('content'),
    });
    event.target.reset();
    await loadSkills();
    await loadPlugins();
    setFeedback('#skill-feedback', '技能已保存；Agent 现在可以按需加载。');
  } catch (error) { setFeedback('#skill-feedback', error.message, true); }
});
$('#mcp-transport').addEventListener('change', () => {
  const remote = $('#mcp-transport').value === 'http';
  $('#mcp-command-field').hidden = remote;
  $('#mcp-url-field').hidden = !remote;
});
$('#mcp-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const values = new FormData(event.target);
  try {
    await api('/mcp-servers', 'POST', {
      name: values.get('name'), transport: values.get('transport'),
      command: values.get('command') || '', url: values.get('url') || null,
      args: String(values.get('args') || '').split('\n').map((item) => item.trim()).filter(Boolean),
      env: JSON.parse(String(values.get('env') || '{}')),
      headers: JSON.parse(String(values.get('headers') || '{}')),
      cwd: String(values.get('cwd') || '').trim() || null,
      enabled: values.has('enabled'),
    });
    event.target.reset();
    await loadMcpServers();
    await loadPlugins();
    setFeedback('#mcp-feedback', 'MCP 服务已保存。可点击卡片内按钮检测工具列表。');
  } catch (error) { setFeedback('#mcp-feedback', error.message, true); }
});
$('#mcp-list').addEventListener('click', async (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.dshToggle) {
    try {
      await api('/dsh/plugins/toggle', 'POST', {
        id: button.dataset.dshToggle,
        enabled: button.dataset.dshEnabled === 'true',
      });
      await loadMcpServers();
      await loadPlugins();
    } catch (error) { setFeedback('#mcp-feedback', error.message, true); }
    return;
  }
  const id = button.dataset.mcpProbe || button.dataset.mcpToggle || button.dataset.mcpDelete;
  if (!id) return;
  try {
    if (button.dataset.mcpProbe) {
      const status = document.querySelector('[data-mcp-result="' + CSS.escape(id) + '"]');
      if (status) { status.textContent = '正在连接服务…'; status.classList.remove('error'); }
      const projParam = currentProjectId() ? '?project_id=' + encodeURIComponent(currentProjectId()) : '';
      const result = await api('/mcp-servers/' + encodeURIComponent(id) + '/probe' + projParam, 'POST', {});
      if (status) status.textContent = '连接成功，发现 ' + result.tools.length + ' 个工具：' + result.tools.map((tool) => tool.name).join('、');
      return;
    }
    const server = (window.maspMcpServers || []).find((item) => item.id === id);
    if (!server) return;
    if (button.dataset.mcpToggle) {
      await api('/mcp-servers/' + encodeURIComponent(id), 'PUT', {
        name: server.name, transport: server.transport || 'stdio', command: server.command || '', url: server.url || null, args: server.args, enabled: !server.enabled,
      });
      await loadMcpServers();
      await loadPlugins();
      setFeedback('#mcp-feedback', server.enabled ? '服务已停用。' : '服务已启用。');
    } else if (button.dataset.mcpDelete) {
      await api('/mcp-servers/' + encodeURIComponent(id), 'DELETE', {});
      await loadMcpServers();
      await loadPlugins();
      setFeedback('#mcp-feedback', '服务已删除。');
    }
  } catch (error) {
    const status = document.querySelector('[data-mcp-result="' + CSS.escape(id) + '"]');
    if (status) { status.textContent = error.message; status.classList.add('error'); }
    else setFeedback('#mcp-feedback', error.message, true);
  }
});

document.querySelectorAll('[data-plugin-tab]').forEach((btn) => btn.addEventListener('click', () => {
  activePluginTab = btn.dataset.pluginTab;
  document.querySelectorAll('[data-plugin-tab]').forEach((b) => b.classList.toggle('selected', b === btn));
  renderDshPluginInventory();
}));

async function installPluginFromInput(inputSelector, feedbackSelector) {
  const path = $(inputSelector)?.value?.trim();
  if (!path) return setFeedback(feedbackSelector, '请输入本地插件目录或清单路径。', true);
  try {
    setFeedback(feedbackSelector, '正在解析并加载插件…');
    const res = await api('/dsh/plugins/install', 'POST', { path });
    if (res.status === 'build_required') {
      const feedback = $(feedbackSelector);
      feedback.replaceChildren();
      const plan = document.createElement('pre');
      plan.textContent = '此插件需要构建：\n' + res.commands.map(command =>
        command.argv.join(' ') + '\n' + JSON.stringify(command.scripts, null, 2)).join('\n');
      const approve = document.createElement('button');
      approve.type = 'button'; approve.textContent = '批准构建并加载';
      const reject = document.createElement('button');
      reject.type = 'button'; reject.textContent = '取消安装';
      async function decide(approved) {
        approve.disabled = reject.disabled = true;
        try {
          const result = await api('/dsh/builds/' + encodeURIComponent(res.id) + '/decision', 'POST', { approved, revision: res.revision });
          setFeedback(feedbackSelector, approved ? '已成功加载插件：' + result.name : '已取消安装');
          if (approved) { $(inputSelector).value = ''; scheduleExtensionRefresh(); }
        } catch (error) { setFeedback(feedbackSelector, error.message, true); }
      }
      approve.addEventListener('click', () => decide(true));
      reject.addEventListener('click', () => decide(false));
      feedback.append(plan, approve, reject);
      return;
    }
    $(inputSelector).value = '';
    await loadPlugins();
    await loadMcpServers();
    await loadSkills();
    setFeedback(feedbackSelector, '已成功加载插件：' + res.name);
  } catch (error) {
    setFeedback(feedbackSelector, error.message, true);
  }
}
$('#dsh-plugin-install-btn')?.addEventListener('click', () => installPluginFromInput('#dsh-plugin-path', '#dsh-plugin-install-feedback'));
const marketEntries = new Map();
let extensionDetailAction = null;
let extensionDetailEpoch = 0;
function extensionDescription(item) {
  return typeof item.description === 'object' ? (item.description?.zh || item.description?.['zh-CN'] || item.description?.en || '') : item.description || '';
}
function safeExtensionUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : ''; } catch { return ''; }
}
function startExtensionDetail(title, confirmText) {
  disposeExtensionSurface();
  extensionDetailEpoch++;
  extensionDetailAction = null;
  $('#extension-detail-title').textContent = title;
  $('#extension-detail-body').textContent = '正在读取…';
  $('#extension-detail-status').textContent = '';
  $('#extension-detail-confirm').textContent = confirmText;
  $('#extension-detail-confirm').hidden = false;
  $('#extension-detail-confirm').disabled = true;
  if (!$('#extension-detail-dialog').open) $('#extension-detail-dialog').showModal();
  return extensionDetailEpoch;
}
async function openMarketDetail(name) {
  const epoch = startExtensionDetail('安装 ' + name + '？', '确认安装');
  let item = marketEntries.get(name);
  try {
    if (!item) item = (await api('/dsh/market?q=' + encodeURIComponent(name))).plugins.find(value => value.name === name);
    if (epoch !== extensionDetailEpoch) return;
    if (!item) throw Error('插件已不在目录中，请刷新市场');
    const description = extensionDescription(item);
    const source = safeExtensionUrl(item.url);
    const images = (item.screenshots || []).filter(value => {
      const url = safeExtensionUrl(value);
      return url && ['github.com', 'raw.githubusercontent.com', 'user-images.githubusercontent.com', 'private-user-images.githubusercontent.com', 'github-production-user-asset-6210df.s3.amazonaws.com'].includes(new URL(url).hostname);
    });
    $('#extension-detail-body').innerHTML = '<p class="extension-byline">' + escapeHtml(item.owner || '') + ' · ' + escapeHtml(item.version ? 'v' + item.version : '版本未提供') + ' · ★ ' + Number(item.stars || 0) + (item.downloads != null ? ' · ↓ ' + Number(item.downloads).toLocaleString() + ' / 近30天' : '') + (item.added ? ' · ' + escapeHtml(item.added) : '') + '</p>' +
      '<p class="extension-description">' + escapeHtml(description) + '</p>' +
      (images.length ? '<div class="extension-screenshots">' + images.map(url => '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer"><img src="' + escapeHtml(url) + '" alt="插件界面预览" loading="lazy" referrerpolicy="no-referrer"></a>').join('') + '</div>' : '') +
      '<details class="extension-fold"><summary>它会做什么</summary><p>' + escapeHtml(description) + '</p><p>' + escapeHtml((item.capabilities || []).join('、') || '目录未提供能力扫描信息') + '</p>' + (source ? '<a href="' + escapeHtml(source) + '" target="_blank" rel="noopener noreferrer">查看项目说明和使用指令 ↗</a>' : '') + '</details>' +
      '<details class="extension-fold"><summary>安装命令</summary><pre>' + escapeHtml(item.install || ('dsh plugin add ' + (item.npm || name))) + '</pre><p>在本程序点击确认后，使用本程序的安装目录和 Host 工具链。</p></details><p class="extension-note">构建脚本默认不运行。需要构建时，将在安装后单独显示构建审批。</p>';
    $('#extension-detail-confirm').disabled = false;
    extensionDetailAction = async () => {
      const result = await api('/dsh/market/install', 'POST', {name});
      if (result.status === 'build_required') {
        $('#extension-detail-status').textContent = '插件需要构建，尚未启用。以下脚本需要单独批准：\n' + result.commands.map(command => command.argv.join(' ') + '\n' + JSON.stringify(command.scripts, null, 2)).join('\n');
        $('#extension-detail-confirm').textContent = '批准构建并安装';
        extensionDetailAction = async () => {
          const installed = await api('/dsh/builds/' + encodeURIComponent(result.id) + '/decision', 'POST', {approved: true, revision: result.revision});
          $('#extension-detail-status').textContent = '已成功加载插件：' + installed.name;
          $('#extension-detail-confirm').hidden = true;
          scheduleExtensionRefresh();
        };
      } else {
        $('#extension-detail-status').textContent = '安装成功，已加入本程序的插件目录。';
        $('#extension-detail-confirm').hidden = true;
        document.querySelectorAll('[data-market-install]').forEach(button => { if (button.dataset.marketInstall === name) button.textContent = '查看'; });
      }
      scheduleExtensionRefresh();
    };
  } catch (error) { if (epoch === extensionDetailEpoch) $('#extension-detail-status').textContent = error.message; }
}
async function openInstalledDetail(id) {
  const epoch = startExtensionDetail('插件详情与配置', '保存配置');
  try {
    const inventory = await api('/dsh/plugins');
    if (epoch !== extensionDetailEpoch) return;
    const item = [...inventory.official, ...inventory.installed, ...inventory.mcp_servers].find(value => value.id === id);
    if (!item) throw Error('插件已移除，请刷新已安装列表');
    $('#extension-detail-title').textContent = item.name;
    $('#extension-detail-body').innerHTML = '<p class="extension-description">' + escapeHtml(extensionDescription(item)) + '</p><p class="extension-note">' + escapeHtml(item.runtime === 'native-cordis-host' ? '通过本程序 Cordis Host 加载' : item.kind || '已安装扩展') + '</p><div id="extension-config-fields"></div>';
    const fields = $('#extension-config-fields');
    let value, save;
    if (item.kind === 'native-profile') {
      const form = await api('/native-profiles/' + encodeURIComponent(item.profile_name) + '/form');
      if (epoch !== extensionDetailEpoch) return;
      const read = window.NativeProfileForm.render(fields, form);
      save = () => api('/native-profiles/' + encodeURIComponent(item.profile_name) + '/form', 'PUT', {entries: read(), revision: form.revision});
    } else if (item.runtime === 'native-cordis-host') {
      const surface = await api('/dsh/plugins/' + encodeURIComponent(id) + '/surface');
      if (epoch !== extensionDetailEpoch) return;
      if (surface.available) {
        $('#extension-detail-dialog').classList.add('has-plugin-surface');
        $('#extension-detail-confirm').hidden = true;
        fields.innerHTML = '<div class="plugin-surface-toolbar"><span>插件设置</span></div><div id="plugin-client-root" class="plugin-client-root">正在加载插件页面…</div>';
        const url = '/api/dsh/plugins/' + encodeURIComponent(id) + '/surface/';
        const stylesheet = document.createElement('link'); stylesheet.rel = 'stylesheet'; stylesheet.href = url + 'client.css?revision=' + encodeURIComponent(surface.client_revision||item.updated_at||''); document.head.append(stylesheet);
        extensionSurfaceDispose = () => stylesheet.remove();
        const client = await importPluginClient(id,surface.client_revision||item.updated_at);
        if (epoch !== extensionDetailEpoch) { stylesheet.remove(); return; }
        const dispose = await client.mount($('#plugin-client-root'), {rpcUrl: '/api/dsh/plugins/' + encodeURIComponent(id) + '/rpc', settingsNamespaces:surface.settings_namespaces, sessionId: conversationId, model: () => {
          const profile = profiles.find(item => item.id === $('#chat-model-select').value);
          if (!profile) return null;
          try { const wire = JSON.parse(profile.model); if (Array.isArray(wire) && wire.length === 2) return {provider: wire[0], model: wire[1]}; } catch {}
          return {provider: profile.provider || 'micro-multi', model: profile.model};
        }});
        if (epoch !== extensionDetailEpoch) { dispose(); stylesheet.remove(); return; }
        extensionSurfaceDispose = () => { dispose(); stylesheet.remove(); };
        if (surface.provides_models) {
        const importButton = document.createElement('button'); importButton.type = 'button'; importButton.textContent = '同步插件模型到对话'; fields.querySelector('.plugin-surface-toolbar').append(importButton);
        importButton.addEventListener('click', async event => {
          event.currentTarget.disabled = true;
          try {
            const result = await api('/dsh/plugins/' + encodeURIComponent(id) + '/models/import', 'POST', {});
            profiles = await api('/model-profiles'); renderSelectors(); renderTeam();
            $('#extension-detail-status').textContent = result.models.length ? '已同步 ' + result.models.length + ' 个模型，可在对话中选择。' : '插件尚未提供模型。请先完成插件登录或配置，再同步。';
          } catch (error) { $('#extension-detail-status').textContent = error.message; }
          finally { event.currentTarget.disabled = false; }
        });
        }
        return;
      }
      const form = await api('/dsh/plugins/' + encodeURIComponent(id) + '/configuration');
      if (epoch !== extensionDetailEpoch) return;
      if (!form.editable || !form.entries.length) { fields.textContent = form.message || '此插件没有可调整参数。'; $('#extension-detail-confirm').hidden = true; return; }
      fields.innerHTML = form.entries.map((entry, index) => '<label class="extension-config-label">' + escapeHtml(entry.name) + '<textarea data-extension-config="' + index + '" rows="6" spellcheck="false">' + escapeHtml(JSON.stringify(entry.config, null, 2)) + '</textarea></label>').join('');
      if(surface.provides_models){
        const button=document.createElement('button');button.type='button';button.textContent='同步插件模型到对话';fields.prepend(button);
        button.addEventListener('click',async()=>{button.disabled=true;try{const result=await api('/dsh/plugins/'+encodeURIComponent(id)+'/models/import','POST',{});profiles=await api('/model-profiles');renderSelectors();renderTeam();$('#extension-detail-status').textContent='已同步 '+result.models.length+' 个模型。';}catch(error){$('#extension-detail-status').textContent=error.message;}finally{button.disabled=false;}});
      }
      save = () => api('/dsh/plugins/' + encodeURIComponent(id) + '/configuration', 'PUT', {revision: form.revision, entries: form.entries.map((entry, index) => ({key: entry.key, config: JSON.parse(fields.querySelector('[data-extension-config="' + index + '"]').value)}))});
    } else if (item.settings_key && item.config) {
      value = item.config;
      save = config => api('/dsh/settings', 'PUT', {[item.settings_key]: config});
    } else {
      const tool = inventory.tool_plugins.find(entry => entry.id === id);
      const server = inventory.mcp_servers.find(entry => entry.id === id && !entry.builtin);
      if (tool) { value = {name: tool.name, description: tool.description, command: tool.command, args: tool.args, parameters: tool.parameters, enabled: tool.configured_enabled ?? tool.enabled}; save = config => api('/plugins/' + encodeURIComponent(id), 'PUT', config); }
      else if (server) { value = server; save = config => api('/mcp-servers/' + encodeURIComponent(id), 'PUT', config); }
      else { fields.innerHTML = '<p>此扩展没有独立参数。可调用组件：</p><ul>' + (item.components || []).map(component => '<li>' + escapeHtml(component.type + '：' + component.name) + '</li>').join('') + '</ul>'; $('#extension-detail-confirm').hidden = true; return; }
    }
    if (value) fields.innerHTML = '<label class="extension-config-label">参数 · JSON<textarea id="extension-config-json" rows="12" spellcheck="false">' + escapeHtml(JSON.stringify(value, null, 2)) + '</textarea></label>';
    extensionDetailAction = async () => {
      await save(value ? JSON.parse($('#extension-config-json').value) : undefined);
      $('#extension-detail-status').textContent = '配置已验证并保存，下次调用使用新参数。';
      scheduleExtensionRefresh();
    };
    $('#extension-detail-confirm').disabled = false;
  } catch (error) { if (epoch === extensionDetailEpoch) $('#extension-detail-status').textContent = error.message; }
}
let extensionSurfaceDispose = null;
function disposeExtensionSurface() { try { extensionSurfaceDispose?.(); } finally { extensionSurfaceDispose = null; $('#extension-detail-dialog').classList.remove('has-plugin-surface'); } }
function closeExtensionDetail() { extensionDetailEpoch++; extensionDetailAction = null; disposeExtensionSurface(); $('#extension-detail-dialog').close(); }
$('#extension-detail-close').addEventListener('click', closeExtensionDetail);
$('#extension-detail-cancel').addEventListener('click', closeExtensionDetail);
$('#extension-detail-dialog').addEventListener('cancel', () => { extensionDetailEpoch++; extensionDetailAction = null; disposeExtensionSurface(); });
$('#extension-detail-confirm').addEventListener('click', async () => {
  const action = extensionDetailAction, epoch = extensionDetailEpoch;
  if (!action) return;
  $('#extension-detail-confirm').disabled = true;
  $('#extension-detail-status').textContent = '正在处理…';
  try { await action(); } catch (error) { if (epoch === extensionDetailEpoch) $('#extension-detail-status').textContent = error.message; }
  finally { if (epoch === extensionDetailEpoch) $('#extension-detail-confirm').disabled = false; }
});
$('#market-add').addEventListener('click', () => { $('#market-installed').click(); $('#plugins-panel').classList.add('extension-adding'); $('#dsh-plugin-path').focus(); });
let marketOffset = 0;
let marketCategory = '';
let marketCategories = {};
let marketQueryTimer;
let marketRequest = 0;
async function loadMarket(append = false) {
  $('#plugins-panel').classList.add('market-browsing');
  $('#plugins-panel').classList.remove('extension-adding');
  $('#market-category-bar').hidden = false;
  $('#market-discover').classList.add('selected');
  $('#market-installed').classList.remove('selected');
  const request = ++marketRequest;
  if (!append) marketOffset = 0;
  $('#market-results').hidden = false;
  if (!append) $('#market-results').textContent = '正在读取 dsh 市场…';
  try {
    const data = await api('/dsh/market?q=' + encodeURIComponent($('#market-search').value) + '&offset=' + marketOffset + '&category=' + encodeURIComponent(marketCategory) + '&sort=' + encodeURIComponent($('#market-sort').value));
    if (request !== marketRequest) return;
    data.plugins.forEach(item => marketEntries.set(item.name, item));
    marketCategories = data.categories || {};
    const categoryName = key => typeof marketCategories[key] === 'object' ? (marketCategories[key].zh || marketCategories[key]['zh-CN'] || marketCategories[key].en || key) : marketCategories[key] || key;
    const categoryKeys = Object.keys(marketCategories);
    const renderCategory = key => '<button type="button" data-market-category="' + escapeHtml(key) + '" class="' + (marketCategory === key ? 'selected' : '') + '">' + escapeHtml(categoryName(key)) + '</button>';
    const topCategories = categoryKeys.slice(0, 8);
    if (marketCategory && !topCategories.includes(marketCategory)) topCategories.push(marketCategory);
    $('#market-categories').innerHTML = '<button type="button" data-market-category="" class="' + (!marketCategory ? 'selected' : '') + '">全部</button>' + topCategories.map(renderCategory).join('') + (categoryKeys.length > 8 ? '<details class="market-more-categories"><summary>更多分类 ⌄</summary><div>' + categoryKeys.filter(key => !topCategories.includes(key)).map(renderCategory).join('') + '</div></details>' : '');
    const html = data.plugins.map(item => {
      const category = Array.isArray(item.category) ? item.category[0] : item.category;
      const url = safeExtensionUrl(item.url);
      const shots = (item.screenshots || []).filter(value => { try { return ['github.com','raw.githubusercontent.com','user-images.githubusercontent.com'].includes(new URL(value).hostname) && new URL(value).protocol === 'https:'; } catch { return false; } }).slice(0,2);
      return '<article class="market-card"><div class="market-card-head"><div class="market-card-title"><strong title="' + escapeHtml(item.name) + '">' + escapeHtml(item.name) + '</strong><small>' + escapeHtml(item.owner || '') + (item.downloads != null ? ' · ↓ ' + Number(item.downloads).toLocaleString() : '') + '<br>★ ' + Number(item.stars || 0).toLocaleString() + '</small></div><button type="button" class="market-install" data-market-install="' + escapeHtml(item.name) + '">安装</button></div><p>' + escapeHtml(extensionDescription(item)) + '</p>' + (shots.length ? '<div class="market-card-shots">' + shots.map(value => '<img src="' + escapeHtml(value) + '" alt="插件预览" loading="lazy" referrerpolicy="no-referrer">').join('') + '</div>' : '') + '<div class="market-card-foot"><span class="market-category-tag">' + escapeHtml(categoryName(category) || '插件') + '</span>' + (url ? '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer">项目说明 ↗</a>' : '') + '</div></article>';
    }).join('');
    $('#market-results').querySelector('[data-market-more]')?.remove();
    if (append) $('#market-results .market-grid').insertAdjacentHTML('beforeend', html);
    else $('#market-results').innerHTML = '<p class="panel-help">dsh-market 目录 · ' + data.total + ' 个结果</p><div class="market-grid">' + html + '</div>';
    marketOffset += data.plugins.length;
    if (marketOffset < data.total) $('#market-results').insertAdjacentHTML('beforeend', '<button type="button" data-market-more>加载更多</button>');
    if (!data.total) $('#market-results').insertAdjacentHTML('beforeend', '<p>未找到匹配插件。</p>');
  } catch (error) { if (request === marketRequest) $('#market-results').textContent = '市场暂不可用：' + error.message; }
}
$('#market-discover').addEventListener('click', () => loadMarket());
$('#market-installed').addEventListener('click', () => { $('#plugins-panel').classList.remove('market-browsing', 'extension-adding'); $('#market-results').hidden = true; $('#market-category-bar').hidden = true; $('#market-installed').classList.add('selected'); $('#market-discover').classList.remove('selected'); activePluginTab = 'installed'; scheduleExtensionRefresh(); });
$('#market-categories').addEventListener('click', event => { const button = event.target.closest('[data-market-category]'); if (button) { marketCategory = button.dataset.marketCategory; loadMarket(); } });
$('#market-sort').addEventListener('change', () => loadMarket());
$('#market-refresh').addEventListener('click', () => { scheduleExtensionRefresh(); if (!$('#market-results').hidden) loadMarket(); });
$('#market-search').addEventListener('input', () => { clearTimeout(marketQueryTimer); marketQueryTimer = setTimeout(() => loadMarket(), 300); });
$('#market-results').addEventListener('click', async event => {
  if (event.target.closest('[data-market-more]')) return loadMarket(true);
  const button = event.target.closest('[data-market-install]');
  if (!button) return;
  openMarketDetail(button.dataset.marketInstall);
});
$('#settings-install-plugin-btn')?.addEventListener('click', () => installPluginFromInput('#settings-install-plugin-path', '#settings-install-plugin-feedback'));

async function handleDshInventoryClick(event) {
  const detail = event.target.closest('[data-extension-detail]');
  if (detail) return openInstalledDetail(detail.dataset.extensionDetail);
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.dshToggle) {
    try {
      await api('/dsh/plugins/toggle', 'POST', {
        id: button.dataset.dshToggle,
        enabled: button.dataset.dshEnabled === 'true',
      });
      await loadPlugins();
      await loadMcpServers();
    } catch (error) { toast(error.message, true); }
  } else if (button.dataset.dshProbeMcp) {
    const srvId = button.dataset.dshProbeMcp;
    const statusNodes = document.querySelectorAll('[data-dsh-probe-result="' + CSS.escape(srvId) + '"]');
    statusNodes.forEach((n) => { n.textContent = '正在检测工具…'; n.classList.remove('error'); });
    try {
      const projParam = currentProjectId() ? '?project_id=' + encodeURIComponent(currentProjectId()) : '';
      const result = await api('/mcp-servers/' + encodeURIComponent(srvId) + '/probe' + projParam, 'POST', {});
      statusNodes.forEach((n) => { n.textContent = '连接正常 · 共 ' + result.tools.length + ' 个工具：' + result.tools.map((t) => t.name).join('、'); });
    } catch (error) {
      statusNodes.forEach((n) => { n.textContent = error.message; n.classList.add('error'); });
    }
  } else if (button.dataset.dshDeleteBundle) {
    try {
      await api('/dsh/bundles/' + encodeURIComponent(button.dataset.dshDeleteBundle), 'DELETE', {});
      await loadPlugins();
    } catch (error) { toast(error.message, true); }
  }
}
$('#dsh-plugin-overview')?.addEventListener('click', handleDshInventoryClick);
$('#settings-plugin-inventory')?.addEventListener('click', handleDshInventoryClick);

$('#plugin-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const values = new FormData(event.target);
  try {
    await api('/plugins', 'POST', {
      name: values.get('name'), description: values.get('description'),
      command: values.get('command'),
      args: String(values.get('args') || '').split('\n').map((item) => item.trim()).filter(Boolean),
      parameters: JSON.parse(String(values.get('parameters'))),
      enabled: values.has('enabled'),
    });
    event.target.reset();
    await loadPlugins();
    setFeedback('#plugin-feedback', '插件已保存。');
  } catch (error) { setFeedback('#plugin-feedback', error.message, true); }
});
$('#plugin-list').addEventListener('click', async (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  const id = button.dataset.pluginToggle || button.dataset.pluginDelete;
  const plugin = (window.maspPlugins || []).find((item) => item.id === id);
  if (!plugin) return;
  try {
    if (button.dataset.pluginToggle) {
      await api('/plugins/' + encodeURIComponent(id), 'PUT', {
        name: plugin.name, description: plugin.description,
        command: plugin.command, args: plugin.args,
        parameters: plugin.parameters, enabled: !plugin.enabled,
      });
    } else {
      await api('/plugins/' + encodeURIComponent(id), 'DELETE', {});
    }
    await loadPlugins();
    setFeedback('#plugin-feedback', button.dataset.pluginToggle ? '插件状态已更新。' : '插件已删除。');
  } catch (error) { setFeedback('#plugin-feedback', error.message, true); }
});
$('#run-list').addEventListener('click', (event) => {
  const id = event.target.closest('[data-run]')?.dataset.run;
  if (id) { showRun(id); watchRun(id); }
});
$('#run-detail').addEventListener('click', async (event) => {
  const followup = event.target.closest('[data-followup]')?.dataset.followup;
  if (followup) {
    feedbackRunId = followup;
    $('#prompt').value = '请根据上一轮 ' + followup + ' 的结果修改：';
    $('#prompt').focus();
    return;
  }
  const action = event.target.closest('[data-run-action]')?.dataset.runAction;
  if (!action || !selectedRunId) return;
  try {
    await api('/runs/' + encodeURIComponent(selectedRunId) + '/' + action, 'POST', {});
    await showRun(selectedRunId);
  } catch (error) { $('#run-detail').insertAdjacentHTML('beforeend', '<p class="feedback error">' + escapeHtml(error.message) + '</p>'); }
});
$('#toggle-inspector').addEventListener('click', () => document.body.classList.toggle('inspector-closed'));
$('#close-inspector').addEventListener('click', () => {
  $('#inspector')?.classList.remove('review-fullscreen');
  document.body.classList.add('inspector-closed');
});
$('#toggle-sidebar').addEventListener('click', () => document.body.classList.toggle('sidebar-closed'));
$('#header-expand-sidebar')?.addEventListener('click', () => document.body.classList.remove('sidebar-closed'));
$('#header-open-workflow')?.addEventListener('click', () => {
  showLeftTool('team');
  openTeamReview({ fullscreen: false });
});
$('#header-open-changes')?.addEventListener('click', () => {
  document.body.classList.remove('inspector-closed');
  showWorkspacePanel('changes', true, null);
});
$('#header-open-review')?.addEventListener('click', () => {
  document.body.classList.remove('inspector-closed');
  showWorkspacePanel('review', false);
});

let isChatExecutionPaused = false;

async function pauseCurrentChat() {
  if (!conversationId) return;
  try {
    await api('/conversations/' + encodeURIComponent(conversationId) + '/pause', 'POST');
    isChatExecutionPaused = true;
    updatePauseButtons(true);
    toast('对话已暂停。可在导图中调整子代理路由模型与任务内容。');
    loadTeam();
  } catch (err) {
    toast('暂停失败: ' + err.message, true);
  }
}

async function resumeCurrentChat(updatedSubagents = null) {
  if (!conversationId) return;
  try {
    const body = updatedSubagents ? { subagents: updatedSubagents } : null;
    await api('/conversations/' + encodeURIComponent(conversationId) + '/resume', 'POST', body);
    isChatExecutionPaused = false;
    updatePauseButtons(false);
    toast('对话已恢复，继续执行任务。');
    loadTeam();
  } catch (err) {
    toast('恢复失败: ' + err.message, true);
  }
}

function updatePauseButtons(isPaused) {
  const btn = $('#header-pause-chat');
  if (btn) {
    btn.classList.toggle('is-paused', isPaused);
    btn.innerHTML = isPaused
      ? '<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"><path d="m11.596 8.697-6.363 3.692c-.54.313-1.233-.066-1.233-.697V4.308c0-.63.692-1.01 1.233-.696l6.363 3.692a.802.802 0 0 1 0 1.393z"/></svg> 恢复对话'
      : '<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"><path d="M5.5 3.5A1.5 1.5 0 0 1 7 5v6a1.5 1.5 0 0 1-3 0V5a1.5 1.5 0 0 1 1.5-1.5zm5 0A1.5 1.5 0 0 1 12 5v6a1.5 1.5 0 0 1-3 0V5a1.5 1.5 0 0 1 1.5-1.5z"/></svg> 暂停对话';
    btn.title = isPaused ? '恢复对话执行' : '暂停对话执行';
  }
  const modalToggle = $('#team-review-pause-toggle');
  if (modalToggle) {
    modalToggle.textContent = isPaused ? '恢复对话' : '暂停对话';
  }
}

$('#header-pause-chat')?.addEventListener('click', () => {
  if (isChatExecutionPaused) resumeCurrentChat();
  else pauseCurrentChat();
});
$('#team-review-pause-toggle')?.addEventListener('click', () => {
  if (isChatExecutionPaused) resumeCurrentChat();
  else pauseCurrentChat();
});
$('#team-review-resume-btn')?.addEventListener('click', () => {
  if (!$('#team-review-editor')?.hidden) syncModalEditorToTeam();
  resumeCurrentChat(team?.agents || null);
});
$('#brand-home').addEventListener('click', () => startNewChat(null));
$('#composer-project').addEventListener('click', async () => {
  const menu = $('#composer-add-menu');
  menu.hidden = !menu.hidden;
  if (menu.hidden) return;
  menu.innerHTML = '<button type="button" data-add-files>' + attachmentMenuIcon + '<strong>文件和文件夹</strong></button><small>插件、技能与 MCP</small><p>正在读取已安装能力…</p>';
  try {
    const data = await api('/dsh/plugins' + (currentProjectId() ? '?project_id=' + encodeURIComponent(currentProjectId()) : ''));
    const entries = [...(data.installed || []), ...(data.tool_plugins || []), ...(data.skills || []), ...(data.mcp_servers || [])].filter(item => item.enabled !== false && item.runtime !== 'native-surface');
    menu.innerHTML = '<button type="button" data-add-files>' + attachmentMenuIcon + '<strong>文件和文件夹</strong></button><small>插件、技能与 MCP</small>' + entries.map(item => '<button type="button" data-select-extension="' + escapeHtml(item.name) + '" data-extension-runtime="' + escapeHtml(item.runtime || '') + '"><strong>' + escapeHtml(item.name) + '</strong><span>' + escapeHtml(item.description || item.kind || '') + '</span></button>').join('') + (!entries.length ? '<p>暂无已启用能力</p>' : '');
  } catch (error) { menu.innerHTML = '<p>' + escapeHtml(error.message) + '</p>'; }
});
$('#composer-add-menu').addEventListener('click', event => {
  if (event.target.closest('[data-add-files]')) $('#attachment-input').click();
  const extension = event.target.closest('[data-select-extension]');
  if (extension) {
    $('#prompt').value = '请使用「' + extension.dataset.selectExtension + '」：' + $('#prompt').value;
    $('#prompt').focus();
  }
  $('#composer-add-menu').hidden = true;
});
document.addEventListener('click', async event => {
  const button = event.target.closest('[data-team-document]');
  if (button) { try { closeCustomizationPage(); await openWorkspaceFile(button.dataset.teamDocument); } catch (error) { toast(error.message, true); } }
});
document.addEventListener('click', event => {
  if (!event.target.closest('#composer-add-menu, #composer-project')) $('#composer-add-menu').hidden = true;
});
window.maspDesktop?.externalApplications().then(apps => {
  for (const app of apps) $('#workspace-open-with').add(new Option(app.name, app.id));
}).catch(error => toast(error.message, true));
$('#workspace-open-with').addEventListener('change', async event => {
  const application = event.target.value;
  event.target.value = '';
  if (!application || !selectedWorkspaceFile) return;
  if (!window.maspDesktop) return toast('外部打开功能需要桌面应用。', true);
  try {
    const file = await api('/projects/' + encodeURIComponent(activeWorkspaceId()) + '/workspace/external-path?path=' + encodeURIComponent(selectedWorkspaceFile));
    await window.maspDesktop.openFileWith(file.path, application);
  } catch (error) { toast(error.message, true); }
});
async function addAttachments(files) {
  for (const file of files) {
    if (pendingAttachments.length >= 5) { toast('每条消息最多添加 5 个文件。', true); break; }
    if (file.size > 10 * 1024 * 1024) { toast(file.name + ' 超过 10 MB 附件上限。', true); continue; }
    const total = pendingAttachments.reduce((sum, item) => sum + Number(item.size || 0), 0);
    if (total + file.size > 25 * 1024 * 1024) { toast('附件总大小不能超过 25 MB。', true); break; }
    try {
      const image = ['image/png','image/jpeg','image/webp','image/gif'].includes(file.type);
      const textType = !image && (file.type.startsWith('text/') || /\.(txt|md|py|js|ts|tsx|jsx|json|ya?ml|toml|html|css|sql|log|xml|csv)$/i.test(file.name));
      if (textType && file.size <= maxAttachmentBytes) {
        const content = await file.text();
        if (!content.includes('\0')) {
          pendingAttachments.push({name:file.name, content, kind:'text', size:String(file.size)});
          continue;
        }
      }
      const data_url = await new Promise((resolve,reject) => {
        const reader = new FileReader(); reader.onload=()=>resolve(reader.result); reader.onerror=()=>reject(reader.error); reader.readAsDataURL(file);
      });
      pendingAttachments.push({name:file.name || 'clipboard.png', content:'', data_url, kind:image?'image':'file', mime_type:file.type || 'application/octet-stream', size:String(file.size)});
    } catch(error) { toast('无法读取 ' + file.name + '：' + error.message, true); }
  }
  renderAttachments();
}
$('#attachment-input').addEventListener('change', async event => {
  const files=Array.from(event.target.files || []);event.target.value='';await addAttachments(files);
});
async function pasteAttachments(event) {
  let files = Array.from(event.clipboardData?.files || []);
  if (files.length) event.preventDefault();
  else if (window.maspDesktop?.readClipboardFiles) {
    const copied = await window.maspDesktop.readClipboardFiles();
    files = copied.map(item => new File([Uint8Array.from(atob(item.data), c => c.charCodeAt(0))], item.name, {type:item.mime}));
  }
  if (!files.length) return;
  await addAttachments(files);
  $('#prompt').focus();
}
$('.composer-wrap').addEventListener('paste', pasteAttachments);
$('#thread').addEventListener('paste', pasteAttachments);
$('.composer-wrap').addEventListener('dragover', event => {if(event.dataTransfer.types.includes('Files'))event.preventDefault();});
$('.composer-wrap').addEventListener('drop', async event => {if(event.dataTransfer.files.length){event.preventDefault();await addAttachments(Array.from(event.dataTransfer.files));}});
$('#attachment-list').addEventListener('click', (event) => {
  const index = Number(event.target.closest('[data-remove-attachment]')?.dataset.removeAttachment);
  if (!Number.isInteger(index)) return;
  pendingAttachments.splice(index, 1);
  renderAttachments();
});

document.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', async () => {
  const action = button.dataset.action;
  button.closest('details')?.removeAttribute('open');
  if (action === 'new-chat') return startNewChat(null);
  if (action === 'new-project') return $('#new-project').click();
  if (action === 'focus-prompt') return $('#prompt').focus();
  if (action === 'clear-prompt') { $('#prompt').value = ''; $('#prompt').focus(); return; }
  if (action === 'toggle-sidebar') return $('#toggle-sidebar').click();
  if (action === 'toggle-inspector') return $('#toggle-inspector').click();
  if (action === 'help') return openSettingsPage();
  if (action === 'copy-answer') {
    const answers = [...thread.querySelectorAll('.message.assistant .bubble')];
    const latest = answers.at(-1)?.textContent?.trim();
    if (!latest) return toast('当前对话还没有可复制的回复。', true);
    try { await navigator.clipboard.writeText(latest); toast('最近一条回复已复制。'); }
    catch { toast('复制失败，请检查浏览器剪贴板权限。', true); }
  }
}));

document.addEventListener('click', (event) => {
  if (!event.target.closest('.menu-item')) {
    document.querySelectorAll('.menu-item[open]').forEach((menu) => menu.removeAttribute('open'));
  }
});
document.querySelectorAll('.menu-item').forEach((menu) => menu.addEventListener('toggle', () => {
  if (!menu.open) return;
  document.querySelectorAll('.menu-item[open]').forEach((other) => {
    if (other !== menu) other.removeAttribute('open');
  });
}));
$('#sidebar-search').addEventListener('click', () => { $('#search-dialog').showModal(); $('#conversation-search').focus(); });
let globalSearchSequence = 0;
$('#conversation-search').addEventListener('input', async () => {
  const q = $('#conversation-search').value.trim();
  const sequence = ++globalSearchSequence;
  if (!q) { $('#search-results').replaceChildren(); return; }
  try {
    const results = await api('/search/global?q=' + encodeURIComponent(q));
    if (sequence !== globalSearchSequence) return;
    const group = (title, items, render) => (items && items.length) ? '<section class="global-search-group"><h3>' + title + '</h3>' + items.map(render).join('') + '</section>' : '';
    const content = group('聊天', results.chats, (item) => '<button type="button" class="search-result" data-search-id="' + escapeHtml(item.id) + '"><strong>' + escapeHtml(item.title) + '</strong><small>' + (item.match === 'content' ? '匹配到对话内容' : '匹配到标题') + '</small></button>')
      + group('项目', results.projects, (item) => '<button type="button" class="search-result" data-search-project="' + escapeHtml(item.id) + '"><strong>' + escapeHtml(item.name) + '</strong><small>' + escapeHtml(item.repository) + '</small></button>')
      + group('项目文件', results.files, (item) => '<button type="button" class="search-result" data-search-file="' + escapeHtml(item.project_id) + '" data-file-path="' + escapeHtml(item.path) + '"><strong>' + escapeHtml(item.path) + '</strong><small>' + escapeHtml(item.project) + ' · ' + (item.match === 'content' ? '匹配到文件内容' : '匹配到文件名') + '</small></button>')
      + group('插件与扩展', results.plugins, (item) => '<button type="button" class="search-result" data-search-plugin="' + escapeHtml(item.id) + '"><strong>' + escapeHtml(item.title) + '</strong><small>' + escapeHtml(item.kind + (item.description ? ' · ' + item.description : '')) + '</small></button>')
      + group('设置', results.settings, (item) => '<button type="button" class="search-result" data-search-settings="' + escapeHtml(item.section) + '"><strong>' + escapeHtml(item.title) + '</strong><small>打开全局设置</small></button>');
    const actions = group('应用内操作', results.actions, (item) => '<button type="button" class="search-result" data-search-action="' + escapeHtml(item.id) + '"><strong>' + escapeHtml(item.title) + '</strong></button>');
    $('#search-results').innerHTML = content + actions || '<p class="empty">没有匹配的内容。</p>';
  } catch (error) { if (sequence === globalSearchSequence) $('#search-results').textContent = error.message; }
});
$('#search-results').addEventListener('click', async (event) => {
  const item = event.target.closest('[data-search-id], [data-search-project], [data-search-settings], [data-search-file], [data-search-plugin], [data-search-action]');
  if (!item) return;
  $('#search-dialog').close();
  $('#conversation-search').value = '';
  if (item.dataset.searchId) await openConversation(item.dataset.searchId);
  else if (item.dataset.searchProject) await startNewChat(item.dataset.searchProject);
  else if (item.dataset.searchFile) {
    if (conversationId && conversations.find((entry) => entry.id === conversationId)?.message_count && draftProjectId !== item.dataset.searchFile) {
      await startNewChat(item.dataset.searchFile);
    } else {
      draftProjectId = item.dataset.searchFile;
      $('#project-select').value = draftProjectId;
      updateContextLabels();
      await loadTeam();
      await loadWorkspaceFiles('');
    }
    await openWorkspaceFile(item.dataset.filePath);
    document.body.classList.remove('inspector-closed');
  } else if (item.dataset.searchPlugin) {
    closeSettingsPage();
    showLeftTool('plugins');
  } else if (item.dataset.searchAction === 'new-chat') await startNewChat(null);
  else if (item.dataset.searchAction === 'new-project' || item.dataset.searchAction === 'open-folder') $('#project-dialog').showModal();
  else if (item.dataset.searchAction === 'open-plugins') { closeSettingsPage(); showLeftTool('plugins'); }
  else if (item.dataset.searchAction === 'open-settings') openSettingsPage('general');
  else if (item.dataset.searchSettings) openSettingsPage(item.dataset.searchSettings);
});
$('#search-close').addEventListener('click', () => $('#search-dialog').close());
document.querySelectorAll('[data-rail]').forEach((button) => button.addEventListener('click', () => {
  if (!['plugins', 'skills', 'mcp'].includes(button.dataset.rail)) closeCustomizationPage();
  const target = button.dataset.rail;
  if (target === 'settings') return openSettingsPage();
  closeSettingsPage();
  document.querySelectorAll('[data-rail]').forEach((item) => item.classList.toggle('rail-active', item === button));
  if (['repository', 'team', 'models', 'skills', 'mcp', 'plugins', 'runs'].includes(target)) {
    showLeftTool(target);
  } else if (target === 'home') {
    document.body.classList.remove('sidebar-tools-mode');
    closeSettingsPage();
  }
}));
document.querySelectorAll('[data-workspace-panel]').forEach((button) =>
  button.addEventListener('click', () => showWorkspacePanel(button.dataset.workspacePanel)));
$('#workspace-breadcrumbs').addEventListener('click', (event) => {
  const folder = event.target.closest('[data-folder]')?.dataset.folder;
  if (folder !== undefined) loadWorkspaceFiles(folder);
});
async function handleTreeToggle(event) {
  const folder = event.target;
  if (!folder.matches('details[data-directory]') || !folder.open || folder.dataset.loaded) return;
  const wsId = activeWorkspaceId();
  const children = folder.querySelector('.tree-children');
  if (!children) return;
  children.textContent = '正在读取…';
  try {
    const entries = await api('/projects/' + encodeURIComponent(wsId) + '/workspace/files?path=' + encodeURIComponent(folder.dataset.directory));
    if (wsId !== activeWorkspaceId()) return;
    children.innerHTML = repositoryEntries(entries);
    folder.dataset.loaded = 'true';
  } catch (error) { children.textContent = error.message; }
}
$('#repo-tree').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-path]');
  if (!button) return;
  if (button.dataset.entryType === 'directory') return loadWorkspaceFiles(button.dataset.path);
  await openWorkspaceFile(button.dataset.path);
});
$('#repo-tree').addEventListener('toggle', handleTreeToggle, true);
$('#workspace-file-list').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-path]');
  if (!button) return;
  if (button.dataset.entryType === 'directory') return loadWorkspaceFiles(button.dataset.path);
  await openWorkspaceFile(button.dataset.path);
});
$('#workspace-file-list').addEventListener('toggle', handleTreeToggle, true);
$('#workspace-review-current-file')?.addEventListener('click', async () => {
  if (!selectedWorkspaceFile) return toast('请先选择一个文件。', true);
  showWorkspacePanel('review', false);
  await runSelectedFilesReview([selectedWorkspaceFile]);
});
$('#workspace-changes-show-all')?.addEventListener('click', () => {
  $('#workspace-diff').innerHTML = renderChangesCardsHtml(cachedWorkspaceChanges.files || []);
});
$('#workspace-changes-refresh')?.addEventListener('click', () => loadWorkspaceChanges());
$('#workspace-review-run')?.addEventListener('click', () => runSelectedFilesReview());

function syncInspectorFullscreenButtons() {
  const isFull = Boolean($('#inspector')?.classList.contains('review-fullscreen'));
  const expandSvg = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10"/></svg>';
  const collapseSvg = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 2.5V6H2.5M10 2.5V6h3.5M13.5 10H10v3.5M2.5 10H6v3.5"/></svg>';
  const labelText = isFull ? '退出全屏' : '全屏视图';
  const buttons = [
    $('#workspace-review-fullscreen'),
    $('#inspector-fullscreen-toggle'),
    ...document.querySelectorAll('[data-toggle-inspector-fullscreen]'),
  ].filter(Boolean);
  for (const btn of new Set(buttons)) {
    btn.innerHTML = isFull ? collapseSvg : expandSvg;
    btn.title = labelText;
    btn.setAttribute('aria-label', labelText);
  }
}

$('#workspace-review-fullscreen')?.addEventListener('click', () => {
  const insp = $('#inspector');
  if (!insp) return;
  insp.classList.toggle('review-fullscreen');
  syncInspectorFullscreenButtons();
});

$('#inspector')?.addEventListener('click', (event) => {
  const addReviewModelBtn = event.target.closest('[data-open-add-review-model]');
  if (addReviewModelBtn) {
    showLeftTool('models');
    $('#model-form input[name="name"]')?.focus();
    toast('请在左侧模型面板添加或编辑审查模型配置');
    return;
  }
  const rerunReviewBtn = event.target.closest('[data-rerun-open-code-review]');
  if (rerunReviewBtn) {
    runSelectedFilesReview(lastReviewedPaths);
    return;
  }
  const fullBtn = event.target.closest('[data-toggle-inspector-fullscreen]');
  if (fullBtn) {
    const insp = $('#inspector');
    if (insp) {
      insp.classList.toggle('review-fullscreen');
      syncInspectorFullscreenButtons();
    }
    return;
  }
  const expandBtn = event.target.closest('[data-expand-step], [data-expand-all]');
  if (expandBtn) {
    const expander = expandBtn.closest('.ide-diff-expander');
    const gapKey = expander?.dataset?.gapKey;
    const state = gapKey ? ideGapStore.get(gapKey) : null;
    if (!expander || !state || !state.remainingLines.length) {
      expander?.remove();
      return;
    }
    const isAll = Boolean(expandBtn.dataset.expandAll);
    const step = isAll ? state.remainingLines.length : Number(expandBtn.dataset.expandStep || 10);
    const chunk = state.remainingLines.splice(0, step);
    const rowsHtml = chunk.map((ln) =>
      renderIdeCodeRowHtml(state.filePath, ln, state.ext)
    ).join('');
    expander.insertAdjacentHTML('beforebegin', rowsHtml);
    if (state.remainingLines.length === 0) {
      ideGapStore.delete(gapKey);
      expander.remove();
    } else {
      const allBtn = expander.querySelector('[data-expand-all]');
      if (allBtn) allBtn.textContent = '+' + state.remainingLines.length + ' more lines';
    }
  }
});

function collectConversationTurns() {
  const userNodes = [...thread.querySelectorAll('.message.user')];
  return userNodes.map((userEl) => {
    let next = userEl.nextElementSibling;
    let assistantEl = null;
    while (next && !next.classList.contains('user')) {
      if (next.classList.contains('assistant')) {
        assistantEl = next;
        break;
      }
      next = next.nextElementSibling;
    }
    const userBubble = userEl.querySelector('.bubble');
    const userText = String(userBubble?.dataset?.rawContent || userBubble?.textContent || '').trim();
    let assistantText = '';
    if (assistantEl) {
      const textBlocks = [...assistantEl.querySelectorAll('.assistant-segment-text, .bubble')];
      assistantText = textBlocks.map((b) => String(b.dataset?.rawContent || b.textContent || '').trim()).filter(Boolean).join(' ');
    }
    return {
      userEl,
      assistantEl,
      userText: userText || '用户提问',
      assistantText: assistantText || '正在处理或已执行工具操作…',
    };
  });
}

let cachedConversationTurns = [];
let isDraggingTurnRail = false;

function syncActiveTurnTickFromScroll() {
  const ticksWrap = $('#chat-turn-rail-ticks');
  if (!ticksWrap || !cachedConversationTurns.length) return;
  const scrollMid = thread.scrollTop + thread.clientHeight * 0.28;
  let activeIdx = 0;
  for (let i = 0; i < cachedConversationTurns.length; i += 1) {
    const el = cachedConversationTurns[i].userEl;
    if (el && el.offsetTop <= scrollMid) {
      activeIdx = i;
    }
  }
  const ticks = [...ticksWrap.querySelectorAll('.chat-turn-tick')];
  ticks.forEach((t, idx) => t.classList.toggle('is-active', idx === activeIdx));
}

function updateChatTurnRail() {
  const rail = $('#chat-turn-rail');
  const ticksWrap = $('#chat-turn-rail-ticks');
  const popover = $('#turn-rail-popover');
  if (!rail || !ticksWrap) return;
  cachedConversationTurns = collectConversationTurns();
  if (!cachedConversationTurns.length) {
    rail.hidden = true;
    if (popover) popover.hidden = true;
    ticksWrap.innerHTML = '';
    return;
  }
  rail.hidden = false;
  ticksWrap.innerHTML = cachedConversationTurns.map((_, idx) =>
    '<span class="chat-turn-tick" data-turn-index="' + idx + '"></span>'
  ).join('');
  syncActiveTurnTickFromScroll();
}

function resolveTurnIndexFromClientY(clientY) {
  const ticksWrap = $('#chat-turn-rail-ticks');
  if (!ticksWrap || !cachedConversationTurns.length) return -1;
  const rect = ticksWrap.getBoundingClientRect();
  if (rect.height <= 0) return 0;
  const ratio = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
  return Math.min(cachedConversationTurns.length - 1, Math.floor(ratio * cachedConversationTurns.length));
}

function showTurnRailPopoverForIndex(idx) {
  const popover = $('#turn-rail-popover');
  const ticksWrap = $('#chat-turn-rail-ticks');
  if (!popover || !ticksWrap) return;
  const turn = cachedConversationTurns[idx];
  if (!turn) {
    popover.hidden = true;
    return;
  }
  const ticks = [...ticksWrap.querySelectorAll('.chat-turn-tick')];
  ticks.forEach((t, i) => t.classList.toggle('is-hovered', i === idx));
  popover.innerHTML =
    '<div class="turn-rail-popover-user">' + escapeHtml(turn.userText) + '</div>' +
    '<div class="turn-rail-popover-assistant">' + escapeHtml(turn.assistantText) + '</div>';
  popover.hidden = false;
}

function scrollToConversationTurn(idx, instant = false) {
  const turn = cachedConversationTurns[idx];
  if (!turn?.userEl) return;
  const targetTop = Math.max(0, turn.userEl.offsetTop - 16);
  if (instant) {
    thread.scrollTop = targetTop;
  } else {
    thread.scrollTo({ top: targetTop, behavior: 'smooth' });
  }
  syncActiveTurnTickFromScroll();
}

const turnRailEl = $('#chat-turn-rail');
if (turnRailEl) {
  turnRailEl.addEventListener('pointerenter', () => {
    turnRailEl.classList.add('is-active');
  });
  turnRailEl.addEventListener('pointermove', (event) => {
    if (!cachedConversationTurns.length) return;
    turnRailEl.classList.add('is-active');
    const idx = resolveTurnIndexFromClientY(event.clientY);
    if (idx < 0) return;
    showTurnRailPopoverForIndex(idx);
    if (isDraggingTurnRail) {
      scrollToConversationTurn(idx, true);
    }
  });
  turnRailEl.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || !cachedConversationTurns.length) return;
    isDraggingTurnRail = true;
    turnRailEl.classList.add('is-active');
    turnRailEl.setPointerCapture?.(event.pointerId);
    const idx = resolveTurnIndexFromClientY(event.clientY);
    if (idx >= 0) {
      showTurnRailPopoverForIndex(idx);
      scrollToConversationTurn(idx, false);
    }
  });
  const endTurnRailDrag = () => {
    isDraggingTurnRail = false;
    turnRailEl.classList.remove('is-active');
    const popover = $('#turn-rail-popover');
    if (popover) popover.hidden = true;
    document.querySelectorAll('#chat-turn-rail-ticks .chat-turn-tick.is-hovered').forEach((t) =>
      t.classList.remove('is-hovered'));
  };
  turnRailEl.addEventListener('pointerup', endTurnRailDrag);
  turnRailEl.addEventListener('pointercancel', endTurnRailDrag);
  turnRailEl.addEventListener('pointerleave', () => {
    if (!isDraggingTurnRail) endTurnRailDrag();
  });
}
thread.addEventListener('scroll', () => {
  if (!isDraggingTurnRail) syncActiveTurnTickFromScroll();
}, { passive: true });
$('#terminal-clear')?.addEventListener('click', () => {
  $('#terminal-output').textContent = '';
});
$('#terminal-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const wsId = activeWorkspaceId();
  if (!wsId) { $('#terminal-output').textContent = '请先选择项目或开始对话。'; return; }
  const command = $('#terminal-command').value.trim();
  $('#terminal-output').textContent = '正在运行：' + command;
  try {
    const result = await api('/projects/' + encodeURIComponent(wsId) + '/workspace/command',
      'POST', { command, timeout_seconds: Number($('#setting-command-timeout').value) });
    $('#terminal-output').textContent = '$ ' + command + '\n退出码：' + result.exit_code +
      '\n' + (result.stdout || '') + (result.stderr ? '\n' + result.stderr : '');
    await loadWorkspaceFiles(workspaceFolder);
    await loadWorkspaceChanges();
  } catch (error) { $('#terminal-output').textContent = error.message; }
});
$('#new-project').addEventListener('click', () => {
  const saved = JSON.parse(localStorage.getItem('masp.settings') || '{}');
  $('#project-form').elements.link_repository.checked = saved.linkProjects !== false;
  $('#project-dialog').showModal();
});
$('#close-project').addEventListener('click', () => $('#project-dialog').close());
$('#choose-repository').addEventListener('click', async () => {
  if (!window.maspDesktop?.isDesktop) {
    toast('请在桌面应用中使用原生目录选择器，或直接粘贴文件夹路径。', true);
    return;
  }
  const path = await window.maspDesktop.chooseProjectDirectory();
  if (!path) return;
  $('#project-form').elements.repository.value = path;
  $('#project-form').elements.link_repository.checked = true;
});
$('#project-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const values = new FormData(event.target);
  try {
    const project = await api('/projects', 'POST', {
      name: values.get('name'), description: values.get('description'),
      repository: values.get('repository') || null,
      link_repository: values.has('link_repository'), provider: 'openai-compatible',
    });
    projects = await api('/projects');
    $('#project-dialog').close();
    event.target.reset();
    await startNewChat(project.id);
    renderSelectors();
    toast('项目已就绪，Git 仓库与分支已自动连接。');
  } catch (error) { setFeedback('#project-feedback', error.message, true); }
});

async function initialize() {
  try {
    if ($('#context-limit-select')) $('#context-limit-select').value = String(contextMaxTokens);
    if ($('#context-auto-compact')) $('#context-auto-compact').checked = Boolean(contextAutoCompact);
    initializeSettings();
    await loadDshSettings();
    [projects, profiles, conversations] = await Promise.all([
      api('/projects'), api('/model-profiles'), api('/conversations'),
    ]);
    renderSelectors();
    await loadMcpServers();
    await loadPlugins();
    const recoveringRenderer = new URLSearchParams(location.search).get("recover") === "renderer";
    const shouldRestore = recoveringRenderer || Boolean(dshSettings?.general?.restoreLastSession);
    const interruptedConv = conversations.find((c) => ['interrupted', 'running'].includes(c.execution_status));
    const lastViewedConv = conversations.find((c) => c.id === localStorage.getItem('masp.lastConversationId'));
    const activeConv = (recoveringRenderer && lastViewedConv) || interruptedConv || lastViewedConv || conversations[0];
    if ((shouldRestore || interruptedConv) && activeConv) {
      await openConversation(activeConv.id);
    } else {
      await startNewChat(null);
    }
  } catch (error) { renderMessage('assistant', '工作空间加载失败：' + error.message); }
}
initialize();
