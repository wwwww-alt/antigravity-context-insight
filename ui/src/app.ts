import {
  App,
  applyDocumentTheme,
  applyHostStyleVariables,
} from '@modelcontextprotocol/ext-apps';
import { z } from 'zod';

type CompKey = 'system' | 'user' | 'skills' | 'assistant' | 'tools' | 'events';
type Composition = Record<CompKey, number>;

const COMP_META: Array<{ key: CompKey; label: string; color: string }> = [
  { key: 'system', label: '系统与工具定义', color: '#6366f1' },
  { key: 'user', label: '用户消息', color: '#0ea5e9' },
  { key: 'skills', label: '技能注入', color: '#ec4899' },
  { key: 'assistant', label: '助手思考与回复', color: '#10b981' },
  { key: 'tools', label: '工具调用与结果', color: '#f59e0b' },
  { key: 'events', label: '系统与子Agent消息', color: '#8b5cf6' },
];

interface StepPoint {
  step: number;
  seq?: number;
  turn: number;
  ts: string;
  model: string;
  promptTokens: number;
  inputTokens: number;
  cacheReadTokens: number;
  outputTokens: number;
  cacheRate: number;
  deltaTokens: number;
  isModelSwitch: boolean;
  isCompaction: boolean;
  composition: Composition;
  brief: { user: string; inSummary: string; response: string };
}

interface SessionDetail {
  conversationId: string;
  title: string;
  transcriptPath: string;
  transcriptUri: string;
  firstTs: string;
  lastTs: string;
  durationSeconds: number;
  model: string;
  models: string[];
  modelWindow: number;
  occupancyPct: number;
  stats: {
    userTurns: number;
    modelSteps: number;
    totalSteps: number;
    toolCalls: number;
    errors: number;
    currentContext: number;
    peakContext: number;
    totalInputBilled: number;
    totalCacheRead: number;
    totalOutputTokens: number;
    totalTokens: number;
    cacheHitRate: number;
    subagentCount: number;
    filesTouched: number;
    commandsRun: number;
  };
  currentComposition: Composition;
  stepSeries: StepPoint[];
  turnSeries: StepPoint[];
  events: Array<{ step: number; turn: number; kind: string; label: string; detail: string; delta: number; ts: string }>;
  browserItems: Array<{
    id: string;
    step: number;
    turn: number;
    category: string;
    kind: string;
    kinds?: string[];
    model?: string;
    toolName?: string;
    status?: string;
    title: string;
    tokens: number;
    promptTokens?: number;
    cacheReadTokens?: number;
    ts: string;
    preview: string;
    content?: string;
    thinking?: string;
    answer?: string;
    argsPreview?: string;
    toolCalls?: Array<{ name: string; argsPreview: string }>;
  }>;
  files: Array<{
    path: string;
    name: string;
    fileUri: string;
    reads: number;
    writes: number;
    searches: number;
    ops: Array<{ step: number; tool: string; action: string; ts: string }>;
  }>;
  commands: Array<{
    step: number;
    program: string;
    summary: string;
    command: string;
    status: string;
    exitCode: number | null;
    durationMs: number;
    ts: string;
    outputPreview?: string;
  }>;
  topTools: Array<{ name: string; count: number }>;
  topSkills: Array<{ name: string; count: number }>;
  topPrograms: Array<{ name: string; count: number }>;
}

interface FleetData {
  rootId: string;
  currentId: string;
  memberCount: number;
  subagentCount: number;
  familyTokens: number;
  familyTools: number;
  familySteps: number;
  members: Array<{
    conversationId: string;
    parentId: string | null;
    depth: number;
    isRoot: boolean;
    isCurrent: boolean;
    role: string;
    subagentType: string;
    title: string;
    model: string;
    occupancyPct: number;
    currentContext: number;
    peakContext: number;
    totalTokens: number;
    cacheHitRate: number;
    modelSteps: number;
    toolCalls: number;
    durationSeconds: number;
    currentComposition: Composition;
    lastTs: string;
    promptPreview: string;
  }>;
  edges: Array<{ from: string; to: string; role: string; type: string; step: number }>;
  timeline: Array<{
    id: string;
    step: number;
    kind: string;
    from: string;
    fromLabel: string;
    to: string;
    toLabel: string;
    ts: string;
    summary: string;
    content: string;
  }>;
}

interface InsightsData {
  range: string;
  dayFilter: string;
  kpi: {
    sessions: number;
    rootSessions: number;
    totalTokens: number;
    inputBilled: number;
    cacheRead: number;
    outputTokens: number;
    cacheHitRate: number;
    modelSteps: number;
    toolCalls: number;
    userTurns: number;
    subagents: number;
  };
  last7Days: Array<{ day: string; label: string; tokens: number; calls: number }>;
  heatmap: Array<{ day: string; tokens: number; calls: number }>;
  composition: Partial<Composition>;
  topTools: Array<{ name: string; count: number }>;
  topSkills: Array<{ name: string; count: number }>;
  topPrograms: Array<{ name: string; count: number }>;
  sessions: Array<{
    conversationId: string;
    title: string;
    isSubagent: boolean;
    parentId: string | null;
    role: string | null;
    model: string;
    lastTs: string;
    durationSeconds: number;
    occupancyPct: number;
    stats: SessionDetail['stats'];
    currentComposition: Composition;
  }>;
}

const state = {
  tab: 'context' as 'context' | 'fleet' | 'insights',
  loading: true,
  session: null as SessionDetail | null,
  fleet: null as FleetData | null,
  sessions: [] as Array<{
    conversationId: string;
    title: string;
    isSubagent: boolean;
    model: string;
    lastTs: string;
    stats: SessionDetail['stats'];
    occupancyPct: number;
  }>,
  insights: null as InsightsData | null,
  fullDetailLoadedFor: '' as string,

  // Context view controls
  trendGranularity: 'step' as 'step' | 'turn',
  trendMode: 'total' as 'total' | 'delta',
  pinnedIndex: -1,
  subTab: 'browser' as 'browser' | 'events' | 'files' | 'commands',
  browserCat: 'all' as string,
  assistantKind: 'all' as string,
  browserSearch: '',
  expandedBrowserIds: new Set<string>(),
  eventFilter: 'all' as string,
  fileFilter: 'all' as 'all' | 'read' | 'write' | 'search',
  fileSearch: '',
  cmdStatusFilter: 'all' as 'all' | 'ok' | 'error' | 'bg',
  cmdProgFilter: '',
  expandedCmdSteps: new Set<number>(),

  // Fleet controls
  selectedMemberId: '' as string,
  fleetKindFilter: 'all' as string,
  fleetSearch: '',
  expandedFleetEventIds: new Set<string>(),

  // Insights controls
  insightsRange: '30d' as 'today' | '7d' | '30d' | 'all',
  insightsDay: '' as string,
  insightsSearch: '',
  insightsSort: 'recent' as 'recent' | 'context' | 'tokens',

  toast: '',
  toastTimer: 0,
};

