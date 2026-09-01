/* AquaFHIR Bridge — reviewer console.
   Vanilla ES2020, no build step. Rendering is a pure function of `state`;
   every mutation ends in render() so the sidebar counts, KPIs, timeline, map,
   and hash-chain visualization can never drift from each other. */

'use strict';

const API = '/api/v1';
const THEME_KEY   = 'aquafhir.theme';
const REVIEWER_KEY = 'aquafhir.reviewer';

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* ── State ──────────────────────────────────────────────────────────────── */

const OAH_SYSTEM = 'http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu';
const OAH_CATALOG = [
  { code: 'electrical-conductivity', display: 'Electrical conductivity',                    unit: 'mS/cm' },
  { code: 'ndci',                    display: 'Normalized Difference Chlorophyll Index',    unit: '1'     },
  { code: 'waterTemperature',        display: 'Water temperature',                          unit: 'Cel'   },
  { code: 'dissolved-oxygen',        display: 'Dissolved Oxygen',                           unit: 'mg/L'  },
  { code: 'ph',                      display: 'pH',                                         unit: '[pH]'  },
  { code: 'chloride',                display: 'Chloride',                                   unit: 'mg/L'  },
];

const state = {
  view: 'overview',
  health: {},
  ai:    { enabled: false },
  umls:  { enabled: false },
  proposals:  [],
  alerts:     [],
  briefings:  [],
  provenance: [],
  chain:      null,
  situation:  null,
  suggestions:    {},   // proposal id -> UMLS TerminologyMatch[]
  secondaryPicks: {},   // proposal id -> Coding
  filter: 'pending',
  search: '',
  focusIndex: 0,        // review-queue keyboard cursor
  palette: { open: false, query: '', cursor: 0 },
  drawer:  { open: false, proposalId: null, override: null, result: null, busy: false },
  aiDrawer:{ open: false },
  toasts:  [],
  loading: true,
};

/* ── Utilities ──────────────────────────────────────────────────────────── */

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

let toastSeq = 0;
function toast(message, isError = false) {
  const id = ++toastSeq;
  state.toasts.push({ id, message, isError });
  if (state.toasts.length > 4) state.toasts.shift();
  renderToasts();
  if (!isError) setTimeout(() => dismissToast(id), 4000);
}
function dismissToast(id) {
  const stack = $('#toast-stack');
  const node = stack?.querySelector(`[data-toast-id="${id}"]`);
  if (node) {
    node.classList.add('leaving');
    setTimeout(() => {
      state.toasts = state.toasts.filter((t) => t.id !== id);
      renderToasts();
    }, 200);
  } else {
    state.toasts = state.toasts.filter((t) => t.id !== id);
    renderToasts();
  }
}
function renderToasts() {
  const stack = $('#toast-stack');
  if (!stack) return;
  const existing = new Set(Array.from(stack.children).map((n) => Number(n.dataset.toastId)));
  const wanted = new Set(state.toasts.map((t) => t.id));
  // Remove nodes that no longer belong.
  Array.from(stack.children).forEach((n) => {
    if (!wanted.has(Number(n.dataset.toastId))) n.remove();
  });
  // Add new ones.
  for (const t of state.toasts) {
    if (existing.has(t.id)) continue;
    const div = document.createElement('div');
    div.className = `toast show ${t.isError ? 'error' : ''}`;
    div.dataset.toastId = String(t.id);
    div.textContent = t.message;
    div.addEventListener('click', () => dismissToast(t.id));
    stack.appendChild(div);
  }
}

async function withBusy(button, work) {
  if (!button) { await work(); return; }
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>Working…';
  try { await work(); }
  catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.innerHTML = original; }
}

function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[c]));
}

function reviewer() {
  return $('#reviewer-name').value.trim() || 'demo-reviewer';
}

function ago(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 45) return 'just now';
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toISOString().slice(0, 10);
}

function shortDate(iso) {
  return iso ? String(iso).replace('T', ' ').replace(/(\+00:00|Z)$/, '').slice(0, 16) : '—';
}

function classifySeverity(alert) {
  return alert?.severity === 'critical' ? 'bad'
       : alert?.severity === 'high'     ? 'warn'
       : 'ok';
}