const app = new App({ name: 'Context Insight', version: '1.0.0' }, {});

function esc(v: unknown): string {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function fmtTok(n: number): string {
  const abs = Math.abs(n || 0);
  const sign = n < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}${(abs / 1_000).toFixed(1)}k`;
  return `${sign}${abs}`;
}

function fmtDur(sec: number): string {
  if (!sec || sec < 0) return '0s';
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function fmtTimeShort(ts: string): string {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts.slice(0, 16);
    const pad = (x: number) => String(x).padStart(2, '0');
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return ts.slice(0, 16);
  }
}

function showToast(msg: string) {
  state.toast = msg;
  const el = document.getElementById('toast');
  if (el) {
    el.textContent = msg;
    el.classList.add('show');
  }
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => {
    state.toast = '';
    const t = document.getElementById('toast');
    if (t) t.classList.remove('show');
  }, 2400);
}

function renderMiniCompBar(comp: Partial<Composition> | undefined, height = 8): string {
  const total = COMP_META.reduce((acc, m) => acc + Math.max(0, Number(comp?.[m.key] || 0)), 0);
  if (total <= 0) {
    return `<div class="comp-bar" style="height:${height}px"><div class="comp-empty"></div></div>`;
  }
  const segs = COMP_META.map((m) => {
    const v = Math.max(0, Number(comp?.[m.key] || 0));
    if (v <= 0) return '';
    const pct = (v / total) * 100;
    return `<div class="comp-seg" style="width:${pct.toFixed(2)}%;background:${m.color}" title="${esc(m.label)}: ${fmtTok(v)} (${pct.toFixed(1)}%)"></div>`;
  }).join('');
  return `<div class="comp-bar" style="height:${height}px">${segs}</div>`;
}

async function openFileInPane(fileUri: string) {
  try {
    const res = await app.request(
      {
        method: 'com.google.antigravity/toggle-aux-pane',
        params: { tabType: 'fileView', uri: fileUri },
      },
      z.object({ isError: z.boolean().optional() }).passthrough(),
    );
    if (res?.isError) showToast('当前全页视图不支持直接打开侧栏文件标签');
  } catch {
    showToast('当前视图不支持直接打开文件标签');
  }
}

async function loadSession(conversationId: string, switchToContext = false) {
  state.loading = true;
  if (switchToContext) state.tab = 'context';
  render();
  try {
    const res = await app.callServerTool({
      name: 'app_get_session',
      arguments: { conversation_id: conversationId },
    });
    const data = res.structuredContent as any;
    if (data?.ok && data.session) {
      state.session = data.session;
      state.fleet = data.fleet || state.fleet;
      if (Array.isArray(data.sessions)) state.sessions = data.sessions;
      state.fullDetailLoadedFor = data.session.conversationId;
      state.pinnedIndex = -1;
      state.selectedMemberId = '';
      state.expandedBrowserIds.clear();
      state.expandedCmdSteps.clear();
    } else {
      showToast(data?.error || '加载会话失败');
    }
  } catch (err: any) {
    showToast(`加载失败：${err?.message || err}`);
  } finally {
    state.loading = false;
    render();
  }
}

async function loadInsights(rangeKey = state.insightsRange, dayFilter = state.insightsDay) {
  state.insightsRange = rangeKey;
  state.insightsDay = dayFilter;
  try {
    const res = await app.callServerTool({
      name: 'app_get_insights',
      arguments: { range_key: rangeKey, day_filter: dayFilter },
    });
    const data = res.structuredContent as any;
    if (data?.ok) {
      state.insights = data;
      render();
    }
  } catch (err: any) {
    showToast(`加载洞察失败：${err?.message || err}`);
  }
}

function renderTrendChart(s: SessionDetail): string {
  const series = state.trendGranularity === 'turn' ? s.turnSeries : s.stepSeries;
  if (!series || series.length === 0) {
    return '<div class="empty-inline">该会话尚无模型请求记录。</div>';
  }
  const activeIdx =
    state.pinnedIndex >= 0 && state.pinnedIndex < series.length ? state.pinnedIndex : series.length - 1;
  const active = series[activeIdx];

  const isDelta = state.trendMode === 'delta';
  const count = series.length;
  const barW = Math.max(8, Math.min(24, Math.floor(680 / Math.max(count, 1)) - 2));
  const gap = 3;
  const padL = 44;
  const padR = 14;
  const padT = 18;
  const padB = 22;
  const chartW = Math.max(460, padL + padR + count * (barW + gap));
  const chartH = 176;
  const innerH = chartH - padT - padB;

  let barsSvg = '';
  let axisSvg = '';

  if (!isDelta) {
    const maxVal = Math.max(1000, ...series.map((p) => p.promptTokens || 0));
    const gridTicks = [0, 0.5, 1];
    axisSvg = gridTicks
      .map((t) => {
        const y = padT + innerH * (1 - t);
        const lbl = fmtTok(Math.round(maxVal * t));
        return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${chartW - padR}" y2="${y.toFixed(1)}" class="grid-line"/>
                <text x="${padL - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end" class="axis-lbl">${lbl}</text>`;
      })
      .join('');

    barsSvg = series
      .map((p, i) => {
        const x = padL + i * (barW + gap);
        const total = p.promptTokens || 1;
        const barH = Math.max(2, (total / maxVal) * innerH);
        let curY = padT + innerH;
        const compSum = COMP_META.reduce((a, m) => a + Math.max(0, p.composition?.[m.key] || 0), 0) || 1;
        const rects = COMP_META.map((m) => {
          const v = Math.max(0, p.composition?.[m.key] || 0);
          if (v <= 0) return '';
          const segH = (v / compSum) * barH;
          curY -= segH;
          return `<rect x="${x}" y="${curY.toFixed(1)}" width="${barW}" height="${Math.max(0.8, segH).toFixed(1)}" fill="${m.color}" rx="1"/>`;
        }).join('');

        const marker = p.isCompaction
          ? `<text x="${x + barW / 2}" y="${Math.max(10, curY - 3).toFixed(1)}" text-anchor="middle" class="mark-compact">✂</text>`
          : p.isModelSwitch
            ? `<text x="${x + barW / 2}" y="${Math.max(10, curY - 3).toFixed(1)}" text-anchor="middle" class="mark-switch">⇄</text>`
            : '';

        const isSel = i === activeIdx;
        const selRect = isSel
          ? `<rect x="${x - 1.5}" y="${padT}" width="${barW + 3}" height="${innerH}" fill="none" stroke="var(--color-ring-primary, #4f46e5)" stroke-width="1.5" rx="2"/>`
          : '';
        const xLbl =
          count <= 16 || i === 0 || i === count - 1 || i % Math.ceil(count / 12) === 0
            ? `<text x="${x + barW / 2}" y="${chartH - 5}" text-anchor="middle" class="axis-lbl">${state.trendGranularity === 'turn' ? `T${p.turn}` : `#${p.seq || i + 1}`}</text>`
            : '';

        return `<g class="bar-hit" data-action="pin-bar" data-idx="${i}">
          <rect x="${x - 1}" y="${padT}" width="${barW + 2}" height="${innerH}" fill="transparent"/>
          ${rects}${marker}${selRect}${xLbl}
        </g>`;
      })
      .join('');
  } else {
    const maxAbs = Math.max(1000, ...series.map((p) => Math.abs(p.deltaTokens || 0)));
    const midY = padT + innerH / 2;
    axisSvg = `
      <line x1="${padL}" y1="${midY.toFixed(1)}" x2="${chartW - padR}" y2="${midY.toFixed(1)}" class="grid-line strong"/>
      <text x="${padL - 6}" y="${(padT + 4).toFixed(1)}" text-anchor="end" class="axis-lbl">+${fmtTok(maxAbs)}</text>
      <text x="${padL - 6}" y="${(midY + 3).toFixed(1)}" text-anchor="end" class="axis-lbl">0</text>
      <text x="${padL - 6}" y="${(padT + innerH).toFixed(1)}" text-anchor="end" class="axis-lbl">-${fmtTok(maxAbs)}</text>
    `;
    barsSvg = series
      .map((p, i) => {
        const x = padL + i * (barW + gap);
        const d = p.deltaTokens || 0;
        const h = Math.max(2, (Math.abs(d) / maxAbs) * (innerH / 2 - 4));
        const y = d >= 0 ? midY - h : midY;
        const fill = d >= 0 ? '#0ea5e9' : '#10b981';
        const isSel = i === activeIdx;
        const selRect = isSel
          ? `<rect x="${x - 1.5}" y="${padT}" width="${barW + 3}" height="${innerH}" fill="none" stroke="var(--color-ring-primary, #4f46e5)" stroke-width="1.5" rx="2"/>`
          : '';
        const xLbl =
          count <= 16 || i === 0 || i === count - 1 || i % Math.ceil(count / 12) === 0
            ? `<text x="${x + barW / 2}" y="${chartH - 5}" text-anchor="middle" class="axis-lbl">${state.trendGranularity === 'turn' ? `T${p.turn}` : `#${p.seq || i + 1}`}</text>`
            : '';
        return `<g class="bar-hit" data-action="pin-bar" data-idx="${i}">
          <rect x="${x - 1}" y="${padT}" width="${barW + 2}" height="${innerH}" fill="transparent"/>
          <rect x="${x}" y="${y.toFixed(1)}" width="${barW}" height="${h.toFixed(1)}" fill="${fill}" rx="2"/>
          ${selRect}${xLbl}
        </g>`;
      })
      .join('');
  }

  return `
    <div class="trend-scroll">
      <svg class="trend-svg" viewBox="0 0 ${chartW} ${chartH}" width="${chartW}" height="${chartH}">
        ${axisSvg}
        ${barsSvg}
      </svg>
    </div>
    <div class="step-brief">
      <div class="brief-head">
        <span><strong>${state.trendGranularity === 'turn' ? `Turn ${active.turn}` : `Step #${active.step}`}</strong> · <code>${esc(active.model)}</code></span>
        <span class="brief-metrics">
          Prompt <strong>${active.promptTokens.toLocaleString()}</strong> ·
          Cache <strong>${active.cacheReadTokens.toLocaleString()}</strong> (${active.cacheRate}%) ·
          Output <strong>${active.outputTokens.toLocaleString()}</strong> ·
          Delta <strong class="${active.deltaTokens < 0 ? 'txt-ok' : ''}">${active.deltaTokens >= 0 ? '+' : ''}${fmtTok(active.deltaTokens)}</strong>
        </span>
      </div>
      <div class="brief-row"><span class="brief-tag">User</span><span>${esc(active.brief?.user || '—')}</span></div>
      <div class="brief-row"><span class="brief-tag">In</span><span>${esc(active.brief?.inSummary || '—')}</span></div>
      <div class="brief-row"><span class="brief-tag">Resp</span><span>${esc(active.brief?.response || '—')}</span></div>
    </div>
  `;
}

function renderContextSubPanel(s: SessionDetail): string {
  if (state.subTab === 'events') {
    const counts: Record<string, number> = { all: s.events.length };
    for (const ev of s.events) counts[ev.kind] = (counts[ev.kind] || 0) + 1;
    const list = s.events.filter((ev) => state.eventFilter === 'all' || ev.kind === state.eventFilter).reverse();
    return `
      <div class="sub-toolbar">
        ${[
          ['all', '全部'],
          ['compact', '✂ 压缩'],
          ['switch', '⇄ 切换模型'],
          ['skill', '🧩 技能加载'],
          ['subagent', '🤖 派生子Agent'],
          ['error', '⚠ 错误'],
        ]
          .map(
            ([k, l]) =>
              `<button class="chip ${state.eventFilter === k ? 'active' : ''}" data-action="event-filter" data-val="${k}">${l} ${counts[k] || 0}</button>`,
          )
          .join('')}
      </div>
      ${
        list.length === 0
          ? '<div class="empty-inline">暂无匹配的上下文事件。</div>'
          : `<div class="simple-list">
              ${list
                .map(
                  (ev) => `
                  <div class="row-item">
                    <span class="badge badge-${esc(ev.kind)}">${esc(ev.label)}</span>
                    <span class="row-main">${esc(ev.detail)}</span>
                    <span class="row-meta">Step #${ev.step} · ${fmtTimeShort(ev.ts)}</span>
                  </div>`,
                )
                .join('')}
            </div>`
      }
    `;
  }

  if (state.subTab === 'files') {
    const q = state.fileSearch.trim().toLowerCase();
    const list = s.files.filter((f) => {
      if (state.fileFilter === 'read' && f.reads === 0) return false;
      if (state.fileFilter === 'write' && f.writes === 0) return false;
      if (state.fileFilter === 'search' && f.searches === 0) return false;
      if (q && !f.path.toLowerCase().includes(q)) return false;
      return true;
    });
    return `
      <div class="sub-toolbar">
        <input id="file-search" class="input sm" type="search" placeholder="筛选文件路径…" value="${esc(state.fileSearch)}" />
        ${[
          ['all', `全部 ${s.files.length}`],
          ['read', '读取'],
          ['write', '写入/编辑'],
          ['search', '搜索'],
        ]
          .map(
            ([k, l]) =>
              `<button class="chip ${state.fileFilter === k ? 'active' : ''}" data-action="file-filter" data-val="${k}">${l}</button>`,
          )
          .join('')}
      </div>
      ${
        list.length === 0
          ? '<div class="empty-inline">暂无匹配的文件操作。</div>'
          : `<div class="simple-list">
              ${list
                .slice(0, 100)
                .map(
                  (f) => `
                  <div class="row-item">
                    <button class="link-btn" data-action="open-file" data-uri="${esc(f.fileUri)}" title="在 Antigravity 侧栏打开 ${esc(f.path)}">${esc(f.name)}</button>
                    <span class="row-path" title="${esc(f.path)}">${esc(f.path)}</span>
                    <span class="row-badges">
                      ${f.reads ? `<span class="badge badge-read">读 ${f.reads}</span>` : ''}
                      ${f.writes ? `<span class="badge badge-write">写 ${f.writes}</span>` : ''}
                      ${f.searches ? `<span class="badge badge-search">搜 ${f.searches}</span>` : ''}
                    </span>
                  </div>`,
                )
                .join('')}
            </div>`
      }
    `;
  }

  if (state.subTab === 'commands') {
    const list = s.commands
      .filter((c) => {
        if (state.cmdStatusFilter !== 'all' && c.status !== state.cmdStatusFilter) return false;
        if (state.cmdProgFilter && c.program !== state.cmdProgFilter) return false;
        return true;
      })
      .reverse();
    return `
      <div class="sub-toolbar">
        ${[
          ['all', `全部 ${s.commands.length}`],
          ['ok', '✅ 成功'],
          ['error', '❌ 失败'],
          ['bg', '⏳ 后台'],
        ]
          .map(
            ([k, l]) =>
              `<button class="chip ${state.cmdStatusFilter === k ? 'active' : ''}" data-action="cmd-status" data-val="${k}">${l}</button>`,
          )
          .join('')}
        ${s.topPrograms
          .slice(0, 8)
          .map(
            (p) =>
              `<button class="chip ${state.cmdProgFilter === p.name ? 'active' : ''}" data-action="cmd-prog" data-val="${esc(p.name)}">${esc(p.name)} (${p.count})</button>`,
          )
          .join('')}
      </div>
      ${
        list.length === 0
          ? '<div class="empty-inline">暂无匹配的命令执行记录。</div>'
          : `<div class="simple-list">
              ${list
                .slice(0, 100)
                .map((c) => {
                  const open = state.expandedCmdSteps.has(c.step);
                  return `
                  <div class="expand-item">
                    <div class="row-item clickable" data-action="toggle-cmd" data-step="${c.step}">
                      <span class="badge badge-cmd-${esc(c.status)}">${c.status === 'ok' ? 'OK' : c.status === 'bg' ? 'BG' : `ERR ${c.exitCode ?? ''}`}</span>
                      <span class="badge badge-muted">${esc(c.program)}</span>
                      <span class="row-main">${esc(c.summary || c.command)}</span>
                      <span class="row-meta">${c.durationMs ? `${(c.durationMs / 1000).toFixed(1)}s · ` : ''}Step #${c.step}</span>
                    </div>
                    ${
                      open
                        ? `<div class="expand-body">
                            <div class="sub-lbl">命令行</div>
                            <pre class="code-pre">${esc(c.command)}</pre>
                            ${c.outputPreview ? `<div class="sub-lbl">输出预览</div><pre class="code-pre">${esc(c.outputPreview)}</pre>` : ''}
                          </div>`
                        : ''
                    }
                  </div>`;
                })
                .join('')}
            </div>`
      }
    `;
  }

  // Context Browser
  const q = state.browserSearch.trim().toLowerCase();
  const items = [...(s.browserItems || [])].reverse().filter((it) => {
    if (state.browserCat !== 'all' && it.category !== state.browserCat) return false;
    if (state.browserCat === 'assistant' && state.assistantKind !== 'all') {
      if (!(it.kinds || []).includes(state.assistantKind)) return false;
    }
    if (q) {
      const hay = `${it.title} ${it.preview} ${it.toolName || ''} ${it.model || ''}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  return `
    <div class="sub-toolbar">
      <input id="browser-search" class="input sm" type="search" placeholder="搜索消息、思考、工具名或输出…" value="${esc(state.browserSearch)}" />
      ${[
        ['all', `全部 ${s.browserItems.length}`],
        ['user', '用户'],
        ['assistant', '助手'],
        ['tools', '工具结果'],
        ['skills', '技能'],
        ['events', '系统/子Agent'],
      ]
        .map(
          ([k, l]) =>
            `<button class="chip ${state.browserCat === k ? 'active' : ''}" data-action="browser-cat" data-val="${k}">${l}</button>`,
        )
        .join('')}
      ${
        state.browserCat === 'assistant'
          ? ['all', 'thinking', 'tools', 'answer']
              .map(
                (k) =>
                  `<button class="chip sub ${state.assistantKind === k ? 'active' : ''}" data-action="asst-kind" data-val="${k}">${k === 'all' ? '全部类型' : k}</button>`,
              )
              .join('')
          : ''
      }
    </div>
    ${
      items.length === 0
        ? '<div class="empty-inline">暂无匹配的上下文条目。</div>'
        : `<div class="simple-list">
            ${items
              .slice(0, 120)
              .map((it) => {
                const open = state.expandedBrowserIds.has(it.id);
                const catMeta = COMP_META.find((m) => m.key === it.category);
                return `
                <div class="expand-item">
                  <div class="row-item clickable" data-action="toggle-browser" data-id="${esc(it.id)}">
                    <span class="dot" style="background:${catMeta?.color || '#64748b'}"></span>
                    <span class="row-step">#${it.step}</span>
                    <span class="row-title">${esc(it.title)}</span>
                    <span class="row-preview">${esc(it.preview)}</span>
                    <span class="row-meta">${fmtTok(it.tokens)} tok</span>
                  </div>
                  ${
                    open
                      ? `<div class="expand-body">
                          ${
                            it.thinking
                              ? `<div class="sub-lbl">思考 (Thinking)</div><pre class="code-pre">${esc(it.thinking)}</pre>`
                              : ''
                          }
                          ${
                            it.toolCalls && it.toolCalls.length > 0
                              ? `<div class="sub-lbl">工具调用 (${it.toolCalls.length})</div>
                                 ${it.toolCalls.map((tc) => `<div class="tc-box"><strong>${esc(tc.name)}</strong><pre class="code-pre">${esc(tc.argsPreview)}</pre></div>`).join('')}`
                              : ''
                          }
                          ${
                            it.argsPreview
                              ? `<div class="sub-lbl">调用参数</div><pre class="code-pre">${esc(it.argsPreview)}</pre>`
                              : ''
                          }
                          ${
                            it.answer || it.content
                              ? `<div class="sub-lbl">正文内容</div><pre class="code-pre">${esc(it.answer || it.content)}</pre>`
                              : `<div class="sub-lbl">摘要</div><pre class="code-pre">${esc(it.preview)}</pre>`
                          }
                        </div>`
                      : ''
                  }
                </div>`;
              })
              .join('')}
          </div>`
    }
  `;
}

function renderContextView(): string {
  const s = state.session;
  if (!s) {
    return '<div class="empty-panel">未找到可分析的 Antigravity 会话日志。</div>';
  }
  const st = s.stats;
  const compTotal = COMP_META.reduce((a, m) => a + Math.max(0, s.currentComposition?.[m.key] || 0), 0) || 1;
  const fleetCount = state.fleet?.memberCount || 1;

  return `
    <div class="view-scroll">
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-lbl">当前上下文窗口</div>
          <div class="kpi-val">${fmtTok(st.currentContext)} <span class="kpi-unit">/ ${fmtTok(s.modelWindow)}</span></div>
          <div class="kpi-sub">占用 <strong>${s.occupancyPct}%</strong> · 峰值 ${fmtTok(st.peakContext)}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-lbl">提示词缓存命中率</div>
          <div class="kpi-val txt-ok">${st.cacheHitRate}%</div>
          <div class="kpi-sub">缓存 ${fmtTok(st.totalCacheRead)} · 新输入 ${fmtTok(st.totalInputBilled)}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-lbl">累计消耗 Token</div>
          <div class="kpi-val">${fmtTok(st.totalTokens)}</div>
          <div class="kpi-sub">输出 ${fmtTok(st.totalOutputTokens)} · ${st.userTurns} 轮 / ${st.modelSteps} 步</div>
        </div>
        <div class="kpi-card clickable-card" data-action="switch-tab" data-tab="fleet">
          <div class="kpi-lbl">执行与多 Agent 编队</div>
          <div class="kpi-val">${st.toolCalls} <span class="kpi-unit">工具调用</span></div>
          <div class="kpi-sub">编队 <strong>${fleetCount}</strong> 个 Agent · ${st.filesTouched} 文件 · ${st.commandsRun} 命令</div>
        </div>
      </div>

      <section class="panel-card">
        <div class="card-head">
          <div>
            <h2>🧱 当前上下文组成</h2>
            <span class="card-sub">锚定服务商实际 Prompt 窗口（<code>${esc(s.model)}</code>）</span>
          </div>
          <button class="btn btn-xs btn-ghost" data-action="open-file" data-uri="${esc(s.transcriptUri)}">打开 transcript.jsonl</button>
        </div>
        ${renderMiniCompBar(s.currentComposition, 16)}
        <div class="comp-legend">
          ${COMP_META.map((m) => {
            const v = Math.max(0, s.currentComposition?.[m.key] || 0);
            const pct = ((v / compTotal) * 100).toFixed(1);
            return `<div class="legend-item">
              <span class="dot" style="background:${m.color}"></span>
              <span class="legend-name">${esc(m.label)}</span>
              <strong>${fmtTok(v)}</strong>
              <span class="legend-pct">${pct}%</span>
            </div>`;
          }).join('')}
        </div>
      </section>

      <section class="panel-card">
        <div class="card-head">
          <div>
            <h2>📈 上下文演进趋势</h2>
            <span class="card-sub">点击任意柱子固定步骤详情（✂ 压缩回收 · ⇄ 模型切换）</span>
          </div>
          <div class="seg-group">
            <button class="chip ${state.trendGranularity === 'step' ? 'active' : ''}" data-action="trend-gran" data-val="step">Step</button>
            <button class="chip ${state.trendGranularity === 'turn' ? 'active' : ''}" data-action="trend-gran" data-val="turn">Turn</button>
            <span class="sep"></span>
            <button class="chip ${state.trendMode === 'total' ? 'active' : ''}" data-action="trend-mode" data-val="total">Total</button>
            <button class="chip ${state.trendMode === 'delta' ? 'active' : ''}" data-action="trend-mode" data-val="delta">Delta ±</button>
          </div>
        </div>
        ${renderTrendChart(s)}
      </section>

      <section class="panel-card">
        <div class="subtab-bar">
          <button class="subtab ${state.subTab === 'browser' ? 'active' : ''}" data-action="sub-tab" data-val="browser">🧭 上下文浏览器 (${s.browserItems.length})</button>
          <button class="subtab ${state.subTab === 'events' ? 'active' : ''}" data-action="sub-tab" data-val="events">⚡ 上下文事件 (${s.events.length})</button>
          <button class="subtab ${state.subTab === 'files' ? 'active' : ''}" data-action="sub-tab" data-val="files">📁 文件活动 (${s.files.length})</button>
          <button class="subtab ${state.subTab === 'commands' ? 'active' : ''}" data-action="sub-tab" data-val="commands">🖥️ 命令执行 (${s.commands.length})</button>
        </div>
        ${renderContextSubPanel(s)}
      </section>
    </div>
  `;
}