/* Debounce for palette input. */
function debounce(fn, ms) {
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* ── Icons (inline SVG, 2px stroke, line style) ─────────────────────────── */

const I = {
  clock:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  users:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><circle cx="17" cy="9" r="2.6"/><path d="M15 20c0-2.5 2.4-4 4-4s2 1 2 4"/></svg>',
  bell:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0-6 6c0 5-3 6-3 6h18s-3-1-3-6a6 6 0 0 0-6-6z"/><path d="M10 21h4"/></svg>',
  link:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 11a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>',
  droplet:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3s-6 6.5-6 11a6 6 0 0 0 12 0c0-4.5-6-11-6-11z"/></svg>',
  eye:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  arrow:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>',
  check:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l5 5L20 6"/></svg>',
  x:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  play:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>',
  moon:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  sun:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  file:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
  refresh:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-8-8"/><path d="M20 4v6h-6"/></svg>',
  brain:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3a3 3 0 0 0-3 3v1a3 3 0 0 0-2 5 3 3 0 0 0 2 5v1a3 3 0 0 0 3 3 3 3 0 0 0 3-3V6a3 3 0 0 0-3-3z"/><path d="M15 3a3 3 0 0 1 3 3v1a3 3 0 0 1 2 5 3 3 0 0 1-2 5v1a3 3 0 0 1-3 3 3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/></svg>',
};

/* ── Chip / status rendering ────────────────────────────────────────────── */

function setChip(id, label, kind /* on|off|warn|bad */) {
  const node = $(id);
  node.className = `chip ${kind}`;
  node.innerHTML = `<span class="dot"></span><span>${esc(label)}</span>`;
}

/* ── KPI tiles (Overview) ───────────────────────────────────────────────── */

function renderKpis() {
  const pending  = state.proposals.filter((p) => p.status === 'pending').length;
  const approved = state.proposals.filter((p) => p.status === 'approved').length;
  const critical = state.alerts.filter((a) => a.severity === 'critical').length;
  const highs    = state.alerts.filter((a) => a.severity === 'high').length;
  const alertCls = critical ? 'bad' : highs ? 'warn' : 'ok';
  const chainCls = state.chain
    ? (state.chain.valid ? 'ok' : 'bad')
    : '';

  const tiles = [
    {
      label: 'Awaiting review', icon: I.eye,
      value: pending,
      sub: pending ? 'Human decision required' : 'Queue clear',
      cls: pending ? 'warn' : 'ok',
    },
    {
      label: 'Approved & published', icon: I.check,
      value: approved,
      sub: state.health.fhir_write_mode === 'enabled'
        ? 'FHIR write: enabled'
        : 'FHIR write: dry-run',
      cls: '',
    },
    {
      label: 'Active alerts', icon: I.bell,
      value: state.alerts.length,
      sub: critical
        ? `${critical} critical · ${highs} high`
        : (highs ? `${highs} high, none critical` : 'no thresholds crossed'),
      cls: alertCls,
    },
    {
      label: 'Chain integrity', icon: I.shield,
      value: state.chain ? (state.chain.valid ? '✓' : '✗') : '—',
      sub: state.chain
        ? `${state.chain.entries_checked} entries verified`
        : 'chain not yet loaded',
      cls: chainCls,
    },
  ];

  $('#kpi-grid').innerHTML = tiles.map((t) => `
    <div class="kpi ${t.cls}">
      <div class="kpi-label">${t.icon}<span>${esc(t.label)}</span></div>
      <div class="kpi-value">${esc(String(t.value))}</div>
      <div class="kpi-sub">${esc(t.sub)}</div>
    </div>
  `).join('');
}

/* ── Pipeline SVG (Overview) ────────────────────────────────────────────── */

function renderPipeline() {
  const proposed  = state.proposals.length;
  const inReview  = state.proposals.filter((p) => p.status === 'pending').length;
  const approved  = state.proposals.filter((p) => p.status === 'approved').length;
  const alerts    = state.alerts.length;
  const briefings = state.briefings.length;

  const nodes = [
    { x:  55, label: 'Ingest',    sub: `${state.proposals.length} in`, kind: 'in' },
    { x: 205, label: 'Propose',   sub: `${proposed} mappings`,          kind: 'in' },
    { x: 365, label: 'Review',    sub: `${inReview} pending`,           kind: 'human' },
    { x: 525, label: 'Publish',   sub: `${approved} to FHIR`,           kind: 'pub' },
    { x: 685, label: 'Threshold', sub: `${alerts} alerts`,              kind: 'alert' },
    { x: 845, label: 'Advisory',  sub: `${briefings} drafts`,           kind: 'alert' },
  ];
  const fillFor = (kind) => ({
    in:    'var(--brand)',
    human: 'var(--info)',
    pub:   'var(--ok)',
    alert: 'var(--warn)',
  }[kind]);
  const softFor = (kind) => ({
    in:    'var(--brand-soft)',
    human: 'var(--info-soft)',
    pub:   'var(--ok-soft)',
    alert: 'var(--warn-soft)',
  }[kind]);

  const groups = nodes.map((n) => `
    <g transform="translate(${n.x}, 60)">
      <rect x="-58" y="-28" width="116" height="56" rx="10"
            fill="${softFor(n.kind)}" stroke="${fillFor(n.kind)}" stroke-width="1.5" />
      <text x="0" y="-4" text-anchor="middle"
            font-family="var(--font-sans)" font-size="13" font-weight="600"
            fill="${fillFor(n.kind)}">${esc(n.label)}</text>
      <text x="0" y="15" text-anchor="middle"
            font-family="var(--font-mono)" font-size="11"
            fill="var(--ink-3)">${esc(n.sub)}</text>
    </g>
  `).join('');

  const arrows = nodes.slice(0, -1).map((n, i) => {
    const next = nodes[i + 1];
    const x1 = n.x + 60, x2 = next.x - 60;
    return `
      <g>
        <line x1="${x1}" y1="60" x2="${x2}" y2="60"
              stroke="var(--line)" stroke-width="1.5" />
        <polygon points="${x2},60 ${x2 - 6},57 ${x2 - 6},63"
                 fill="var(--ink-4)" />
      </g>`;
  }).join('');

  // Gate emphasis at Review
  const gate = `
    <g transform="translate(365, 60)">
      <rect x="-64" y="-34" width="128" height="68" rx="12"
            fill="none" stroke="var(--info)" stroke-width="1.5"
            stroke-dasharray="4 3" opacity="0.6" />
      <text x="0" y="52" text-anchor="middle"
            font-family="var(--font-sans)" font-size="10.5" font-weight="600"
            fill="var(--info)" letter-spacing="0.5">HUMAN GATE</text>
    </g>`;

  const svg = `
    <svg class="pipeline-svg" viewBox="0 0 900 140"
         preserveAspectRatio="xMidYMid meet" role="img" aria-label="Pipeline flow">
      ${arrows}
      ${gate}
      ${groups}
    </svg>`;
  $('#pipeline-svg-slot').innerHTML = svg;
}

/* ── Activity list (Overview) ───────────────────────────────────────────── */

const EVENT_META = {
  'mapping-proposed':    { dot: 'propose', verb: 'Proposal created' },
  'mapping-approved':    { dot: 'approve', verb: 'Proposal approved' },
  'mapping-rejected':    { dot: 'reject',  verb: 'Proposal rejected' },
  'alert-created':       { dot: 'alert',   verb: 'Alert raised' },
  'unstructured-intake': { dot: 'ai',      verb: 'Bulletin extracted' },
  'briefing-drafted':    { dot: 'ai',      verb: 'Advisory drafted' },
  'situation-report':    { dot: 'ai',      verb: 'Situation report' },
};

function renderActivity() {
  const rows = state.provenance.slice(0, 8);
  const list = $('#activity-list');
  if (!rows.length) {
    list.innerHTML = '<li><span class="dot"></span><span class="muted">No events yet — load the Oder replay from the header.</span><time></time></li>';
    return;
  }
  list.innerHTML = rows.map((r) => {
    const meta = EVENT_META[r.event_type] || { dot: '', verb: r.event_type };
    const eid  = r.entity_id ? esc(r.entity_id.slice(0, 18)) : '';
    return `<li>
      <span class="dot ${meta.dot}"></span>
      <span><b class="strong">${esc(meta.verb)}</b>${eid ? ` <span class="muted mono">· ${eid}</span>` : ''}</span>
      <time datetime="${esc(r.created_at)}">${esc(ago(r.created_at))}</time>
    </li>`;
  }).join('');
}

/* ── Review queue rendering ─────────────────────────────────────────────── */

function siteSparkline(proposal) {
  // Build a mini series from approved proposals of the same site+code.
  const key = proposal.coding?.code;
  if (!key) return '';
  const series = state.proposals
    .filter((p) => p.coding?.code === key && p.reading.site_code === proposal.reading.site_code
               && p.normalized_value !== null && p.normalized_value !== undefined)
    .sort((a, b) => new Date(a.reading.observed_at) - new Date(b.reading.observed_at))
    .slice(-12)
    .map((p) => p.normalized_value);
  if (series.length < 2) return '';

  const w = 96, h = 24, pad = 2;
  const min = Math.min(...series), max = Math.max(...series);
  const span = max - min || 1;
  const step = (w - pad * 2) / (series.length - 1);
  const points = series.map((v, i) => {
    const x = pad + i * step;
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return [x.toFixed(1), y.toFixed(1)];
  });
  const d = 'M' + points.map((p) => p.join(',')).join(' L ');
  const [lx, ly] = points[points.length - 1];

  // Colour by "does this parameter have a live alert?"
  const alertCls = state.alerts.some((a) =>
    a.rule_code === key && a.site_code === proposal.reading.site_code)
    ? (state.alerts.find((a) => a.rule_code === key && a.site_code === proposal.reading.site_code)?.severity === 'critical'
       ? 'bad' : 'warn')
    : '';
  return `<svg class="spark ${alertCls}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <path d="${d}" />
    <circle class="last" cx="${lx}" cy="${ly}" r="2.2" />
  </svg>`;
}

function aiDetail(ai) {
  if (!ai) return '';
  const flags = [];
  if (ai.disagreed_with_rules) flags.push('<span class="tag warn">disagrees with curated rules</span>');
  if (ai.needs_expert_review)  flags.push('<span class="tag warn">flagged for expert review</span>');
  const evidence = (ai.evidence || []).length
    ? `<div class="detail-row">
         <span class="detail-label">Quoted</span>
         <span class="quote">${ai.evidence.map((s) => `“${esc(s)}”`).join(' · ')}</span>
       </div>` : '';
  return `
    <div class="detail-row">
      <span class="detail-label">Co-pilot</span>
      <span class="tag ai">${esc(ai.model)}</span>
      <span class="tag mono">${esc(ai.template_id)}</span>
      <span class="tag mono" title="SHA-256 of the exact rendered prompt">prompt ${esc(ai.prompt_hash.slice(0, 12))}</span>
      <span class="tag mono">${ai.latency_ms} ms</span>
      ${flags.join('')}
    </div>
    ${evidence}`;
}

function candidatesDetail(candidates) {
  if (!candidates || candidates.length < 2) return '';
  return `<div class="detail-row">
    <span class="detail-label">Also considered</span>
    ${candidates.map((c) => `<span class="tag mono" title="${esc(c.origin)}">${esc(c.code)} ${c.score.toFixed(2)}</span>`).join('')}
  </div>`;
}

function terminologyDetail(proposal) {
  if (proposal.status !== 'pending' || !proposal.coding) return '';
  if (!state.umls.enabled) {
    return `<div class="detail-row">
      <span class="detail-label">LOINC / SNOMED</span>
      <span class="quote">No terminology source configured — approval will carry one coding.</span>
    </div>`;
  }
  const picked = state.secondaryPicks[proposal.id];
  if (picked) {
    return `<div class="detail-row">
      <span class="detail-label">LOINC / SNOMED</span>
      <span class="chip-btn picked">${esc(picked.code)} · ${esc(picked.display)}</span>
      <span class="quote">attaches on approval</span>
    </div>`;
  }
  const found = state.suggestions[proposal.id];
  let body;
  if (!found) {
    body = `<button type="button" class="btn btn-xs" data-suggest="${proposal.id}">Suggest LOINC / SNOMED</button>`;
  } else if (found.length) {
    body = found.map((m) => `<button type="button" class="chip-btn" data-pick="${proposal.id}"
        data-system="${esc(m.system)}" data-code="${esc(m.code)}"
        data-display="${esc(m.display)}"
        title="${esc(m.display)} (score ${m.score})">${esc(m.vocabulary)} ${esc(m.code)}</button>`).join('');
  } else {
    body = '<span class="quote">No publishable code for this concept — see the README on LOINC gaps.</span>';
  }
  return `<div class="detail-row"><span class="detail-label">LOINC / SNOMED</span>${body}</div>`;
}

function proposalMarkup(proposal, focused) {
  const { reading } = proposal;
  const resolved = proposal.normalized_value !== null && proposal.normalized_unit;
  const spark = siteSparkline(proposal);

  const out = resolved
    ? `<div class="value">${proposal.normalized_value} ${esc(proposal.normalized_unit)}</div>
       <div class="term">${esc(proposal.coding ? proposal.coding.code : '')}</div>`
    : `<div class="value">unit unresolved</div>
       <div class="term">a reviewer must correct this before approval</div>`;

  const actions = proposal.status === 'pending'
    ? `<div class="proposal-actions">
         <button class="btn btn-sm btn-primary" data-approve="${proposal.id}">
           ${I.check}Approve
         </button>
         <button class="btn btn-sm btn-danger" data-reject="${proposal.id}">
           ${I.x}Reject
         </button>
       </div>`
    : `<div class="proposal-actions"><span class="tag ${proposal.status}">${esc(proposal.status)}</span></div>`;

  const proposerTag = proposal.proposer === 'gemini-assisted'
    ? '<span class="tag ai">Gemini-assisted</span>'
    : '<span class="tag">Curated rules</span>';

  const details = [
    candidatesDetail(proposal.candidates),
    aiDetail(proposal.ai),
    terminologyDetail(proposal),
  ].filter(Boolean).join('');

  return `<article class="proposal ${focused ? 'is-focused' : ''}"
             data-proposal-id="${proposal.id}">
    <div class="proposal-main">
      <div>
        <div class="mapping">
          <div class="side">
            <div class="side-label">As received</div>
            <div class="value">${reading.value} ${esc(reading.unit)}</div>
            <div class="term">${esc(reading.parameter)}</div>
          </div>
          <div class="arrow" aria-hidden="true">${I.arrow}</div>
          <div class="side out ${resolved ? '' : 'unresolved'}">
            <div class="side-label">OneAquaHealth FHIR</div>
            ${out}
          </div>
          ${spark ? `<div style="margin-left:auto">${spark}</div>` : ''}
        </div>
        <div class="meta">
          <span><b>${esc(reading.site_name)}</b></span>
          <span>${esc(reading.source_type)} · ${esc(reading.source_id)}</span>
          <span>observed ${shortDate(reading.observed_at)}</span>
          <span>confidence <b>${Math.round(proposal.confidence * 100)}%</b></span>
          ${proposerTag}
          ${proposal.reviewer ? `<span>reviewed by <b>${esc(proposal.reviewer)}</b></span>` : ''}
        </div>
        <p class="rationale">${esc(proposal.rationale)}</p>
      </div>
      ${actions}
    </div>
    ${details ? `<div class="detail">${details}</div>` : ''}
  </article>`;
}

function matchesSearch(proposal, q) {
  if (!q) return true;
  const bag = [
    proposal.reading?.parameter,
    proposal.reading?.site_name,
    proposal.reading?.site_code,
    proposal.reading?.source_id,
    proposal.reading?.source_type,
    proposal.coding?.code,
    proposal.coding?.display,
    proposal.reviewer,
  ].filter(Boolean).join(' ').toLowerCase();
  return bag.includes(q);
}

function renderReview() {
  const all = state.proposals;
  const counts = {
    pending:  all.filter((p) => p.status === 'pending').length,
    approved: all.filter((p) => p.status === 'approved').length,
    rejected: all.filter((p) => p.status === 'rejected').length,
    all:      all.length,
  };
  $('#count-pending').textContent  = counts.pending;
  $('#count-approved').textContent = counts.approved;
  $('#count-rejected').textContent = counts.rejected;
  $('#count-all').textContent      = counts.all;

  const q = state.search.trim().toLowerCase();
  const byStatus = state.filter === 'all' ? all : all.filter((p) => p.status === state.filter);
  const shown = byStatus.filter((p) => matchesSearch(p, q));
  const focusIdx = Math.max(0, Math.min(state.focusIndex, shown.length - 1));
  state.focusIndex = focusIdx;

  $('#proposal-list').innerHTML = shown.length
    ? shown.map((p, i) => proposalMarkup(p, i === focusIdx && state.filter === 'pending')).join('')
    : `<div class="empty"><b>${q ? `Nothing matches “${esc(q)}”.` : `Nothing ${state.filter === 'all' ? 'here' : state.filter}.`}</b>
        ${all.length ? (q ? 'Clear the search or change the filter.' : 'Try another filter.') : 'Load the Oder replay from Overview or use Ingest.'}</div>`;
}

/* ── Alerts + timeline ──────────────────────────────────────────────────── */

function briefingMarkup(b) {
  return `<div class="briefing">
    <h4>${esc(b.audience)} — ${esc(b.headline)}</h4>
    <p>${esc(b.summary)}</p>
    <ul>${b.recommended_actions.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>
    <p><b>Uncertainty.</b> ${esc(b.uncertainty)}</p>
    <p><b>Next question.</b> ${esc(b.escalation_question)}</p>
    <p class="disclaimer">${esc(b.disclaimer)}</p>
  </div>`;
}

function alertMarkup(alert) {
  const drafted = state.briefings.filter((b) => b.alert_id === alert.id);
  const done = new Set(drafted.map((b) => b.audience));
  const buttons = state.ai.enabled
    ? alert.audiences.map((aud) => `<button type="button" class="btn btn-sm"
          data-brief="${alert.id}" data-audience="${esc(aud)}">
          ${done.has(aud) ? 'Redraft for' : 'Draft for'} ${esc(aud)}</button>`).join('')
    : '<span class="quote">Set GEMINI_API_KEY to draft advisories.</span>';

  return `<article class="card alert-card sev-${esc(alert.severity)}">
    <div class="proposal-main">
      <div>
        <div class="alert-head">
          <h3>${esc(alert.rule_code)}</h3>
          <span class="alert-value">${alert.value} ${esc(alert.unit)}</span>
          <span class="tag ${alert.severity === 'critical' ? 'rejected' : 'pending'}">${esc(alert.severity)}</span>
        </div>
        <p class="rationale">${esc(alert.message)}</p>
        <div class="meta">
          <span><b>${esc(alert.site_code)}</b></span>
          <span>observed ${shortDate(alert.observed_at)}</span>
          <span>policy ${esc(alert.policy_id)}</span>
          <span>routed to ${alert.audiences.map(esc).join(', ')}</span>
        </div>
      </div>
    </div>
    <div class="detail"><div class="detail-row">${buttons}</div></div>
    ${drafted.map(briefingMarkup).join('')}
  </article>`;
}

function renderAlerts() {
  $('#alert-list').innerHTML = state.alerts.length
    ? state.alerts.map(alertMarkup).join('')
    : `<div class="empty"><b>No thresholds crossed.</b>
        Alerts appear here when an approved observation crosses the policy.</div>`;
  renderAlertTimeline();
}

function renderAlertTimeline() {
  const slot = $('#timeline-svg-slot');
  if (!state.alerts.length) {
    slot.innerHTML = `<div class="empty" style="margin:${'16px'}">
      <b>No alerts yet.</b>Timeline populates as thresholds trigger.</div>`;
    return;
  }
  const w = 900, h = 130, padL = 40, padR = 24, padT = 20, padB = 30;
  const times = state.alerts
    .map((a) => new Date(a.observed_at).getTime())
    .filter((n) => !Number.isNaN(n));
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const span = Math.max(1, tMax - tMin);

  const yFor = (sev) => (sev === 'critical' ? padT + 12
                       : sev === 'high'     ? padT + 44
                       : padT + 76);
  const colFor = (sev) => (sev === 'critical' ? 'var(--bad)'
                         : sev === 'high'     ? 'var(--warn)'
                         : 'var(--brand)');

  const xFor = (t) => padL + ((t - tMin) / span) * (w - padL - padR);
  const dotEls = state.alerts.map((a) => {
    const t = new Date(a.observed_at).getTime();
    if (Number.isNaN(t)) return '';
    const x = xFor(t), y = yFor(a.severity);
    const c = colFor(a.severity);
    return `
      <g>
        <line x1="${x}" y1="${y}" x2="${x}" y2="${h - padB}"
              stroke="${c}" stroke-width="1" stroke-dasharray="2 3" opacity="0.5" />
        <circle cx="${x}" cy="${y}" r="5" fill="${c}">
          <title>${esc(a.rule_code)} · ${esc(a.severity)} · ${esc(shortDate(a.observed_at))}</title>
        </circle>
      </g>`;
  }).join('');

  // Sev rows + labels
  const rows = ['critical', 'high', 'info'].map((sev) => {
    const y = yFor(sev);
    return `
      <line x1="${padL}" x2="${w - padR}" y1="${y}" y2="${y}"
            stroke="var(--line-2)" stroke-width="1" />
      <text x="${padL - 8}" y="${y + 4}" text-anchor="end"
            font-family="var(--font-mono)" font-size="10"
            fill="var(--ink-3)">${esc(sev)}</text>`;
  }).join('');

  // X-axis: min / mid / max
  const ticks = [tMin, (tMin + tMax) / 2, tMax].map((t, i) => `
    <text x="${xFor(t)}" y="${h - 8}"
          text-anchor="${i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}"
          font-family="var(--font-mono)" font-size="10"
          fill="var(--ink-3)">${esc(shortDate(new Date(t).toISOString()))}</text>
  `).join('');

  slot.innerHTML = `<svg class="timeline-svg" viewBox="0 0 ${w} ${h}"
      preserveAspectRatio="xMidYMid meet" role="img" aria-label="Alert timeline">
    ${rows}
    ${ticks}
    ${dotEls}
  </svg>`;
}

/* ── Sites map + per-site cards ─────────────────────────────────────────── */

function collectSites() {
  const bySite = new Map();
  for (const p of state.proposals) {
    if (!p.reading?.site_code) continue;
    const key = p.reading.site_code;
    if (!bySite.has(key)) {
      bySite.set(key, {
        site_code: key,
        site_name: p.reading.site_name,
        latitude:  p.reading.latitude,
        longitude: p.reading.longitude,
        params:    new Map(),
      });
    }
    const site = bySite.get(key);
    if (!p.coding || p.normalized_value == null) continue;
    const arr = site.params.get(p.coding.code) || [];
    arr.push({
      value: p.normalized_value,
      unit:  p.normalized_unit,
      at:    p.reading.observed_at,
    });
    site.params.set(p.coding.code, arr);
  }
  for (const site of bySite.values()) {
    for (const [k, arr] of site.params) {
      arr.sort((a, b) => new Date(a.at) - new Date(b.at));
      site.params.set(k, arr);
    }
    site.severity = state.alerts
      .filter((a) => a.site_code === site.site_code)
      .reduce((worst, a) => (a.severity === 'critical' ? 'critical'
                            : (worst === 'critical' ? 'critical' : a.severity)), 'ok');
  }
  return Array.from(bySite.values());
}

function renderSitesMap(sites) {
  const slot = $('#map-svg-slot');
  if (!sites.length) {
    slot.innerHTML = `<div class="empty" style="margin:16px">
      <b>No sites yet.</b>Load the Oder replay or ingest a reading.</div>`;
    return;
  }
  const w = 640, h = 380, pad = 40;

  const lats  = sites.map((s) => s.latitude);
  const lons  = sites.map((s) => s.longitude);
  const latMin = Math.min(...lats) - 0.15, latMax = Math.max(...lats) + 0.15;
  const lonMin = Math.min(...lons) - 0.25, lonMax = Math.max(...lons) + 0.25;
  const proj = (lat, lon) => {
    const x = pad + ((lon - lonMin) / (lonMax - lonMin || 1)) * (w - pad * 2);
    const y = pad + (1 - (lat - latMin) / (latMax - latMin || 1)) * (h - pad * 2);
    return [x, y];
  };

  // Grid
  const grid = [];
  for (let i = 0; i <= 4; i++) {
    const x = pad + (i / 4) * (w - pad * 2);
    const y = pad + (i / 4) * (h - pad * 2);
    grid.push(`<line class="grid" x1="${x}" y1="${pad}" x2="${x}" y2="${h - pad}"/>`);
    grid.push(`<line class="grid" x1="${pad}" y1="${y}" x2="${w - pad}" y2="${y}"/>`);
  }

  // Rough Oder trace through the sites, top-to-bottom, with a gentle curve.
  const sorted = sites.slice().sort((a, b) => b.latitude - a.latitude);
  const river = sorted.map((s) => proj(s.latitude, s.longitude));
  let riverPath = '';
  if (river.length >= 2) {
    const [x0, y0] = river[0];
    riverPath = `M ${x0} ${y0 - 20} `
      + river.map(([x, y]) => `L ${x} ${y}`).join(' ')
      + ` L ${river[river.length - 1][0]} ${river[river.length - 1][1] + 30}`;
  }

  // Border line between (rough) DE and PL — vertical through mean longitude.
  const meanLon = (lonMin + lonMax) / 2;
  const [bx1] = proj(latMin, meanLon);
  const [bx2] = proj(latMax, meanLon);

  // Site markers
  const dots = sites.map((s) => {
    const [x, y] = proj(s.latitude, s.longitude);
    const cls = s.severity === 'critical' ? 'bad'
              : s.severity === 'high'     ? 'warn'
              : s.severity === 'ok'       ? 'ok'
              : '';
    const halo = cls === 'bad' || cls === 'warn'
      ? `<circle class="halo ${cls}" cx="${x}" cy="${y}" r="16"/>`
      : '';
    return `
      ${halo}
      <circle class="site ${cls}" cx="${x}" cy="${y}" r="6">
        <title>${esc(s.site_name)} — ${esc(s.severity)}</title>
      </circle>
      <text class="label" x="${x + 10}" y="${y + 3}">${esc(s.site_name)}</text>
      <text class="label label-2" x="${x + 10}" y="${y + 16}">${s.latitude.toFixed(3)}, ${s.longitude.toFixed(3)}</text>`;
  }).join('');

  slot.innerHTML = `
    <svg class="map-svg" viewBox="0 0 ${w} ${h}"
         preserveAspectRatio="xMidYMid meet" role="img" aria-label="Sites map">
      <rect class="land" x="${pad}" y="${pad}" width="${w - pad * 2}" height="${h - pad * 2}" rx="4"/>
      ${grid.join('')}
      <line class="border" x1="${bx1}" y1="${pad}" x2="${bx2}" y2="${h - pad}"/>
      <text x="${bx1 + 6}" y="${pad + 14}" fill="var(--ink-4)"
            font-family="var(--font-mono)" font-size="9">DE ⟷ PL (approx.)</text>
      ${riverPath ? `<path class="river" d="${riverPath}"/>` : ''}
      ${dots}
    </svg>`;
}

function renderSiteCards(sites) {
  const list = $('#site-list');
  if (!sites.length) { list.innerHTML = ''; return; }
  list.innerHTML = sites.map((s) => {
    const rows = Array.from(s.params.entries()).map(([code, series]) => {
      const last = series[series.length - 1];
      const bandClass = state.alerts.find((a) =>
        a.rule_code === code && a.site_code === s.site_code);
      const cls = bandClass?.severity === 'critical' ? 'bad'
                : bandClass?.severity === 'high'     ? 'warn'
                : '';
      const w = 100, h = 22, pad = 2;
      const min = Math.min(...series.map((r) => r.value));
      const max = Math.max(...series.map((r) => r.value));
      const span = max - min || 1;
      const step = series.length > 1 ? (w - pad * 2) / (series.length - 1) : 0;
      const pts = series.map((r, i) => {
        const x = pad + i * step;
        const y = h - pad - ((r.value - min) / span) * (h - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      });
      const d = 'M' + pts.join(' L ');
      const [lx, ly] = pts[pts.length - 1].split(',');
      const spark = series.length >= 2
        ? `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
             <path d="${d}" />
             <circle class="last" cx="${lx}" cy="${ly}" r="2.2"/>
           </svg>`
        : `<span class="muted mono">n=${series.length}</span>`;
      return `<div class="param-row">
        <span class="name mono">${esc(code)}</span>
        <span class="val ${cls}">${last.value} ${esc(last.unit)}</span>
        ${spark}
      </div>`;
    }).join('');
    return `<article class="card site-card">
      <header>
        <div>
          <h3>${esc(s.site_name)}</h3>
          <span class="muted mono" style="font-size:11px">${esc(s.site_code)}</span>
        </div>
        <span class="coords">${s.latitude.toFixed(4)}, ${s.longitude.toFixed(4)}</span>
      </header>
      ${rows || '<div class="empty" style="margin:12px">No approved readings for this site yet.</div>'}
    </article>`;
  }).join('');
}

/* ── Audit chain visualization ──────────────────────────────────────────── */

function chainNodeMarkup(e) {
  const cls = {
    'mapping-approved':    'approve',
    'mapping-rejected':    'reject',
    'mapping-proposed':    'propose',
    'alert-created':       'alert',
    'unstructured-intake': 'model',
    'briefing-drafted':    'model',
    'situation-report':    'model',
  }[e.event_type] || '';
  const glyph = {
    'mapping-approved':    '✓',
    'mapping-rejected':    '✗',
    'mapping-proposed':    '+',
    'alert-created':       '!',
    'unstructured-intake': 'AI',
    'briefing-drafted':    'AI',
    'situation-report':    'AI',
  }[e.event_type] || '·';
  return `<div class="chain-node ${cls}"
    title="#${e.sequence} · ${esc(e.event_type)} · ${esc(e.hash.slice(0, 16))}…">
    ${esc(glyph)}
  </div>`;
}

function renderChainStrip() {
  const strip = $('#chain-strip');
  const rows = state.provenance.slice().reverse().slice(-40);
  if (!rows.length) {
    strip.innerHTML = '<span class="muted">Chain is empty — nothing has been recorded yet.</span>';
    return;
  }
  strip.innerHTML = rows.flatMap((e, i) => {
    const link = i > 0 ? '<div class="chain-link" aria-hidden="true"></div>' : '';
    return [link, chainNodeMarkup(e)];
  }).filter(Boolean).join('');
}

function renderProvenanceRows() {
  $('#provenance-rows').innerHTML = state.provenance.length
    ? state.provenance.map((e) => `<tr>
        <td class="num">${e.sequence}</td>
        <td><b>${esc(e.event_type)}</b></td>
        <td class="mono">${esc(e.entity_id.slice(0, 22))}</td>
        <td class="mono" title="${esc(e.previous_hash)}">${esc(e.previous_hash.slice(0, 12))}…</td>
        <td class="mono" title="${esc(e.hash)}">${esc(e.hash.slice(0, 12))}…</td>
        <td>${esc(ago(e.created_at))}</td>
      </tr>`).join('')
    : '<tr><td colspan="6"><span class="muted">No events recorded yet.</span></td></tr>';
}

function renderChainBanner() {
  const banner = $('#chain-banner');
  if (!state.chain) { banner.className = 'banner'; banner.textContent = 'Verifying chain…'; return; }
  banner.className = `banner ${state.chain.valid ? 'ok' : 'bad'}`;
  banner.innerHTML = state.chain.valid
    ? `${I.shield}<span>Hash chain verified across ${state.chain.entries_checked} entries.</span>`
    : `${I.x}<span>Chain broken at sequence ${state.chain.first_invalid_sequence}.</span>`;
}

function situationMarkup(r) {
  if (!r) return '';
  return `<article class="card">
    <header class="card-head">
      <h2>${esc(r.headline)}</h2>
      <p>Considered ${r.observations_considered} observations, ${r.alerts_considered} alerts,
        ${r.pending_reviews} mappings still awaiting review.</p>
    </header>
    <div class="briefing" style="border-top:0">
      <p>${esc(r.situation)}</p>
      ${r.by_site.map((s) => `<p><b>${esc(s.site_code)}</b> — ${esc(s.assessment)}</p>`).join('')}
      <div class="split">
        <div><h4>Data gaps</h4><ul>${r.data_gaps.map((g) => `<li>${esc(g)}</li>`).join('')}</ul></div>
        <div><h4>Next steps</h4><ul>${r.next_steps.map((n) => `<li>${esc(n)}</li>`).join('')}</ul></div>
      </div>
      <p class="disclaimer">${esc(r.disclaimer)}</p>
    </div>
  </article>`;
}

/* ── Proposal detail drawer ─────────────────────────────────────────────── */

function highlightJson(text) {
  return esc(text)
    .replace(/(&quot;[^&]+?&quot;)(:)/g, '<span class="k">$1</span>$2')
    .replace(/: (&quot;[^&]*?&quot;)/g, ': <span class="s">$1</span>')
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="n">$1</span>');
}

function drawerMarkup() {
  const p = state.proposals.find((x) => x.id === state.drawer.proposalId);
  if (!p) return '';
  const r = p.reading;
  const proposedValue = p.normalized_value !== null && p.normalized_unit
    ? `${p.normalized_value} ${esc(p.normalized_unit)}` : 'unresolved';
  const proposedCode = p.coding ? p.coding.code : '—';

  const ov = state.drawer.override || {
    code: p.coding?.code || '',
    value: p.normalized_value ?? '',
    unit: p.normalized_unit || '',
  };
  const willOverrideCode = ov.code && p.coding && ov.code !== p.coding.code;
  const willOverrideVal  = ov.value !== '' && Number(ov.value) !== p.normalized_value;
  const willOverrideUnit = ov.unit && ov.unit !== p.normalized_unit;
  const overriding = willOverrideCode || willOverrideVal || willOverrideUnit;

  const result = state.drawer.result;
  const isPending = p.status === 'pending';

  const codeOptions = OAH_CATALOG.map((c) => `
    <option value="${esc(c.code)}" ${c.code === ov.code ? 'selected' : ''}>
      ${esc(c.code)} — ${esc(c.display)} (${esc(c.unit)})
    </option>`).join('');

  const compareOverride = overriding
    ? `<div class="compare-cell override">
         <span class="cell-label">Override</span>
         <span class="cell-value">${esc(String(ov.value))} ${esc(ov.unit)}</span>
         <span class="cell-sub">${esc(ov.code)}</span>
       </div>`
    : `<div class="compare-cell">
         <span class="cell-label">Override</span>
         <span class="cell-value muted">no override</span>
         <span class="cell-sub muted">approves as proposed</span>
       </div>`;

  const aiBlock = p.ai ? `
    <div class="drawer-section">
      <h3>AI attribution</h3>
      <div class="detail-row">
        <span class="tag ai">${esc(p.ai.model)}</span>
        <span class="tag mono">${esc(p.ai.template_id)}</span>
        <span class="tag mono">prompt ${esc(p.ai.prompt_hash.slice(0, 16))}…</span>
        <span class="tag mono">${p.ai.latency_ms} ms</span>
        ${p.ai.disagreed_with_rules ? '<span class="tag warn">disagrees with curated rules</span>' : ''}
        ${p.ai.needs_expert_review ? '<span class="tag warn">flagged for expert review</span>' : ''}
      </div>
      ${(p.ai.evidence || []).length ? `<p class="quote mt-2">
        ${p.ai.evidence.map((s) => `“${esc(s)}”`).join(' · ')}
      </p>` : ''}
    </div>` : '';

  const candBlock = (p.candidates && p.candidates.length > 1) ? `
    <div class="drawer-section">
      <h3>Candidates considered</h3>
      <div class="detail-row">
        ${p.candidates.map((c) => `
          <button type="button" class="chip-btn" data-drawer-pick="${esc(c.code)}"
            title="${esc(c.origin)}  score=${c.score.toFixed(2)}">
            ${esc(c.code)} · ${c.score.toFixed(2)}
          </button>`).join('')}
      </div>
    </div>` : '';

  const resultBlock = result ? `
    <div class="drawer-section">
      <h3>FHIR Observation just published</h3>
      <div class="fhir-preview">${highlightJson(JSON.stringify(result.observation, null, 2))}</div>
      ${result.alerts && result.alerts.length ? `
        <p class="hint mt-2">Threshold policy raised ${result.alerts.length} alert(s):
          ${result.alerts.map((a) => `<span class="tag ${a.severity === 'critical' ? 'rejected' : 'pending'}">${esc(a.rule_code)} · ${esc(a.severity)}</span>`).join(' ')}
        </p>` : `<p class="hint mt-2">No thresholds crossed.</p>`}
    </div>` : '';

  const overrideForm = isPending && !result ? `
    <div class="drawer-section">
      <h3>Reviewer override</h3>
      <p class="override-note">Overriding the coding or value is hash-chained under your reviewer id. Leave blank to accept the proposal as-is.</p>
      <div class="override-form">
        <label class="field">
          <span>OneAquaHealth code</span>
          <select id="ovr-code">${codeOptions}</select>
        </label>
        <div class="field-row">
          <label class="field">
            <span>Normalized value</span>
            <input id="ovr-value" type="number" step="any" value="${esc(String(ov.value))}" />
          </label>
          <label class="field">
            <span>Unit (UCUM)</span>
            <input id="ovr-unit" type="text" value="${esc(ov.unit)}" />
          </label>
        </div>
      </div>
    </div>` : '';

  const actionRow = isPending && !result ? `
    <div class="drawer-actions">
      <button class="btn btn-quiet" id="drawer-close-2" type="button">Cancel</button>
      <button class="btn btn-danger" id="drawer-reject" type="button">Reject</button>
      <button class="btn btn-primary" id="drawer-approve" type="button">
        ${overriding ? 'Approve with override' : 'Approve'}
      </button>
    </div>` : `
    <div class="drawer-actions">
      <button class="btn btn-quiet" id="drawer-close-2" type="button">Close</button>
    </div>`;

  return `
    <div class="drawer-head">
      <div>
        <h2>${esc(r.parameter)} <span class="tag ${p.status}" style="margin-left:6px">${esc(p.status)}</span></h2>
        <div class="sub">${esc(r.site_name)} · observed ${shortDate(r.observed_at)}</div>
      </div>
      <button class="btn btn-icon btn-quiet" id="drawer-close" type="button" aria-label="Close">${I.x}</button>
    </div>
    <div class="drawer-body">
      <div class="drawer-section">
        <h3>Mapping comparison</h3>
        <div class="compare-grid">
          <div class="compare-cell">
            <span class="cell-label">As received</span>
            <span class="cell-value">${r.value} ${esc(r.unit)}</span>
            <span class="cell-sub">${esc(r.parameter)}</span>
          </div>
          <div class="compare-cell">
            <span class="cell-label">${p.proposer === 'gemini-assisted' ? 'Gemini proposal' : 'Curated proposal'}</span>
            <span class="cell-value">${esc(proposedValue)}</span>
            <span class="cell-sub">${esc(proposedCode)}  ·  ${Math.round(p.confidence * 100)}%</span>
          </div>
          ${compareOverride}
        </div>
        <p class="rationale mt-2">${esc(p.rationale)}</p>
      </div>
      ${aiBlock}
      ${candBlock}
      ${overrideForm}
      ${resultBlock}
    </div>
    ${actionRow}`;
}

function renderDrawer() {
  const overlay = $('#overlay-drawer');
  if (!state.drawer.open) { overlay.classList.remove('show'); return; }
  $('#drawer-body').innerHTML = drawerMarkup();
  overlay.classList.add('show');
}

function openDrawer(proposalId) {
  state.drawer = { open: true, proposalId, override: null, result: null, busy: false };
  renderDrawer();
}

function closeDrawer() {
  state.drawer = { open: false, proposalId: null, override: null, result: null, busy: false };
  $('#overlay-drawer').classList.remove('show');
}

function captureOverride() {
  const code  = $('#ovr-code')?.value  || '';
  const value = $('#ovr-value')?.value || '';
  const unit  = $('#ovr-unit')?.value  || '';
  state.drawer.override = { code, value, unit };
}

async function drawerApprove() {
  const p = state.proposals.find((x) => x.id === state.drawer.proposalId);
  if (!p) return;
  captureOverride();
  const ov = state.drawer.override;
  const payload = { reviewer: reviewer() };
  const secondary = state.secondaryPicks[p.id];
  if (secondary) payload.secondary_coding = secondary;
  if (ov.code && ov.code !== p.coding?.code) {
    const meta = OAH_CATALOG.find((c) => c.code === ov.code);
    payload.coding = { system: OAH_SYSTEM, code: ov.code, display: meta?.display || ov.code };
  }
  if (ov.value !== '' && ov.unit) {
    const v = Number(ov.value);
    if (!Number.isNaN(v) && (v !== p.normalized_value || ov.unit !== p.normalized_unit)) {
      payload.normalized_value = v;
      payload.normalized_unit  = ov.unit;
    }
  }
  state.drawer.busy = true;
  const btn = $('#drawer-approve');
  await withBusy(btn, async () => {
    const result = await request(`/proposals/${p.id}/approve`, {
      method: 'POST', body: JSON.stringify(payload),
    });
    state.drawer.result = result;
    toast(payload.coding || payload.normalized_value !== undefined
      ? 'Approved with reviewer override. FHIR built and policy evaluated.'
      : 'Approved. FHIR resources built and the policy evaluated.');
    await refresh();
    renderDrawer();
  });
}

async function drawerReject() {
  const id = state.drawer.proposalId;
  await withBusy($('#drawer-reject'), async () => {
    await rejectProposal(id);
    closeDrawer();
  });
}

/* ── AI transparency drawer ─────────────────────────────────────────────── */

function aiCallsFromProvenance() {
  return state.provenance
    .filter((e) => ['unstructured-intake', 'briefing-drafted', 'situation-report', 'mapping-proposed']
      .includes(e.event_type))
    .filter((e) => {
      // mapping-proposed only when it carried AI attribution (payload.ai != null)
      if (e.event_type !== 'mapping-proposed') return true;
      return e.payload?.ai != null;
    })
    .slice(0, 12);
}

function aiDrawerMarkup() {
  const ai = state.ai;
  const calls = aiCallsFromProvenance();
  const glyphFor = (t) => ({
    'unstructured-intake': 'IN',
    'briefing-drafted':    'BR',
    'situation-report':    'SR',
    'mapping-proposed':    'CO',
  }[t] || 'AI');
  const labelFor = (t) => ({
    'unstructured-intake': 'Bulletin extracted',
    'briefing-drafted':    'Advisory drafted',
    'situation-report':    'Situation report',
    'mapping-proposed':    'Coding co-pilot',
  }[t] || t);
  const rows = calls.length
    ? calls.map((e) => {
        const a = e.payload?.ai || e.payload;
        const latency = a?.latency_ms || '';
        const hash = a?.prompt_hash || e.hash;
        return `<div class="row">
          <span class="glyph">${glyphFor(e.event_type)}</span>
          <span><b>${esc(labelFor(e.event_type))}</b><br><span class="muted mono" style="font-size:11px">${esc(a?.template_id || e.event_type)}</span></span>
          <span class="hash" title="${esc(hash)}">${esc((hash || '').slice(0, 12))}…</span>
          <time>${latency ? latency + ' ms' : ago(e.created_at)}</time>
        </div>`;
      }).join('')
    : '<div class="empty" style="margin:8px 0">No AI calls yet.</div>';

  return `
    <div class="drawer-head">
      <div>
        <h2>AI transparency</h2>
        <div class="sub">${ai.enabled ? `${ai.model} · ${ai.assist_mode} mode` : 'AI disabled — set GEMINI_API_KEY'}</div>
      </div>
      <button class="btn btn-icon btn-quiet" id="ai-drawer-close" type="button" aria-label="Close">${I.x}</button>
    </div>
    <div class="drawer-body">
      <div class="drawer-section">
        <h3>Model &amp; policy</h3>
        <dl class="kv" style="padding:0">
          <dt>Provider</dt><dd>${esc(ai.provider || '—')}</dd>
          <dt>Model</dt><dd>${esc(ai.model || '—')}</dd>
          <dt>Assist mode</dt><dd>${esc(ai.assist_mode || '—')}</dd>
          <dt>Assist below confidence</dt><dd>${ai.assist_below_confidence ?? '—'}</dd>
          <dt>Confidence ceiling</dt><dd>${ai.confidence_ceiling ?? '—'}</dd>
        </dl>
        <p class="override-note mt-3">${esc(ai.detail || '')}</p>
      </div>
      <div class="drawer-section">
        <h3>Features enabled</h3>
        <div class="detail-row">
          ${(ai.features || []).map((f) => `<span class="tag ai">${esc(f)}</span>`).join('') || '<span class="muted">none</span>'}
        </div>
      </div>
      <div class="drawer-section">
        <h3>Recent AI calls (from hash chain)</h3>
        <div class="call-log">${rows}</div>
      </div>
    </div>`;
}

function renderAiDrawer() {
  const overlay = $('#overlay-ai');
  if (!state.aiDrawer.open) { overlay.classList.remove('show'); return; }
  $('#ai-drawer-body').innerHTML = aiDrawerMarkup();
  overlay.classList.add('show');
}
function openAiDrawer() { state.aiDrawer.open = true; renderAiDrawer(); }
function closeAiDrawer() { state.aiDrawer.open = false; $('#overlay-ai').classList.remove('show'); }

/* ── Top-level render ───────────────────────────────────────────────────── */

function renderChips() {
  setChip('#chip-fhir',
    state.health.fhir_write_mode === 'enabled' ? 'FHIR live' : 'FHIR dry-run',
    state.health.fhir_write_mode === 'enabled' ? 'on' : 'off');
  setChip('#chip-ai',
    state.ai.enabled ? `AI ${state.ai.model}` : 'AI off',
    state.ai.enabled ? 'on' : 'off');
  setChip('#chip-umls',
    state.umls.enabled ? `UMLS ${(state.umls.vocabularies || []).join(' · ')}` : 'UMLS off',
    state.umls.enabled ? 'on' : 'off');
}

function renderSidebarStats() {
  const pending = state.proposals.filter((p) => p.status === 'pending').length;
  const sites = new Set(state.proposals.map((p) => p.reading?.site_code).filter(Boolean));
  $('#nav-pending').textContent = pending;
  $('#nav-alerts').textContent  = state.alerts.length;
  $('#nav-sites').textContent   = sites.size;
  $('#stat-proposals').textContent = state.proposals.length;
  $('#stat-pending').textContent   = pending;
  $('#stat-alerts').textContent    = state.alerts.length;
  $('#stat-briefings').textContent = state.briefings.length;
  $('#stat-policy').textContent    = state.health.threshold_policy || 'demo';

  const chain = $('#stat-chain');
  if (state.chain) {
    chain.textContent = state.chain.valid ? 'verified' : 'broken';
    chain.className   = state.chain.valid ? 'ok' : 'bad';
  } else {
    chain.textContent = '—'; chain.className = '';
  }
}

function renderIngestGating() {
  $('#intake-submit').disabled  = !state.ai.enabled;
  $('#btn-situation').disabled  = !state.ai.enabled;
  $('#intake-state').textContent = state.ai.enabled
    ? 'Free text is read by Gemini and extracted literally — nothing is inferred.'
    : 'Needs GEMINI_API_KEY. The single-reading form works meanwhile.';
}

function render() {
  renderChips();
  renderSidebarStats();
  renderIngestGating();
  renderKpis();
  renderPipeline();
  renderActivity();
  renderReview();
  renderAlerts();
  const sites = collectSites();
  renderSitesMap(sites);
  renderSiteCards(sites);
  renderChainBanner();
  renderChainStrip();
  renderProvenanceRows();
  $('#situation-report').innerHTML = situationMarkup(state.situation);
}

/* ── Refresh ────────────────────────────────────────────────────────────── */

async function refresh() {
  try {
    const [health, ai, umls, proposals, alerts, briefings, provenance, chain] = await Promise.all([
      request('/health'), request('/ai/status'), request('/terminology/status'),
      request('/proposals'), request('/alerts'), request('/briefings'),
      request('/provenance?limit=200'), request('/provenance/verify'),
    ]);
    Object.assign(state, { health, ai, umls, proposals, alerts, briefings, provenance, chain, loading: false });
    render();
  } catch (error) {
    toast(error.message, true);
  }
}

/* ── View switching ─────────────────────────────────────────────────────── */

function switchView(name) {
  state.view = name;
  $$('.nav-item').forEach((n) => n.classList.toggle('is-active', n.dataset.view === name));
  $$('.view').forEach((v) => v.classList.toggle('is-active', v.dataset.view === name));
  // Focus first heading for accessibility
  const heading = $(`.view[data-view="${name}"] h1`);
  if (heading) heading.setAttribute('tabindex', '-1');
}

/* ── Command palette ────────────────────────────────────────────────────── */

const COMMANDS = () => ([
  { id: 'go-overview', label: 'Go to Overview',        hint: 'g o', icon: I.eye,     run: () => switchView('overview') },
  { id: 'go-review',   label: 'Go to Review queue',    hint: 'g r', icon: I.check,   run: () => switchView('review') },
  { id: 'go-ingest',   label: 'Go to Ingest',          hint: 'g i', icon: I.file,    run: () => switchView('ingest') },
  { id: 'go-sites',    label: 'Go to Sites',           hint: 'g s', icon: I.droplet, run: () => switchView('sites') },
  { id: 'go-alerts',   label: 'Go to Alerts',          hint: 'g a', icon: I.bell,    run: () => switchView('alerts') },
  { id: 'go-audit',    label: 'Go to Audit chain',     hint: 'g u', icon: I.link,    run: () => switchView('audit') },
  { id: 'replay',      label: 'Load Oder replay',      hint: '',    icon: I.play,    run: () => triggerReplay() },
  { id: 'approve-all', label: 'Approve all pending',   hint: '',    icon: I.check,   run: () => triggerApproveAll() },
  { id: 'situation',   label: 'Draft situation report',hint: '',    icon: I.brain,   run: () => triggerSituation(), needsAi: true },
  { id: 'refresh',     label: 'Refresh from server',   hint: '⌘R',  icon: I.refresh, run: () => refresh() },
  { id: 'theme',       label: 'Toggle theme',          hint: 'T',   icon: I.moon,    run: () => toggleTheme() },
  { id: 'print',       label: 'Print audit chain',     hint: '',    icon: I.file,    run: () => { switchView('audit'); setTimeout(() => window.print(), 200); } },
]);

function paletteMatches() {
  const q = state.palette.query.trim().toLowerCase();
  return COMMANDS().filter((c) => !c.needsAi || state.ai.enabled)
    .filter((c) => !q || c.label.toLowerCase().includes(q));
}

function renderPalette() {
  const items = paletteMatches();
  state.palette.cursor = Math.max(0, Math.min(state.palette.cursor, items.length - 1));
  $('#palette-list').innerHTML = items.length
    ? items.map((c, i) => `<button class="palette-item ${i === state.palette.cursor ? 'is-active' : ''}"
        data-cmd="${esc(c.id)}" type="button">
        ${c.icon}<span>${esc(c.label)}</span>
        ${c.hint ? `<span class="meta"><kbd>${esc(c.hint)}</kbd></span>` : ''}
      </button>`).join('')
    : '<div class="empty" style="margin:12px">No matches.</div>';
}

function openPalette() {
  state.palette.open = true; state.palette.query = ''; state.palette.cursor = 0;
  $('#overlay-palette').classList.add('show');
  const input = $('#palette-input');
  input.value = '';
  renderPalette();
  setTimeout(() => input.focus(), 10);
}
function closePalette() {
  state.palette.open = false;
  $('#overlay-palette').classList.remove('show');
}
function runPaletteCommand(id) {
  const cmd = COMMANDS().find((c) => c.id === id);
  closePalette();
  if (cmd) cmd.run();
}

/* ── Actions used by both palette and buttons ───────────────────────────── */

async function triggerReplay() {
  await withBusy($('#btn-replay'), async () => {
    const proposals = await request('/replay', { method: 'POST' });
    toast(`Loaded ${proposals.length} readings from the synthetic Oder timeline.`);
    await refresh();
  });
}

async function triggerApproveAll() {
  await withBusy($('#btn-approve-all'), async () => {
    const ids = state.proposals.filter((p) => p.status === 'pending').map((p) => p.id);
    if (!ids.length) { toast('Nothing is pending.'); return; }
    const result = await request('/proposals/approve-batch', {
      method: 'POST',
      body: JSON.stringify({ reviewer: reviewer(), proposal_ids: ids }),
    });
    const failed = result.failures.length;
    toast(`Approved ${result.approved.length}${failed ? `; ${failed} need a reviewer correction` : ''}.`);
    await refresh();
  });
}

async function triggerSituation() {
  await withBusy($('#btn-situation'), async () => {
    state.situation = await request('/ai/situation-report', { method: 'POST' });
    switchView('audit');
    render();
  });
}

async function approveProposal(id) {
  const secondary = state.secondaryPicks[id];
  await request(`/proposals/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({
      reviewer: reviewer(),
      ...(secondary ? { secondary_coding: secondary } : {}),
    }),
  });
  toast('Approved. FHIR resources built and the policy evaluated.');
  await refresh();
}

async function rejectProposal(id) {
  await request(`/proposals/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reviewer: reviewer(), reason: 'Rejected during review' }),
  });
  toast('Rejected. The decision is recorded and immutable.');
  await refresh();
}