function renderFleetView(): string {
  const f = state.fleet;
  if (!f || f.members.length === 0) {
    return '<div class="empty-panel">当前会话暂无多 Agent 编队信息。</div>';
  }
  const q = state.fleetSearch.trim().toLowerCase();
  const timeline = f.timeline.filter((ev) => {
    if (state.selectedMemberId && ev.from !== state.selectedMemberId && ev.to !== state.selectedMemberId) return false;
    if (state.fleetKindFilter !== 'all' && ev.kind !== state.fleetKindFilter) return false;
    if (q && !`${ev.fromLabel} ${ev.toLabel} ${ev.summary}`.toLowerCase().includes(q)) return false;
    return true;
  });

  const rootMember = f.members.find((m) => m.isRoot) || f.members[0];
  const children = f.members.filter((m) => !m.isRoot);

  return `
    <div class="view-scroll">
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-lbl">编队成员总数</div>
          <div class="kpi-val">${f.memberCount} <span class="kpi-unit">个 Agent</span></div>
          <div class="kpi-sub">1 主 Agent · ${f.subagentCount} 子 Agent</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-lbl">家族累计 Token</div>
          <div class="kpi-val">${fmtTok(f.familyTokens)}</div>
          <div class="kpi-sub">含全部子代理完整上下文消耗</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-lbl">家族模型请求</div>
          <div class="kpi-val">${f.familySteps}</div>
          <div class="kpi-sub">跨成员总工具调用 ${f.familyTools} 次</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-lbl">跨 Agent 协作事件</div>
          <div class="kpi-val">${f.timeline.length}</div>
          <div class="kpi-sub">派发 / 指令 / 回报 / Host 校验</div>
        </div>
      </div>

      <section class="panel-card">
        <div class="card-head">
          <div>
            <h2>🕸 Agent 网络（家族全景）</h2>
            <span class="card-sub">点击卡片筛选下方协作时间线，或直接切换分析该成员的上下文</span>
          </div>
          ${
            state.selectedMemberId
              ? '<button class="btn btn-xs btn-ghost" data-action="clear-member">显示全部成员</button>'
              : ''
          }
        </div>

        <div class="fleet-tree">
          <div class="member-card root ${state.selectedMemberId === rootMember.conversationId ? 'selected' : ''}" data-action="select-member" data-id="${esc(rootMember.conversationId)}">
            <div class="member-top">
              <span class="badge badge-global">主 Agent</span>
              <strong>${esc(rootMember.title)}</strong>
              <span class="badge badge-muted">${esc(rootMember.model)}</span>
              <button class="btn btn-xs btn-secondary ml-auto" data-action="open-session" data-id="${esc(rootMember.conversationId)}" data-stop="1">查看上下文 →</button>
            </div>
            <div class="member-metrics">
              <span>上下文 <strong>${fmtTok(rootMember.currentContext)}</strong> (${rootMember.occupancyPct}%)</span>
              <span>缓存 <strong>${rootMember.cacheHitRate}%</strong></span>
              <span>${rootMember.modelSteps} 步 · ${rootMember.toolCalls} 工具 · ${fmtDur(rootMember.durationSeconds)}</span>
            </div>
            ${renderMiniCompBar(rootMember.currentComposition, 8)}
          </div>

          ${
            children.length === 0
              ? '<div class="empty-inline">该会话未派生子 Agent。可在「洞察」页选择带有 🤖 标记的多 Agent 会话查看完整编队网络。</div>'
              : `<div class="fleet-children">
                  ${children
                    .map(
                      (m) => `
                      <div class="member-card child ${state.selectedMemberId === m.conversationId ? 'selected' : ''}" data-action="select-member" data-id="${esc(m.conversationId)}">
                        <div class="member-top">
                          <span class="badge badge-subagent">${esc(m.subagentType)}</span>
                          <strong>${esc(m.role)}</strong>
                          <span class="badge badge-muted">${esc(m.model)}</span>
                          <button class="btn btn-xs btn-ghost ml-auto" data-action="open-session" data-id="${esc(m.conversationId)}" data-stop="1">查看上下文 →</button>
                        </div>
                        <div class="member-metrics">
                          <span>上下文 <strong>${fmtTok(m.currentContext)}</strong></span>
                          <span>总计 ${fmtTok(m.totalTokens)}</span>
                          <span>${m.modelSteps} 步 · ${m.toolCalls} 工具 · ${fmtDur(m.durationSeconds)}</span>
                        </div>
                        ${renderMiniCompBar(m.currentComposition, 7)}
                        ${m.promptPreview ? `<div class="member-prompt">${esc(m.promptPreview)}</div>` : ''}
                      </div>`,
                    )
                    .join('')}
                </div>`
          }
        </div>
      </section>

      <section class="panel-card">
        <div class="card-head">
          <div>
            <h2>🛰 跨 Agent 协作时间线与事件检查</h2>
            <span class="card-sub">点击任意记录展开完整派发 Prompt 或子 Agent 回报正文</span>
          </div>
        </div>
        <div class="sub-toolbar">
          <input id="fleet-search" class="input sm" type="search" placeholder="搜索成员名或消息内容…" value="${esc(state.fleetSearch)}" />
          ${[
            ['all', `全部 ${f.timeline.length}`],
            ['spawn', '派生'],
            ['send_message', '发送指令'],
            ['reply', '子Agent回报'],
            ['host_facts', 'Host 校验'],
          ]
            .map(
              ([k, l]) =>
                `<button class="chip ${state.fleetKindFilter === k ? 'active' : ''}" data-action="fleet-kind" data-val="${k}">${l}</button>`,
            )
            .join('')}
        </div>
        ${
          timeline.length === 0
            ? '<div class="empty-inline">暂无匹配的跨 Agent 协作消息。</div>'
            : `<div class="simple-list">
                ${timeline
                  .map((ev) => {
                    const open = state.expandedFleetEventIds.has(ev.id);
                    return `
                    <div class="expand-item">
                      <div class="row-item clickable" data-action="toggle-fleet-ev" data-id="${esc(ev.id)}">
                        <span class="badge badge-fe-${esc(ev.kind)}">${esc(ev.kind)}</span>
                        <span class="fe-route"><strong>${esc(ev.fromLabel)}</strong> → <strong>${esc(ev.toLabel)}</strong></span>
                        <span class="row-preview">${esc(ev.summary)}</span>
                        <span class="row-meta">Step #${ev.step} · ${fmtTimeShort(ev.ts)}</span>
                      </div>
                      ${open ? `<div class="expand-body"><pre class="code-pre">${esc(ev.content)}</pre></div>` : ''}
                    </div>`;
                  })
                  .join('')}
              </div>`
        }
      </section>
    </div>
  `;
}

function renderInsightsView(): string {
  const ins = state.insights;
  if (!ins) return '<div class="empty-panel">正在加载跨会话洞察…</div>';
  const kpi = ins.kpi;

  // 7-day SVG chart
  const max7 = Math.max(1000, ...ins.last7Days.map((d) => d.tokens));
  const bars7 = ins.last7Days
    .map((d, i) => {
      const x = 18 + i * 54;
      const h = Math.max(3, (d.tokens / max7) * 90);
      const y = 104 - h;
      const isSel = state.insightsDay === d.day;
      return `<g class="bar-hit" data-action="pick-day" data-day="${d.day}">
        <rect x="${x}" y="${y.toFixed(1)}" width="30" height="${h.toFixed(1)}" rx="5" fill="${isSel ? '#0ea5e9' : '#6366f1'}"/>
        <text x="${x + 15}" y="${(y - 4).toFixed(1)}" text-anchor="middle" class="axis-lbl">${d.tokens > 0 ? fmtTok(d.tokens) : ''}</text>
        <text x="${x + 15}" y="120" text-anchor="middle" class="axis-lbl">${esc(d.label)}</text>
      </g>`;
    })
    .join('');

  // 8-week heatmap
  const maxHeat = Math.max(1, ...ins.heatmap.map((h) => h.tokens));
  const heatCells = ins.heatmap
    .map((h) => {
      const ratio = h.tokens / maxHeat;
      const lvl = h.tokens === 0 ? 0 : ratio < 0.25 ? 1 : ratio < 0.55 ? 2 : ratio < 0.8 ? 3 : 4;
      const active = state.insightsDay === h.day ? 'active-day' : '';
      return `<button class="heat-cell lvl-${lvl} ${active}" data-action="pick-day" data-day="${h.day}" title="${h.day}: ${fmtTok(h.tokens)} tokens (${h.calls} 次模型调用)"></button>`;
    })
    .join('');

  const q = state.insightsSearch.trim().toLowerCase();
  const sessList = [...ins.sessions]
    .filter((s) => !q || s.title.toLowerCase().includes(q) || s.model.toLowerCase().includes(q) || s.conversationId.includes(q))
    .sort((a, b) => {
      if (state.insightsSort === 'context') return b.stats.peakContext - a.stats.peakContext;
      if (state.insightsSort === 'tokens') return b.stats.totalTokens - a.stats.totalTokens;
      return String(b.lastTs).localeCompare(String(a.lastTs));
    });

  return `
    <div class="view-scroll">
      <div class="sub-toolbar">
        ${[
          ['today', '今天'],
          ['7d', '近 7 天'],
          ['30d', '近 30 天'],
          ['all', '全部'],
        ]
          .map(
            ([k, l]) =>
              `<button class="chip ${!state.insightsDay && state.insightsRange === k ? 'active' : ''}" data-action="ins-range" data-val="${k}">${l}</button>`,
          )
          .join('')}
        ${
          state.insightsDay
            ? `<span class="badge badge-global">已筛选日期：${esc(state.insightsDay)}</span>
               <button class="btn btn-xs btn-ghost" data-action="clear-day">清除日期</button>`
            : ''
        }
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-lbl">累计 Token 用量</div>
          <div class="kpi-val">${fmtTok(kpi.totalTokens)}</div>
          <div class="kpi-sub">缓存 ${fmtTok(kpi.cacheRead)} · 输出 ${fmtTok(kpi.outputTokens)}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-lbl">全局缓存命中率</div>
          <div class="kpi-val txt-ok">${kpi.cacheHitRate}%</div>
          <div class="kpi-sub">${kpi.modelSteps} 次模型调用 · ${kpi.userTurns} 轮对话</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-lbl">活跃会话</div>
          <div class="kpi-val">${kpi.sessions}</div>
          <div class="kpi-sub">${kpi.rootSessions} 主会话 · ${kpi.subagents} 次子 Agent 派发</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-lbl">工具执行总计</div>
          <div class="kpi-val">${kpi.toolCalls}</div>
          <div class="kpi-sub">跨全部本地 Antigravity 会话汇总</div>
        </div>
      </div>

      <div class="two-col">
        <section class="panel-card">
          <div class="card-head"><h2>📊 近 7 天用量趋势</h2><span class="card-sub">点击柱子按天筛选</span></div>
          <svg class="chart7-svg" viewBox="0 0 400 128" width="100%" height="132">${bars7}</svg>
        </section>
        <section class="panel-card">
          <div class="card-head"><h2>🗓️ 近 8 周活动热力图</h2><span class="card-sub">点击格子筛选当天会话</span></div>
          <div class="heatmap-grid">${heatCells}</div>
          <div class="heat-legend"><span>低</span><i class="heat-cell lvl-0"></i><i class="heat-cell lvl-1"></i><i class="heat-cell lvl-2"></i><i class="heat-cell lvl-3"></i><i class="heat-cell lvl-4"></i><span>高</span></div>
        </section>
      </div>

      <div class="three-col">
        <section class="panel-card">
          <div class="card-head"><h2>🔧 热门工具调用</h2></div>
          <div class="rank-list">
            ${ins.topTools.slice(0, 8).map((t) => `<div class="rank-row"><code>${esc(t.name)}</code><strong>${t.count}</strong></div>`).join('') || '<div class="empty-inline">暂无数据</div>'}
          </div>
        </section>
        <section class="panel-card">
          <div class="card-head"><h2>🧩 Skill 加载频次</h2></div>
          <div class="rank-list">
            ${ins.topSkills.slice(0, 8).map((t) => `<div class="rank-row"><code>${esc(t.name)}</code><strong>${t.count}</strong></div>`).join('') || '<div class="empty-inline">暂无 Skill 加载</div>'}
          </div>
        </section>
        <section class="panel-card">
          <div class="card-head"><h2>🖥️ 常用终端程序</h2></div>
          <div class="rank-list">
            ${ins.topPrograms.slice(0, 8).map((t) => `<div class="rank-row"><code>${esc(t.name)}</code><strong>${t.count}</strong></div>`).join('') || '<div class="empty-inline">暂无命令执行</div>'}
          </div>
        </section>
      </div>

      <section class="panel-card">
        <div class="card-head">
          <h2>💬 会话列表 (${sessList.length})</h2>
          <div class="seg-group">
            <input id="ins-search" class="input sm" type="search" placeholder="搜索会话标题或模型…" value="${esc(state.insightsSearch)}" />
            <button class="chip ${state.insightsSort === 'recent' ? 'active' : ''}" data-action="ins-sort" data-val="recent">最近</button>
            <button class="chip ${state.insightsSort === 'context' ? 'active' : ''}" data-action="ins-sort" data-val="context">窗口峰值</button>
            <button class="chip ${state.insightsSort === 'tokens' ? 'active' : ''}" data-action="ins-sort" data-val="tokens">总 Token</button>
          </div>
        </div>
        <div class="session-grid">
          ${sessList
            .map(
              (c) => `
              <div class="session-card" data-action="open-session" data-id="${esc(c.conversationId)}">
                <div class="sess-top">
                  <span class="sess-title">${esc(c.title)}</span>
                  ${c.isSubagent ? `<span class="badge badge-subagent">子Agent</span>` : ''}
                  ${c.stats.subagentCount > 0 ? `<span class="badge badge-global">🤖 ${c.stats.subagentCount}</span>` : ''}
                </div>
                <div class="sess-meta">
                  <span><code>${esc(c.model)}</code></span>
                  <span>峰值 ${fmtTok(c.stats.peakContext)} (${c.occupancyPct}%)</span>
                  <span>总计 ${fmtTok(c.stats.totalTokens)}</span>
                  <span>${fmtTimeShort(c.lastTs)}</span>
                </div>
                ${renderMiniCompBar(c.currentComposition, 6)}
              </div>`,
            )
            .join('')}
        </div>
      </section>
    </div>
  `;
}