async function suggestTerminology(id) {
  state.suggestions[id] = await request(`/proposals/${id}/terminology-suggestions`);
  render();
}

/* ── Theme ──────────────────────────────────────────────────────────────── */

function currentTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === 'light' || saved === 'dark') return saved;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('#icon-theme').outerHTML =
    (theme === 'dark' ? I.sun : I.moon).replace('<svg', '<svg id="icon-theme"');
}
function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

/* ── Keyboard ───────────────────────────────────────────────────────────── */

let gPending = false; let gTimer;

function isTyping(e) {
  const t = e.target;
  return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
}

function handleKeydown(e) {
  // Palette
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault(); openPalette(); return;
  }
  if (state.palette.open) {
    if (e.key === 'Escape') { closePalette(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); state.palette.cursor++; renderPalette(); return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); state.palette.cursor--; renderPalette(); return; }
    if (e.key === 'Enter') {
      const items = paletteMatches();
      if (items[state.palette.cursor]) runPaletteCommand(items[state.palette.cursor].id);
      return;
    }
    return;
  }

  if (e.key === 'Escape') {
    $('#overlay-help').classList.remove('show');
    if (state.drawer.open) closeDrawer();
    if (state.aiDrawer.open) closeAiDrawer();
    return;
  }

  if (isTyping(e)) return;

  // Help
  if (e.key === '?') { e.preventDefault(); $('#overlay-help').classList.add('show'); return; }

  // Theme
  if (e.key === 't' || e.key === 'T') { toggleTheme(); return; }

  // g→x navigation
  if (e.key === 'g') {
    gPending = true;
    clearTimeout(gTimer);
    gTimer = setTimeout(() => { gPending = false; }, 1200);
    return;
  }
  if (gPending) {
    const map = { o: 'overview', r: 'review', i: 'ingest', s: 'sites', a: 'alerts', u: 'audit' };
    const target = map[e.key.toLowerCase()];
    gPending = false;
    if (target) { switchView(target); return; }
  }

  // Review-queue nav
  if (state.view === 'review') {
    const pending = state.proposals.filter((p) => state.filter === 'all' || p.status === state.filter);
    if (!pending.length) return;
    if (e.key === 'j' || e.key === 'J') {
      state.focusIndex = Math.min(pending.length - 1, state.focusIndex + 1);
      renderReview(); scrollFocusedIntoView(); return;
    }
    if (e.key === 'k' || e.key === 'K') {
      state.focusIndex = Math.max(0, state.focusIndex - 1);
      renderReview(); scrollFocusedIntoView(); return;
    }
    const target = pending[state.focusIndex];
    if (!target) return;
    if ((e.key === 'a' || e.key === 'A') && target.status === 'pending') {
      approveProposal(target.id).catch((err) => toast(err.message, true));
      return;
    }
    if ((e.key === 'r' || e.key === 'R') && target.status === 'pending') {
      rejectProposal(target.id).catch((err) => toast(err.message, true));
      return;
    }
    if ((e.key === 't' || e.key === 'T') && target.status === 'pending') {
      suggestTerminology(target.id).catch((err) => toast(err.message, true));
      return;
    }
  }
}