function render() {
  const root = document.getElementById('app');
  if (!root) return;

  const activeEl = document.activeElement as HTMLInputElement | null;
  const focusId = activeEl?.id || '';
  const selStart = activeEl && 'selectionStart' in activeEl ? activeEl.selectionStart : null;
  const selEnd = activeEl && 'selectionEnd' in activeEl ? activeEl.selectionEnd : null;

  const currentId = state.session?.conversationId || '';
  const fleetCount = state.fleet?.memberCount || 1;

  root.innerHTML = `
    <header class="topbar">
      <div class="top-left">
        <span class="brand-dot"></span>
        <h1>Context Insight</h1>
        <nav class="tabs">
          <button class="tab-btn ${state.tab === 'context' ? 'active' : ''}" data-action="switch-tab" data-tab="context">📊 上下文</button>
          <button class="tab-btn ${state.tab === 'fleet' ? 'active' : ''}" data-action="switch-tab" data-tab="fleet">🚢 编队${fleetCount > 1 ? ` (${fleetCount})` : ''}</button>
          <button class="tab-btn ${state.tab === 'insights' ? 'active' : ''}" data-action="switch-tab" data-tab="insights">🗂️ 洞察</button>
        </nav>
      </div>
      <div class="top-right">
        <select id="session-select" class="select-sm" title="切换分析的 Antigravity 会话">
          ${state.sessions
            .map(
              (s) =>
                `<option value="${esc(s.conversationId)}" ${s.conversationId === currentId ? 'selected' : ''}>${s.isSubagent ? '↳ ' : ''}${esc(s.title.slice(0, 42))} (${fmtTok(s.stats.peakContext)})</option>`,
            )
            .join('')}
        </select>
        <button class="btn btn-xs btn-ghost" data-action="refresh" title="重新读取会话日志">↻</button>
      </div>
    </header>
    <main class="main-body">
      ${
        state.loading && !state.session && !state.insights
          ? '<div class="empty-panel">正在读取 Antigravity 会话日志…</div>'
          : state.tab === 'insights'
            ? renderInsightsView()
            : state.tab === 'fleet'
              ? renderFleetView()
              : renderContextView()
      }
    </main>
    <div id="toast" class="toast ${state.toast ? 'show' : ''}">${esc(state.toast)}</div>
  `;

  if (focusId) {
    const next = document.getElementById(focusId) as HTMLInputElement | null;
    if (next) {
      next.focus();
      if (selStart !== null && selEnd !== null && typeof next.setSelectionRange === 'function') {
        try {
          next.setSelectionRange(selStart, selEnd);
        } catch {
          // ignore
        }
      }
    }
  }
}

document.addEventListener('change', (e) => {
  const t = e.target as HTMLSelectElement;
  if (t.id === 'session-select' && t.value) {
    void loadSession(t.value);
  }
});

document.addEventListener('input', (e) => {
  const t = e.target as HTMLInputElement;
  if (t.id === 'browser-search') {
    state.browserSearch = t.value;
    render();
  } else if (t.id === 'file-search') {
    state.fileSearch = t.value;
    render();
  } else if (t.id === 'fleet-search') {
    state.fleetSearch = t.value;
    render();
  } else if (t.id === 'ins-search') {
    state.insightsSearch = t.value;
    render();
  }
});

document.addEventListener('click', (e) => {
  const target = e.target as HTMLElement;
  const el = target.closest('[data-action]') as HTMLElement | null;
  if (!el) return;
  if (el.dataset.stop === '1') e.stopPropagation();

  const act = el.dataset.action;
  switch (act) {
    case 'switch-tab': {
      const next = el.dataset.tab as 'context' | 'fleet' | 'insights';
      state.tab = next;
      if (next === 'insights' && !state.insights) void loadInsights();
      else render();
      break;
    }
    case 'refresh':
      if (state.tab === 'insights') void loadInsights();
      else void loadSession(state.session?.conversationId || '');
      break;
    case 'trend-gran':
      state.trendGranularity = (el.dataset.val as 'step' | 'turn') || 'step';
      state.pinnedIndex = -1;
      render();
      break;
    case 'trend-mode':
      state.trendMode = (el.dataset.val as 'total' | 'delta') || 'total';
      render();
      break;
    case 'pin-bar':
      state.pinnedIndex = Number(el.dataset.idx ?? -1);
      render();
      break;
    case 'sub-tab':
      state.subTab = (el.dataset.val as any) || 'browser';
      // Ensure full content is loaded when browsing/inspecting commands
      if (state.session && state.fullDetailLoadedFor !== state.session.conversationId) {
        void loadSession(state.session.conversationId);
      } else {
        render();
      }
      break;
    case 'browser-cat':
      state.browserCat = el.dataset.val || 'all';
      state.assistantKind = 'all';
      render();
      break;
    case 'asst-kind':
      state.assistantKind = el.dataset.val || 'all';
      render();
      break;
    case 'toggle-browser': {
      const id = el.dataset.id || '';
      if (state.session && state.fullDetailLoadedFor !== state.session.conversationId) {
        state.expandedBrowserIds.add(id);
        void loadSession(state.session.conversationId);
        return;
      }
      if (state.expandedBrowserIds.has(id)) state.expandedBrowserIds.delete(id);
      else state.expandedBrowserIds.add(id);
      render();
      break;
    }
    case 'event-filter':
      state.eventFilter = el.dataset.val || 'all';
      render();
      break;
    case 'file-filter':
      state.fileFilter = (el.dataset.val as any) || 'all';
      render();
      break;
    case 'open-file':
      if (el.dataset.uri) void openFileInPane(el.dataset.uri);
      break;
    case 'cmd-status':
      state.cmdStatusFilter = (el.dataset.val as any) || 'all';
      render();
      break;
    case 'cmd-prog': {
      const p = el.dataset.val || '';
      state.cmdProgFilter = state.cmdProgFilter === p ? '' : p;
      render();
      break;
    }
    case 'toggle-cmd': {
      const st = Number(el.dataset.step || 0);
      if (state.session && state.fullDetailLoadedFor !== state.session.conversationId) {
        state.expandedCmdSteps.add(st);
        void loadSession(state.session.conversationId);
        return;
      }
      if (state.expandedCmdSteps.has(st)) state.expandedCmdSteps.delete(st);
      else state.expandedCmdSteps.add(st);
      render();
      break;
    }
    case 'select-member': {
      const id = el.dataset.id || '';
      state.selectedMemberId = state.selectedMemberId === id ? '' : id;
      render();
      break;
    }
    case 'clear-member':
      state.selectedMemberId = '';
      render();
      break;
    case 'fleet-kind':
      state.fleetKindFilter = el.dataset.val || 'all';
      render();
      break;
    case 'toggle-fleet-ev': {
      const id = el.dataset.id || '';
      if (state.expandedFleetEventIds.has(id)) state.expandedFleetEventIds.delete(id);
      else state.expandedFleetEventIds.add(id);
      render();
      break;
    }
    case 'open-session': {
      const id = el.dataset.id || '';
      if (id) void loadSession(id, true);
      break;
    }
    case 'ins-range':
      void loadInsights((el.dataset.val as any) || '30d', '');
      break;
    case 'pick-day': {
      const d = el.dataset.day || '';
      void loadInsights(state.insightsRange, state.insightsDay === d ? '' : d);
      break;
    }
    case 'clear-day':
      void loadInsights(state.insightsRange, '');
      break;
    case 'ins-sort':
      state.insightsSort = (el.dataset.val as any) || 'recent';
      render();
      break;
  }
});