function scrollFocusedIntoView() {
  const node = $('.proposal.is-focused');
  if (node) node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

/* ── Bootstrap event wiring ─────────────────────────────────────────────── */

function wire() {
  $$('.nav-item').forEach((n) => n.addEventListener('click', () => switchView(n.dataset.view)));
  $$('.tab').forEach((tab) => tab.addEventListener('click', () => {
    state.filter = tab.dataset.filter;
    $$('.tab').forEach((t) => t.classList.toggle('is-active', t === tab));
    state.focusIndex = 0;
    renderReview();
  }));

  $('#reviewer-name').value = localStorage.getItem(REVIEWER_KEY) || '';
  $('#reviewer-name').addEventListener('change', (e) => {
    localStorage.setItem(REVIEWER_KEY, e.target.value.trim());
  });

  $('#reading-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const payload = {
      source_id: 'manual-console',
      source_type: 'agency',
      parameter: data.get('parameter'),
      value: Number(data.get('value')),
      unit: data.get('unit'),
      observed_at: new Date().toISOString(),
      site_code: 'oder-kostrzyn',
      site_name: data.get('site_name'),
      latitude: Number(data.get('latitude')),
      longitude: Number(data.get('longitude')),
    };
    await withBusy(e.currentTarget.querySelector('button[type=submit]'), async () => {
      await request('/proposals', { method: 'POST', body: JSON.stringify(payload) });
      toast('Proposal created. It is pending in the review queue.');
      switchView('review');
      await refresh();
    });
  });

  $('#intake-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    await withBusy($('#intake-submit'), async () => {
      const result = await request('/intake', {
        method: 'POST',
        body: JSON.stringify({
          text: data.get('text'),
          source_id: data.get('source_id'),
          source_type: 'agency',
          default_site_code: data.get('default_site_code'),
          default_site_name: 'Oder at Kostrzyn',
        }),
      });
      $('#intake-warnings').innerHTML = result.warnings
        .map((w) => `<p class="note">${esc(w)}</p>`).join('');
      toast(`Extracted ${result.extracted_count} reading(s) into the review queue.`);
      switchView('review');
      await refresh();
    });
  });

  $('#proposal-list').addEventListener('click', async (e) => {
    const button = e.target.closest('button');
    // Row click (not on a button) opens the detail drawer.
    if (!button) {
      const row = e.target.closest('.proposal');
      if (row?.dataset.proposalId) openDrawer(row.dataset.proposalId);
      return;
    }
    const { approve, reject, suggest, pick } = button.dataset;

    if (suggest) {
      await withBusy(button, async () => { await suggestTerminology(suggest); });
      return;
    }
    if (pick) {
      state.secondaryPicks[pick] = {
        system:  button.dataset.system,
        code:    button.dataset.code,
        display: button.dataset.display,
      };
      toast(`${button.dataset.code} will attach when this proposal is approved.`);
      render();
      return;
    }
    if (!approve && !reject) return;
    await withBusy(button, async () => {
      approve ? await approveProposal(approve) : await rejectProposal(reject);
    });
  });

  // Search input
  $('#review-search').addEventListener('input', debounce((e) => {
    state.search = e.target.value; state.focusIndex = 0; renderReview();
  }, 80));

  // Drawer wiring — delegated so it survives re-renders
  $('#overlay-drawer').addEventListener('click', (e) => {
    if (e.target.id === 'overlay-drawer') { closeDrawer(); return; }
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.id === 'drawer-close' || btn.id === 'drawer-close-2') { closeDrawer(); return; }
    if (btn.id === 'drawer-approve') { drawerApprove(); return; }
    if (btn.id === 'drawer-reject')  { drawerReject();  return; }
    const pick = btn.dataset.drawerPick;
    if (pick) {
      state.drawer.override = state.drawer.override || {};
      state.drawer.override.code = pick;
      renderDrawer();
    }
  });
  $('#overlay-drawer').addEventListener('input', (e) => {
    if (['ovr-code', 'ovr-value', 'ovr-unit'].includes(e.target.id)) {
      captureOverride();
      // Re-render only the compare row + action label — cheap to redo whole drawer.
      renderDrawer();
      // Restore focus + caret on the field the user is typing in.
      const f = $(`#${e.target.id}`);
      if (f) { f.focus(); if (f.setSelectionRange && f.value) f.setSelectionRange(f.value.length, f.value.length); }
    }
  });

  // AI drawer — click the AI chip in topbar
  $('#chip-ai').classList.add('clickable-chip');
  $('#chip-ai').addEventListener('click', openAiDrawer);
  $('#overlay-ai').addEventListener('click', (e) => {
    if (e.target.id === 'overlay-ai' || e.target.closest('#ai-drawer-close')) closeAiDrawer();
  });

  $('#alert-list').addEventListener('click', async (e) => {
    const button = e.target.closest('button[data-brief]');
    if (!button) return;
    await withBusy(button, async () => {
      const audience = button.dataset.audience;
      await request(`/alerts/${button.dataset.brief}/briefings?audience=${encodeURIComponent(audience)}`,
        { method: 'POST' });
      toast(`Draft advisory ready for ${audience}.`);
      await refresh();
    });
  });

  $('#btn-replay').addEventListener('click', triggerReplay);
  $('#btn-approve-all').addEventListener('click', triggerApproveAll);
  $('#btn-situation').addEventListener('click', triggerSituation);
  $('#btn-refresh').addEventListener('click', refresh);
  $('#btn-print').addEventListener('click', () => window.print());
  $('#btn-theme').addEventListener('click', toggleTheme);
  $('#btn-palette').addEventListener('click', openPalette);

  $('#palette-input').addEventListener('input', debounce((e) => {
    state.palette.query = e.target.value; state.palette.cursor = 0; renderPalette();
  }, 60));
  $('#palette-list').addEventListener('click', (e) => {
    const button = e.target.closest('button[data-cmd]');
    if (button) runPaletteCommand(button.dataset.cmd);
  });
  $('#overlay-palette').addEventListener('click', (e) => {
    if (e.target === $('#overlay-palette')) closePalette();
  });
  $('#overlay-help').addEventListener('click', (e) => {
    if (e.target === $('#overlay-help')) e.currentTarget.classList.remove('show');
  });

  document.addEventListener('keydown', handleKeydown);
}

/* ── Boot ───────────────────────────────────────────────────────────────── */

applyTheme(currentTheme());
wire();
refresh();

// Passive tick: refresh "N min ago" without a full data pull.
setInterval(() => {
  if (!state.loading) { renderActivity(); renderProvenanceRows(); }
}, 30000);

// Live poll every 15s while the tab is visible. Skips when a drawer or the
// palette is open — the user is mid-decision, don't yank state out from under.
setInterval(() => {
  if (document.hidden) return;
  if (state.drawer.open || state.aiDrawer.open || state.palette.open) return;
  if (state.loading) return;
  refresh().catch(() => { /* toast already fired inside request */ });
}, 15000);