// Register handlers BEFORE connect()
app.ontoolinput = ({ arguments: args }) => {
  if (args && typeof args === 'object') {
    const t = (args as Record<string, unknown>).tab;
    if (t === 'context' || t === 'fleet' || t === 'insights') state.tab = t;
  }
  state.loading = true;
  render();
};

app.ontoolresult = (result) => {
  const data = result.structuredContent as any;
  if (data) {
    if (data.initialTab) state.tab = data.initialTab;
    if (data.session) state.session = data.session;
    if (data.fleet) state.fleet = data.fleet;
    if (Array.isArray(data.sessions)) state.sessions = data.sessions;
    if (data.insights) state.insights = data.insights;
  }
  state.loading = false;
  render();
};

app.onhostcontextchanged = (ctx) => {
  if (ctx.theme) applyDocumentTheme(ctx.theme);
  if (ctx.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
};

async function init() {
  render();
  try {
    await app.connect();
    const ctx = app.getHostContext();
    if (ctx?.theme) applyDocumentTheme(ctx.theme);
    if (ctx?.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
    window.setTimeout(() => {
      if (state.loading && !state.session) {
        void loadSession('');
        void loadInsights('30d', '');
      }
    }, 350);
  } catch (err: any) {
    state.loading = false;
    showToast(`MCP App 连接失败：${err?.message || err}`);
    render();
  }
}

void init();
