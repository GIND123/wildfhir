/* AquaFHIR Bridge — review console
   Vanilla ES2020, no build step. `state` is the single source of truth; every
   mutation ends in render() so counts, boards and drawers can never disagree. */

(() => {
  "use strict";

  const API = "/api/v1";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));
  const POLL_MS = 20000;

  const PAGES = ["flow", "board", "list", "alerts", "advisories", "reports", "audit", "policy", "integrations"];
  const PAGE_TITLES = {
    flow: "Data flow", board: "Board", list: "Queue", alerts: "Incidents", advisories: "Advisories",
    reports: "Reports", audit: "Audit log", policy: "Policy & catalog", integrations: "Integrations",
  };
  const AUDIENCE_LABEL = {
    "public-health": "Public health", veterinary: "Veterinary", "water-authority": "Water authority",
  };
  const EVENT_LABEL = {
    "mapping-proposed": "Proposed", "mapping-approved": "Approved", "mapping-rejected": "Rejected",
    "alert-created": "Incident raised", "briefing-drafted": "Advisory drafted",
    "situation-report": "Situation report", "unstructured-intake": "Bulletin intake",
  };

  const state = {
    page: "board",
    health: {}, ai: { enabled: false }, umls: { enabled: false },
    integrations: null, catalog: { system: null, codes: [] },
    proposals: [], alerts: [], briefings: [], provenance: [], chain: null,
    observations: {},        // proposal id -> {observation, fhir_response} from approvals in this session
    suggestions: {},         // proposal id -> TerminologyMatch[]
    picks: {},               // proposal id -> chosen secondary Coding
    taxa: {},                // proposal id -> GBIF TerminologyMatch[]
    taxonPicks: {},          // proposal id -> chosen taxon Coding
    keys: new Map(),         // proposal id -> AQF-n
    situation: null,
    lastRefresh: null,
    drawer: null,            // {kind:'proposal'|'alert'|'entry', id, tab}
    focus: null,             // focused proposal/alert id for j/k
    selected: new Set(),     // list bulk selection
    filters: {
      board: { q: "", quick: new Set(), site: "", source: "" },
      list: { q: "", status: "pending", quick: new Set(), site: "", proposer: "", sort: "observed", dir: "desc" },
      alerts: { q: "", quick: new Set(), audience: "" },
      briefs: { q: "", audience: "" },
      audit: { q: "", events: new Set(), limit: 50 },
    },
    pending: { rejectIds: [], approveId: null, dragId: null },
    pingResults: {},
  };

  /* ── plumbing ─────────────────────────────────────────────────────────── */

  async function api(path, options = {}) {
    const response = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body.detail === "string") detail = body.detail;
        else if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      } catch (_) { /* non-JSON body */ }
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const icon = (name, cls = "ic sm") => `<svg class="${cls}"><use href="#i-${name}"/></svg>`;

  function toast(message, kind = "ok", action = null) {
    const host = $("#toasts");
    const node = document.createElement("div");
    node.className = `toast ${kind}`;
    node.innerHTML = `${icon(kind === "bad" ? "alert" : "check")}<span>${esc(message)}</span>${action ? `<button class="btn" type="button">${esc(action.label)}</button>` : ""}`;
    if (action) $("button", node).addEventListener("click", () => { action.run(); node.remove(); });
    while (host.children.length >= 3) host.firstChild.remove();
    host.appendChild(node);
    window.setTimeout(() => node.remove(), kind === "bad" ? 7000 : 4200);
  }

  async function busy(button, work) {
    if (button) { button.classList.add("busy"); button.disabled = true; }
    try {
      return await work();
    } catch (error) {
      toast(error.message, "bad");
      return undefined;
    } finally {
      if (button) { button.classList.remove("busy"); button.disabled = false; }
    }
  }

  async function copy(text, label = "Copied") {
    try {
      await navigator.clipboard.writeText(text);
      toast(label);
    } catch (_) {
      toast("Clipboard unavailable in this context", "bad");
    }
  }

  function ago(iso) {
    if (!iso) return "-";
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 45) return "just now";
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    if (s < 86400 * 14) return `${Math.round(s / 86400)}d ago`;
    return new Date(iso).toISOString().slice(0, 10);
  }
  function fdate(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
  }
  function fnum(n) {
    if (n === null || n === undefined) return "-";
    const v = Number(n);
    return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  }
  function initials(name) {
    const parts = String(name || "").replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
    return (parts.length ? parts.slice(0, 2).map((p) => p[0]).join("") : "?").toUpperCase();
  }
  function reviewer() { return (window.localStorage.getItem("aquafhir.reviewer") || "").trim(); }
  function requireReviewer() {
    if (reviewer()) return true;
    openModal("modal-reviewer");
    toast("Set your reviewer identity first. It is written into the audit chain.", "bad");
    return false;
  }

  /* ── derived data ─────────────────────────────────────────────────────── */

  function assignKeys() {
    const ordered = [...state.proposals].sort((a, b) => new Date(a.created_at) - new Date(b.created_at) || a.id.localeCompare(b.id));
    ordered.forEach((p, i) => { if (!state.keys.has(p.id)) state.keys.set(p.id, `AQF-${i + 1}`); });
  }
  const keyOf = (id) => state.keys.get(id) || id.slice(0, 8);
  const byId = (id) => state.proposals.find((p) => p.id === id);
  const alertById = (id) => state.alerts.find((a) => a.id === id);
  const isUnresolved = (p) => p.normalized_value === null || p.normalized_value === undefined || !p.normalized_unit;
  const isFlagged = (p) => Boolean(p.ai && (p.ai.disagreed_with_rules || p.ai.needs_expert_review)) || (!p.coding);
  const isLow = (p) => p.confidence < 0.8;
  const sites = () => [...new Set(state.proposals.map((p) => p.reading.site_name))].sort();
  const proposalTitle = (p) => `${p.reading.parameter} ${p.coding ? "→ " + p.coding.code : "→ no code"}`;
  const eventTypes = () => [...new Set(state.provenance.map((e) => e.event_type))].sort();
  const observationIdFor = (p) => state.observations[p.id]?.observation?.id;

  function matchText(p, q) {
    if (!q) return true;
    const hay = [keyOf(p.id), p.id, p.reading.parameter, p.reading.site_name, p.reading.site_code, p.reading.source_id,
      p.reading.source_type, p.coding?.code, p.coding?.display, p.proposer, p.reviewer, p.rationale].join(" ").toLowerCase();
    return q.toLowerCase().split(/\s+/).every((t) => hay.includes(t));
  }
  function applyProposalFilters(list, f) {
    return list.filter((p) => {
      if (!matchText(p, f.q)) return false;
      if (f.site && p.reading.site_name !== f.site) return false;
      if (f.source && p.reading.source_type !== f.source) return false;
      if (f.proposer && p.proposer !== f.proposer) return false;
      if (f.quick.has("ai") && !p.ai) return false;
      if (f.quick.has("flag") && !isFlagged(p)) return false;
      if (f.quick.has("unres") && !isUnresolved(p)) return false;
      if (f.quick.has("low") && !isLow(p)) return false;
      return true;
    });
  }

  /* ── small renderers ──────────────────────────────────────────────────── */

  const statusLz = (s) => `<span class="lz ${s === "approved" ? "green" : s === "rejected" ? "red" : "blue"}">${esc(s)}</span>`;
  const srcGlyph = (t) => `<span class="src ${esc(t)}" title="${esc(t)}">${esc(String(t).slice(0, 1))}</span>`;
  function meter(c) {
    const pct = Math.round(c * 100);
    return `<span class="meter ${c >= 0.9 ? "" : c >= 0.7 ? "mid" : "low"}" title="confidence ${pct}%"><i style="--pct:${pct}%"></i>${pct}%</span>`;
  }
  const proposerLz = (p) => p.proposer === "gemini-assisted"
    ? `<span class="lz purple">${icon("sparkle", "ic")}AI</span>` : `<span class="lz">rules</span>`;
  function flagLzs(p) {
    const out = [];
    if (!p.coding) out.push('<span class="lz red">no code</span>');
    if (isUnresolved(p) && p.coding) out.push('<span class="lz amber">unit</span>');
    if (p.ai?.disagreed_with_rules) out.push('<span class="lz amber">disagrees</span>');
    if (p.ai?.needs_expert_review) out.push('<span class="lz amber">expert</span>');
    if (p.secondary_coding) out.push(`<span class="lz teal">${esc(p.secondary_coding.code)}</span>`);
    if (p.taxon) out.push('<span class="lz">taxon</span>');
    return out.join("");
  }
  const tagm = (value, full = value) => `<span class="tagm" data-copy="${esc(full)}" title="Click to copy">${esc(value)}</span>`;
  const audLz = (a) => `<span class="lz lc">${esc(AUDIENCE_LABEL[a] || a)}</span>`;
  const sevLz = (s) => `<span class="lz bold ${s === "critical" ? "red" : s === "high" ? "amber" : "blue"}">${esc(s)}</span>`;
  function summaryHtml(p) {
    const code = p.coding ? `<span class="code">${esc(p.coding.code)}</span>` : `<span class="unres">no curated match</span>`;
    return `${esc(p.reading.parameter)}<span class="to">→</span>${code}`;
  }

  /* ── data flow (wire diagram) ─────────────────────────────────────────── */

  // from, to, and which edge of each node the wire leaves and enters.
  const WIRES = [
    ["fn-ingest", "r", "fn-coding", "l", ""],
    ["fn-coding", "r", "fn-review", "l", ""],
    ["fn-review", "r", "fn-fhir", "l", ""],
    ["fn-fhir", "r", "fn-policy", "l", ""],
    ["fn-policy", "r", "fn-router", "l", ""],
    ["fn-gemini", "b", "fn-coding", "t", "is-dashed"],
    ["fn-umls", "b", "fn-review", "t", "is-dashed"],
    ["fn-router", "b", "fa-public", "t", ""],
    ["fn-router", "b", "fa-vet", "t", ""],
    ["fn-router", "b", "fa-water", "t", ""],
  ];

  // Wires are measured from the live DOM rather than hard-coded, so the diagram
  // survives any container width, font size, or wrapped label.
  function drawWires() {
    const canvas = $("#flow-canvas"), svg = $("#flow-wires");
    if (!canvas || !svg || !canvas.offsetParent) return;   // page hidden: nothing to measure
    const base = canvas.getBoundingClientRect();
    if (!base.width || !base.height) return;
    svg.setAttribute("viewBox", `0 0 ${base.width} ${base.height}`);
    svg.setAttribute("width", base.width);
    svg.setAttribute("height", base.height);

    // Anchor on the port dot when the node draws one, so CSS can move a port
    // (to clear the gate badge, say) and the wire follows it automatically.
    const anchor = (id, side) => {
      const el = document.getElementById(id);
      if (!el) return null;
      const port = el.querySelector(`.fport-${side}`);
      if (port) {
        const p = port.getBoundingClientRect();
        return [p.left - base.left + p.width / 2, p.top - base.top + p.height / 2];
      }
      const r = el.getBoundingClientRect();
      const x = r.left - base.left, y = r.top - base.top;
      if (side === "r") return [x + r.width, y + r.height / 2];
      if (side === "l") return [x, y + r.height / 2];
      if (side === "t") return [x + r.width / 2, y];
      return [x + r.width / 2, y + r.height];        // "b"
    };

    // The wire stops short of the target port so the arrowhead sits in clear
    // space instead of being covered by the port dot, which paints above the SVG.
    const GAP = 11;
    const PULL = { l: [-GAP, 0, 0], r: [GAP, 0, 180], t: [0, -GAP, 90], b: [0, GAP, 270] };

    let out = "";
    WIRES.forEach(([from, fs, to, ts, cls], i) => {
      const a = anchor(from, fs), b = anchor(to, ts);
      if (!a || !b) return;
      const [dx, dy, ang] = PULL[ts];
      const end = [b[0] + dx, b[1] + dy];
      const horizontal = (fs === "r" || fs === "l") && (ts === "r" || ts === "l");
      let d;
      if (horizontal) {
        const k = Math.max(18, Math.abs(end[0] - a[0]) * 0.45);
        d = `M ${a[0]} ${a[1]} C ${a[0] + k} ${a[1]}, ${end[0] - k} ${end[1]}, ${end[0]} ${end[1]}`;
      } else {
        const k = Math.max(16, Math.abs(end[1] - a[1]) * 0.55);
        d = `M ${a[0]} ${a[1]} C ${a[0]} ${a[1] + k}, ${end[0]} ${end[1] - k}, ${end[0]} ${end[1]}`;
      }
      // Arrowhead is a rotated triangle so it inherits the lit stroke colour.
      out += `<path d="${d}" class="${cls}" data-from="${from}" data-to="${to}" data-i="${i}"/>`;
      out += `<polygon class="wire-head" data-i="${i}" points="0,-3.6 7,0 0,3.6" transform="translate(${end[0]} ${end[1]}) rotate(${ang})"/>`;
    });
    svg.innerHTML = out;
  }

  // Hovering or focusing a node lights only the wires touching it, and lifts
  // that node above its neighbours so its tooltip is never painted behind them.
  function litWires(id) {
    $$("#flow-wires path").forEach((p) => {
      const on = Boolean(id) && (p.dataset.from === id || p.dataset.to === id);
      p.classList.toggle("is-lit", on);
      const head = $(`#flow-wires polygon[data-i="${p.dataset.i}"]`);
      if (head) head.classList.toggle("is-lit", on);
    });
    $$("#flow-canvas .is-hot").forEach((el) => el.classList.remove("is-hot"));
    const node = id && document.getElementById(id);
    if (!node) return;
    node.classList.add("is-hot");
    const group = node.closest(".fout");        // audience chips share one wrapper
    if (group) group.classList.add("is-hot");
  }

  function renderFlow() {
    const set = (sel, v) => { const n = $(sel); if (n) n.textContent = v; };
    const pending = state.proposals.filter((p) => p.status === "pending").length;
    const approved = state.proposals.filter((p) => p.status === "approved").length;
    const coded = state.proposals.filter((p) => p.coding).length;
    const secondary = state.provenance.filter(
      (e) => e.event_type === "mapping-approved" && e.payload.reviewer_attached_secondary_coding).length;

    set("#flow-c-ingest", state.proposals.length);
    set("#flow-c-coding", coded);
    set("#flow-c-review", pending);
    set("#flow-c-fhir", approved);
    set("#flow-c-policy", state.alerts.length);
    set("#flow-c-alerts", state.briefings.length);
    set("#flow-c-gemini", state.proposals.filter((p) => p.ai).length);
    set("#flow-c-umls", secondary);

    const byAudience = (a) => state.alerts.filter((x) => x.audiences.includes(a)).length;
    [["public-health", "#flow-a-public", "#fa-public"], ["veterinary", "#flow-a-vet", "#fa-vet"],
      ["water-authority", "#flow-a-water", "#fa-water"]].forEach(([aud, numSel, chipSel]) => {
      const n = byAudience(aud);
      set(numSel, n);
      const chip = $(chipSel);
      if (chip) chip.classList.toggle("is-active", n > 0);
    });

    const badge = $("#flow-ledger-status");
    if (badge) {
      if (!state.chain) {
        badge.className = "flow-ledger-status idle";
        badge.textContent = "Not verified yet";
      } else if (state.chain.valid) {
        badge.className = "flow-ledger-status";
        badge.textContent = `${state.chain.entries_checked} ${state.chain.entries_checked === 1 ? "entry" : "entries"} verified`;
      } else {
        badge.className = "flow-ledger-status bad";
        badge.textContent = `Broken at entry ${state.chain.first_invalid_sequence}`;
      }
    }
    requestAnimationFrame(drawWires);
  }

  /* ── board ────────────────────────────────────────────────────────────── */

  function cardHtml(p) {
    const flag = !p.coding ? "flag-bad" : (isFlagged(p) || isUnresolved(p)) ? "flag-warn" : "";
    const val = isUnresolved(p) ? `<span class="lz amber">unit unresolved</span>` : `${fnum(p.normalized_value)} ${esc(p.normalized_unit)}`;
    return `<article class="card ${flag} ${state.focus === p.id ? "is-selected" : ""}" data-open="${p.id}" draggable="${p.status === "pending"}" data-drag="${p.id}">
      <div class="card-title">${summaryHtml(p)}</div>
      <div class="card-sub">${srcGlyph(p.reading.source_type)}<span>${esc(p.reading.site_name)}</span><span>·</span><span>${val}</span></div>
      <div class="card-foot">
        <span class="key">${keyOf(p.id)}</span>
        <div class="card-flags">${flagLzs(p)}</div>
        ${proposerLz(p)}
        ${meter(p.confidence)}
        ${p.reviewer ? `<span class="avatar" title="${esc(p.reviewer)}">${esc(initials(p.reviewer))}</span>` : ""}
      </div>
    </article>`;
  }

  function renderBoard() {
    const f = state.filters.board;
    const shown = applyProposalFilters(state.proposals, f);
    const cols = [
      { s: "pending", title: "Pending review", hint: "Drag a card to Approved or Rejected, or open it." },
      { s: "approved", title: "Approved · published", hint: "Approved mappings become OAH Observations." },
      { s: "rejected", title: "Rejected", hint: "Decisions are immutable and hash-chained." },
    ];
    $("#board").innerHTML = cols.map((c) => {
      const items = shown.filter((p) => p.status === c.s);
      return `<div class="col" data-col="${c.s}">
        <div class="col-head">${esc(c.title)}<span class="count">${items.length}</span>
          ${c.s === "pending" && items.length ? `<button class="btn sm subtle" type="button" data-approve-shown>Approve ${items.length}</button>` : ""}
        </div>
        <div class="col-body">${items.length ? items.map(cardHtml).join("") : `<div class="col-empty">${esc(c.hint)}</div>`}</div>
      </div>`;
    }).join("");
    $$("#board-quick .chipf").forEach((b) => b.classList.toggle("is-on", f.quick.has(b.dataset.q)));
    const reviewers = [...new Set(state.proposals.map((p) => p.reviewer).filter(Boolean))].slice(0, 6);
    $("#board-avatars").innerHTML = reviewers.map((r) => `<span class="avatar" title="${esc(r)}">${esc(initials(r))}</span>`).join("");
  }

  /* ── queue list ───────────────────────────────────────────────────────── */

  function sortProposals(list, sort, dir) {
    const m = dir === "asc" ? 1 : -1;
    const val = {
      key: (p) => Number(keyOf(p.id).split("-")[1]) || 0,
      summary: (p) => p.reading.parameter.toLowerCase(),
      status: (p) => p.status,
      site: (p) => p.reading.site_name.toLowerCase(),
      proposer: (p) => p.proposer,
      confidence: (p) => p.confidence,
      observed: (p) => new Date(p.reading.observed_at).getTime(),
    }[sort] || ((p) => new Date(p.created_at).getTime());
    return [...list].sort((a, b) => { const x = val(a), y = val(b); return x < y ? -m : x > y ? m : 0; });
  }

  function renderList() {
    const f = state.filters.list;
    let shown = applyProposalFilters(state.proposals, f);
    if (f.status !== "all") shown = shown.filter((p) => p.status === f.status);
    shown = sortProposals(shown, f.sort, f.dir);
    for (const id of [...state.selected]) if (!shown.some((p) => p.id === id && p.status === "pending")) state.selected.delete(id);

    $("#list-rows").innerHTML = shown.length ? shown.map((p) => `<tr data-open="${p.id}" class="${state.selected.has(p.id) ? "is-selected" : ""} ${state.focus === p.id ? "is-focus" : ""}">
        <td>${p.status === "pending" ? `<input type="checkbox" data-select="${p.id}" ${state.selected.has(p.id) ? "checked" : ""} aria-label="Select ${keyOf(p.id)}" />` : ""}</td>
        <td class="nowrap"><span class="key">${keyOf(p.id)}</span></td>
        <td class="summary">${summaryHtml(p)} <span class="dim">${isUnresolved(p) ? "" : `· ${fnum(p.normalized_value)} ${esc(p.normalized_unit)}`}</span> ${flagLzs(p)}</td>
        <td>${statusLz(p.status)}</td>
        <td class="nowrap">${esc(p.reading.site_name)}</td>
        <td class="nowrap">${srcGlyph(p.reading.source_type)} <span class="dim">${esc(p.reading.source_id)}</span></td>
        <td>${proposerLz(p)}</td>
        <td class="num">${meter(p.confidence)}</td>
        <td class="nowrap dim" title="${esc(fdate(p.reading.observed_at))}">${esc(fdate(p.reading.observed_at).slice(0, 16))}</td>
        <td class="nowrap">${p.reviewer ? `<span class="avatar" title="${esc(p.reviewer)}" style="display:inline-grid;vertical-align:middle">${esc(initials(p.reviewer))}</span> <span class="dim">${esc(p.reviewer)}</span>` : '<span class="dim">Unassigned</span>'}</td>
      </tr>`).join("")
      : `<tr><td colspan="10"><div class="empty" style="box-shadow:none"><b>No proposals match</b>${state.proposals.length ? "Adjust the filters above." : "Create a reading or load the Oder replay."}</div></td></tr>`;

    const counts = { pending: 0, approved: 0, rejected: 0 };
    state.proposals.forEach((p) => { counts[p.status] = (counts[p.status] || 0) + 1; });
    $("#c-pending").textContent = counts.pending; $("#c-approved").textContent = counts.approved; $("#c-rejected").textContent = counts.rejected;
    $$("#list-status button").forEach((b) => b.classList.toggle("is-on", b.dataset.s === f.status));
    $$("#list-quick .chipf").forEach((b) => b.classList.toggle("is-on", f.quick.has(b.dataset.q)));
    $$("#list-table th.sortable").forEach((th) => th.classList.toggle("sorted", th.dataset.sort === f.sort));
    const pendingShown = shown.filter((p) => p.status === "pending");
    $("#list-check-all").checked = pendingShown.length > 0 && pendingShown.every((p) => state.selected.has(p.id));
    $("#list-check-all").disabled = pendingShown.length === 0;
    $("#bulkbar").classList.toggle("show", state.selected.size > 0);
    $("#bulk-count").textContent = `${state.selected.size} selected`;
  }

  /* ── incidents ────────────────────────────────────────────────────────── */

  function ruleFor(alert) {
    return (state.integrations?.policy?.rules || []).find((r) => r.code === alert.rule_code) || null;
  }
  function filteredAlerts() {
    const f = state.filters.alerts;
    return state.alerts.filter((a) => {
      const drafted = state.briefings.filter((b) => b.alert_id === a.id).map((b) => b.audience);
      if (f.audience && !a.audiences.includes(f.audience)) return false;
      if (f.quick.has("critical") && a.severity !== "critical") return false;
      if (f.quick.has("high") && a.severity !== "high") return false;
      if (f.quick.has("undrafted") && a.audiences.every((x) => drafted.includes(x))) return false;
      if (f.q) {
        const hay = [a.rule_code, a.message, a.site_code, a.severity, a.policy_id, ...a.audiences].join(" ").toLowerCase();
        if (!f.q.toLowerCase().split(/\s+/).every((t) => hay.includes(t))) return false;
      }
      return true;
    }).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  }

  function renderAlerts() {
    const f = state.filters.alerts;
    const list = filteredAlerts();
    const crit = state.alerts.filter((a) => a.severity === "critical").length;
    const undrafted = state.alerts.filter((a) => {
      const done = state.briefings.filter((b) => b.alert_id === a.id).map((b) => b.audience);
      return a.audiences.some((x) => !done.includes(x));
    }).length;
    $("#alert-tiles").innerHTML = [
      ["Open incidents", state.alerts.length, "raised by policy"],
      ["Critical", crit, "highest severity"],
      ["Awaiting advisory", undrafted, "at least one audience undrafted"],
      ["Advisory drafts", state.briefings.length, "AI-drafted, disclaimed"],
    ].map(([l, v, s]) => `<div class="tile"><div class="lbl">${l}</div><div class="val">${v}</div><div class="sub">${s}</div></div>`).join("");

    $("#alert-list").innerHTML = list.length ? list.map((a) => {
      const done = new Set(state.briefings.filter((b) => b.alert_id === a.id).map((b) => b.audience));
      const rule = ruleFor(a);
      return `<article class="incident ${state.focus === a.id ? "is-selected" : ""}" data-open-alert="${a.id}">
        <div class="sev ${esc(a.severity)}" title="${esc(a.severity)}">${esc(a.severity.slice(0, 1).toUpperCase())}</div>
        <div>
          <h3><span>${esc(a.rule_code)}</span>${sevLz(a.severity)}<span class="key">${esc(a.site_code)}</span></h3>
          <p class="msg">${esc(a.message)}</p>
          <div class="meta">
            <span>observed <b>${esc(fdate(a.observed_at))}</b></span>
            <span>policy <b>${esc(a.policy_id)}</b></span>
            ${rule ? `<span>rule <b>${esc(rule.operator)} ${fnum(rule.value)} ${esc(rule.unit)}</b></span>` : ""}
            <span class="aud">${a.audiences.map((x) => `<span class="lz lc ${done.has(x) ? "green" : ""}" title="${done.has(x) ? "advisory drafted" : "no advisory yet"}">${esc(AUDIENCE_LABEL[x] || x)}</span>`).join("")}</span>
          </div>
        </div>
        <div class="incident-right">
          <span class="value">${fnum(a.value)} ${esc(a.unit)}</span>
          <span>${esc(ago(a.created_at))}</span>
        </div>
      </article>`;
    }).join("") : `<div class="empty"><b>${state.alerts.length ? "No incidents match" : "No thresholds crossed"}</b>${state.alerts.length ? "Adjust the filters above." : "Incidents appear once an approved observation crosses the policy."}</div>`;
    $$("#alert-quick .chipf").forEach((b) => b.classList.toggle("is-on", f.quick.has(b.dataset.q)));
  }

  /* ── advisories ───────────────────────────────────────────────────────── */

  function briefHtml(b, withAlert = true) {
    const a = alertById(b.alert_id);
    return `<div class="brief">
      <h4>${audLz(b.audience)}<span>${esc(b.headline)}</span><span class="lz amber" style="margin-left:auto">${esc(b.status)}</span></h4>
      ${withAlert && a ? `<div class="meta"><span class="key" data-open-alert="${a.id}" style="cursor:pointer">${esc(a.rule_code)} · ${esc(a.site_code)}</span></div>` : ""}
      <p>${esc(b.summary)}</p>
      <ul>${b.recommended_actions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      <p><b>Uncertainty.</b> ${esc(b.uncertainty)}</p>
      <p><b>Escalation question.</b> ${esc(b.escalation_question)}</p>
      <div class="meta">${b.ai ? `${tagm(b.ai.model)}${tagm(b.ai.template_id)}${tagm("prompt " + b.ai.prompt_hash.slice(0, 12), b.ai.prompt_hash)}<span>${b.ai.latency_ms} ms</span>` : ""}<span>${esc(fdate(b.created_at))}</span></div>
      <p class="dis">${esc(b.disclaimer)}</p>
    </div>`;
  }
  function renderBriefs() {
    const f = state.filters.briefs;
    const list = state.briefings.filter((b) => {
      if (f.audience && b.audience !== f.audience) return false;
      if (f.q) {
        const hay = [b.audience, b.headline, b.summary, ...b.recommended_actions].join(" ").toLowerCase();
        if (!f.q.toLowerCase().split(/\s+/).every((t) => hay.includes(t))) return false;
      }
      return true;
    });
    $("#brief-list").innerHTML = list.length ? list.map((b) => briefHtml(b)).join("")
      : `<div class="empty"><b>${state.briefings.length ? "No advisories match" : "No advisories drafted"}</b>${state.ai.enabled ? "Open an incident and draft one per audience." : "Set GEMINI_API_KEY to enable drafting."}</div>`;
  }

  /* ── site map (Leaflet + OpenStreetMap) ───────────────────────────────── */
  /* Tiles come from the OSM public tile server, which is fine for a review
     console's traffic but must be swapped for a proper provider before any
     real deployment. Nothing here needs an API key. */

  const OSM_TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
  const OSM_ATTRIB = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors';
  const NOMINATIM = "https://nominatim.openstreetmap.org/search";
  const map = { instance: null, layer: null, fitted: false, searchTimer: null, lastSearch: 0 };

  // One row per distinct site, with the counts that decide colour and radius.
  function siteRollup() {
    const rows = new Map();
    state.proposals.forEach((p) => {
      const r = p.reading;
      if (!Number.isFinite(r.latitude) || !Number.isFinite(r.longitude)) return;
      const row = rows.get(r.site_code) || {
        code: r.site_code, name: r.site_name, lat: r.latitude, lon: r.longitude,
        total: 0, pending: 0, approved: 0, rejected: 0, sources: new Set(), alerts: [],
      };
      row.total += 1; row[p.status] += 1; row.sources.add(r.source_type);
      rows.set(r.site_code, row);
    });
    state.alerts.forEach((a) => { const row = rows.get(a.site_code); if (row) row.alerts.push(a); });
    return [...rows.values()];
  }

  function siteTone(row) {
    if (row.alerts.some((a) => a.severity === "critical")) return { color: "#c9372c", rank: "Critical incident" };
    if (row.alerts.length) return { color: "#e56910", rank: "High incident" };
    if (row.approved) return { color: "#0c66e4", rank: "Observations published" };
    return { color: "#8590a2", rank: "Pending review only" };
  }

  function renderMap() {
    const host = $("#map-canvas");
    if (!host) return;
    const rows = siteRollup();
    $("#map-count").textContent = rows.length
      ? `${rows.length} site${rows.length === 1 ? "" : "s"} · ${rows.reduce((n, r) => n + r.total, 0)} readings`
      : "no sites yet";

    if (typeof window.L === "undefined") {
      host.classList.add("is-dead");
      host.innerHTML = '<div class="map-empty">Map library did not load. The rest of the console is unaffected.</div>';
      return;
    }
    if (!map.instance) {
      host.classList.remove("is-dead");
      map.instance = window.L.map(host, { scrollWheelZoom: false, worldCopyJump: true })
        .setView([52.4, 14.5], 6);
      const tiles = window.L.tileLayer(OSM_TILES, { maxZoom: 18, attribution: OSM_ATTRIB });
      // The public OSM tile server throttles bursts, which leaves holes in the
      // basemap. Retry each failed tile once rather than showing a torn map.
      tiles.on("tileerror", (event) => {
        const img = event.tile;
        if (!img || img.dataset.retried) return;
        img.dataset.retried = "1";
        const src = img.src;
        window.setTimeout(() => { img.src = ""; img.src = src; }, 900);
      });
      tiles.addTo(map.instance);
      // Scroll-to-zoom only once the reviewer has clicked in, so the page still scrolls.
      map.instance.on("click", () => map.instance.scrollWheelZoom.enable());
      map.instance.on("mouseout", () => map.instance.scrollWheelZoom.disable());
      map.layer = window.L.layerGroup().addTo(map.instance);
    }
    map.layer.clearLayers();
    if (!rows.length) return;

    const max = Math.max(...rows.map((r) => r.total));
    rows.forEach((row) => {
      const tone = siteTone(row);
      const marker = window.L.circleMarker([row.lat, row.lon], {
        radius: 7 + Math.round(9 * Math.sqrt(row.total / max)),
        color: tone.color, weight: 2, fillColor: tone.color, fillOpacity: .38,
      });
      const worst = row.alerts.slice().sort((a, b) =>
        (b.severity === "critical") - (a.severity === "critical"))[0];
      marker.bindPopup(
        `<b>${esc(row.name)}</b>` +
        `<div class="mp-meta">${esc(row.code)} · ${esc([...row.sources].join(", "))}</div>` +
        `<div class="mp-meta">${row.total} readings · ${row.approved} approved · ${row.pending} pending</div>` +
        (worst ? `<div class="mp-meta"><b>${esc(tone.rank)}:</b> ${esc(worst.rule_code)} at ${fnum(worst.value)} ${esc(worst.unit)}</div>` : "") +
        `<a class="mp-link" href="#" data-map-site="${esc(row.code)}">Filter the queue to this site</a>`
      );
      marker.addTo(map.layer);
    });

    if (!map.fitted) {
      map.instance.fitBounds(window.L.latLngBounds(rows.map((r) => [r.lat, r.lon])).pad(0.35), { maxZoom: 11 });
      map.fitted = true;
    }
    // Leaflet needs a nudge when it was first laid out inside a hidden page.
    window.setTimeout(() => map.instance && map.instance.invalidateSize(), 0);
  }

  function fitMapToSites() {
    const rows = siteRollup();
    if (!map.instance || !rows.length) { toast("No sites with coordinates yet.", "bad"); return; }
    map.instance.fitBounds(window.L.latLngBounds(rows.map((r) => [r.lat, r.lon])).pad(0.35), { maxZoom: 11 });
  }

  // Nominatim asks for at most one request a second. The 700 ms debounce plus
  // the hard floor below keeps us inside that even while somebody types fast.
  async function geocode(query) {
    const box = $("#map-suggest");
    if (!query.trim()) { box.hidden = true; return; }
    const wait = Math.max(0, 1000 - (Date.now() - map.lastSearch));
    if (wait) await new Promise((r) => window.setTimeout(r, wait));
    map.lastSearch = Date.now();
    try {
      const url = `${NOMINATIM}?q=${encodeURIComponent(query)}&format=jsonv2&limit=5&addressdetails=0`;
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`Nominatim returned ${response.status}`);
      const hits = await response.json();
      box.hidden = false;
      box.innerHTML = hits.length
        ? hits.map((h) => `<button type="button" data-lat="${h.lat}" data-lon="${h.lon}">${esc(h.display_name)}</button>`).join("")
        : '<div class="ms-empty">No place matched.</div>';
    } catch (error) {
      box.hidden = false;
      box.innerHTML = `<div class="ms-empty">Place search unavailable: ${esc(error.message)}</div>`;
    }
  }

  /* ── reports ──────────────────────────────────────────────────────────── */

  function renderReports() {
    const n = state.proposals.length;
    const c = { pending: 0, approved: 0, rejected: 0 };
    state.proposals.forEach((p) => { c[p.status] += 1; });
    const decided = c.approved + c.rejected;
    const aiShare = n ? Math.round(100 * state.proposals.filter((p) => p.ai).length / n) : 0;
    const overrides = state.provenance.filter((e) => e.event_type === "mapping-approved" && (e.payload.reviewer_overrode_coding || e.payload.reviewer_overrode_quantity)).length;
    const secondary = state.provenance.filter((e) => e.event_type === "mapping-approved" && e.payload.reviewer_attached_secondary_coding).length;
    $("#report-tiles").innerHTML = [
      ["Proposals", n, `${c.pending} pending`],
      ["Approval rate", decided ? `${Math.round(100 * c.approved / decided)}%` : "-", `${c.approved} approved · ${c.rejected} rejected`],
      ["AI-assisted", `${aiShare}%`, "proposals that consulted Gemini"],
      ["Reviewer corrections", overrides, "coding or quantity overridden"],
      ["Second codings", secondary, "LOINC / SNOMED attached"],
      ["Incidents", state.alerts.length, `${state.briefings.length} advisory drafts`],
    ].map(([l, v, s]) => `<div class="tile"><div class="lbl">${l}</div><div class="val">${v}</div><div class="sub">${s}</div></div>`).join("");

    const group = (fn) => {
      const m = new Map();
      state.proposals.forEach((p) => {
        const k = fn(p); const row = m.get(k) || { pending: 0, approved: 0, rejected: 0, alerts: 0, n: 0 };
        row[p.status] += 1; row.n += 1; m.set(k, row);
      });
      return m;
    };
    const table = (m, alertsBy) => m.size ? `<div class="tablewrap" style="box-shadow:none"><table class="tbl"><thead><tr><th>Name</th><th class="num">Total</th><th class="num">Pending</th><th class="num">Approved</th><th class="num">Rejected</th><th class="num">Incidents</th></tr></thead><tbody>${[...m.entries()].map(([k, r]) => `<tr style="cursor:default"><td>${esc(k)}</td><td class="num">${r.n}</td><td class="num">${r.pending}</td><td class="num">${r.approved}</td><td class="num">${r.rejected}</td><td class="num">${alertsBy(k)}</td></tr>`).join("")}</tbody></table></div>` : '<p class="quote">No data yet.</p>';
    const siteCodeByName = new Map(state.proposals.map((p) => [p.reading.site_name, p.reading.site_code]));
    $("#report-sites").innerHTML = table(group((p) => p.reading.site_name), (k) => state.alerts.filter((a) => a.site_code === siteCodeByName.get(k)).length);
    $("#report-sources").innerHTML = table(group((p) => `${p.reading.source_type} · ${p.reading.source_id}`), () => "-");
    renderMap();
    $("#situation-report").innerHTML = state.situation ? situationHtml(state.situation) : "";
    $("#btn-situation").disabled = !state.ai.enabled;
    $("#btn-situation").title = state.ai.enabled ? "" : "Needs GEMINI_API_KEY";
  }
  function situationHtml(r) {
    return `<div class="panel"><div class="panel-head"><h2>Situation report</h2><p>${esc(fdate(r.generated_at))} · ${r.observations_considered} observations, ${r.alerts_considered} incidents, ${r.pending_reviews} pending</p></div>
      <div class="report">
        <div class="headline">${esc(r.headline)}</div>
        <p>${esc(r.situation)}</p>
        ${r.by_site.map((s) => `<div class="site"><b>${esc(s.site_code)}</b><span>${esc(s.assessment)}</span></div>`).join("")}
        <div class="split"><div><h4>Data gaps</h4><ul>${r.data_gaps.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>None recorded</li>"}</ul></div><div><h4>Next steps</h4><ul>${r.next_steps.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>None recorded</li>"}</ul></div></div>
        <div class="meta" style="font-size:12px;color:var(--n60);display:flex;gap:8px;flex-wrap:wrap">${r.ai ? `${tagm(r.ai.model)}${tagm(r.ai.template_id)}${tagm("prompt " + r.ai.prompt_hash.slice(0, 12), r.ai.prompt_hash)}${tagm("response " + r.ai.response_hash.slice(0, 12), r.ai.response_hash)}<span>${r.ai.latency_ms} ms</span>` : ""}</div>
        <p class="quote" style="font-size:12px">${esc(r.disclaimer)}</p>
      </div></div>`;
  }

  /* ── audit ────────────────────────────────────────────────────────────── */

  function actorOf(e) {
    const p = e.payload || {};
    if (p.reviewer) return `${p.reviewer}${p.reason ? ` · ${p.reason}` : ""}${p.reviewer_attached_secondary_coding ? " · +2nd coding" : ""}${p.reviewer_overrode_coding ? " · coding overridden" : ""}${p.reviewer_overrode_quantity ? " · quantity overridden" : ""}`;
    if (e.event_type === "mapping-proposed") return `${p.proposer || "curated-rules"} · ${Math.round((p.confidence || 0) * 100)}%`;
    if (e.event_type === "alert-created") return `${p.severity} · ${p.rule_code} · ${(p.audiences || []).join(", ")}`;
    if (e.event_type === "briefing-drafted") return `${p.audience} · ${p.ai?.model || ""}`;
    if (e.event_type === "unstructured-intake") return `${p.extracted} extracted · ${(p.warnings || []).length} warnings`;
    if (e.event_type === "situation-report") return `${p.observations_considered} obs · ${p.alerts_considered} alerts`;
    return "";
  }
  function renderAudit() {
    const f = state.filters.audit;
    const list = state.provenance.filter((e) => {
      if (f.events.size && !f.events.has(e.event_type)) return false;
      if (f.q) {
        const hay = [e.sequence, e.event_type, e.entity_id, e.hash, e.previous_hash, actorOf(e), keyOf(e.entity_id)].join(" ").toLowerCase();
        if (!f.q.toLowerCase().split(/\s+/).every((t) => hay.includes(t))) return false;
      }
      return true;
    });
    $("#audit-quick").innerHTML = eventTypes().map((t) => `<button class="chipf ${f.events.has(t) ? "is-on" : ""}" data-ev="${esc(t)}" type="button"><span class="evt ${esc(t)}"><i></i>${esc(EVENT_LABEL[t] || t)}</span></button>`).join("");
    $("#audit-rows").innerHTML = list.length ? list.map((e) => {
      const isProposal = e.event_type.startsWith("mapping-");
      return `<tr data-open-entry="${e.sequence}">
        <td class="num dim">${e.sequence}</td>
        <td><span class="evt ${esc(e.event_type)}"><i></i>${esc(EVENT_LABEL[e.event_type] || e.event_type)}</span></td>
        <td class="nowrap">${isProposal && byId(e.entity_id) ? `<span class="key">${keyOf(e.entity_id)}</span> ` : ""}${tagm(e.entity_id.slice(0, 18) + (e.entity_id.length > 18 ? "…" : ""), e.entity_id)}</td>
        <td class="dim">${esc(actorOf(e))}</td>
        <td>${tagm(e.hash.slice(0, 16), e.hash)}</td>
        <td class="nowrap dim" title="${esc(fdate(e.created_at))}">${esc(ago(e.created_at))}</td>
      </tr>`;
    }).join("") : '<tr><td colspan="6" class="dim">No events match.</td></tr>';
    const banner = $("#chain-banner");
    if (state.chain) {
      banner.className = `banner ${state.chain.valid ? "ok" : "bad"}`;
      banner.innerHTML = `${icon("shield", "ic")}<span>${state.chain.valid ? `Hash chain verified across ${state.chain.entries_checked} entries.` : `Chain broken at sequence ${state.chain.first_invalid_sequence}. Stored history has been altered after the fact.`}</span>`;
    }
  }

  /* ── policy & catalog ─────────────────────────────────────────────────── */

  function renderPolicy() {
    const pol = state.integrations?.policy;
    const cat = state.catalog;
    if (pol) {
      $("#policy-status-lz").textContent = pol.status;
      $("#policy-body").innerHTML = `<dl class="dl" style="margin-bottom:12px"><dt>Policy id</dt><dd>${tagm(pol.id)}</dd><dt>Source</dt><dd>${tagm(pol.path)}</dd><dt>Evaluation</dt><dd>Deterministic. First coding on the Observation must equal the rule code and the UCUM unit must match exactly.</dd></dl>
      <div class="tablewrap" style="box-shadow:none"><table class="tbl"><thead><tr><th>Code</th><th>Condition</th><th>Severity</th><th>Routes to</th></tr></thead><tbody>${pol.rules.map((r) => `<tr class="rulerow" style="cursor:default"><td><code>${esc(r.code)}</code></td><td class="nowrap">${esc({ gte: "≥", gt: ">", lte: "≤", lt: "<" }[r.operator] || r.operator)} ${fnum(r.value)} ${esc(r.unit)}</td><td>${sevLz(r.severity)}</td><td><span class="aud">${r.audiences.map(audLz).join("")}</span></td></tr><tr style="cursor:default"><td colspan="4" class="dim" style="padding-top:0">${esc(r.message)}</td></tr>`).join("")}</tbody></table></div>`;
    }
    $("#catalog-count").textContent = `${cat.codes.length} codes`;
    $("#catalog-body").innerHTML = cat.codes.length ? `<dl class="dl" style="margin-bottom:12px"><dt>System</dt><dd>${tagm(cat.system)}</dd><dt>Review threshold</dt><dd>${state.integrations ? `${Math.round(state.integrations.coding.review_confidence_threshold * 100)}% (informational; every proposal still requires review)` : "-"}</dd></dl>
      <div class="tablewrap" style="box-shadow:none"><table class="tbl"><thead><tr><th>Code</th><th>Display</th><th>Aliases</th><th>Plausible</th><th>Units</th></tr></thead><tbody>${cat.codes.map((c) => `<tr style="cursor:default"><td><code>${esc(c.code)}</code></td><td>${esc(c.display)}</td><td class="dim">${c.aliases.map(esc).join(", ")}</td><td class="nowrap dim">${c.plausible_range ? `${fnum(c.plausible_range.min)} – ${fnum(c.plausible_range.max)}` : "-"}</td><td>${c.accepted_units.map((u) => `<span class="lz lc">${esc(u)}</span>`).join(" ")} ${Object.entries(c.unit_conversions || {}).map(([from, cv]) => `<span class="lz lc" title="factor ${cv.factor}">${esc(from)} → ${esc(cv.target)}</span>`).join(" ")}</td></tr>`).join("")}</tbody></table></div>` : '<p class="quote">Catalog unavailable.</p>';
  }

  /* ── integrations ─────────────────────────────────────────────────────── */

  function renderIntegrations() {
    const i = state.integrations;
    if (!i) { $("#integrations").innerHTML = '<div class="empty"><b>Loading</b></div>'; return; }
    const stat = (tone, label) => `<span class="status ${tone}"><i></i>${esc(label)}</span>`;
    const yes = (b, on = "Configured", off = "Not configured") => stat(b ? "ok" : "off", b ? on : off);
    const ping = (name) => {
      const r = state.pingResults[name];
      return `<span class="result ${r ? (r.ok ? "ok" : "bad") : ""}">${r ? esc(r.text) : ""}</span>`;
    };
    const cards = [
      {
        name: "gemini", logo: "G", color: "#1a73e8", title: "Google Gemini", sub: "Coding co-pilot, bulletin intake, advisories, situation reports",
        status: yes(i.gemini.configured, "Live", "Off · deterministic only"),
        rows: [
          ["Credential", i.gemini.key_fingerprint ? `<span class="secret">${esc(i.gemini.key_fingerprint)}</span> <span class="dim">via ${esc(i.gemini.key_env)}</span>` : `<span class="dim">${esc(i.gemini.key_env)} unset</span>`],
          ["Model", tagm(i.gemini.model)],
          ["Endpoint", tagm(i.gemini.api_base)],
          ["Assist mode", `<span class="lz lc">${esc(i.gemini.assist_mode)}</span> <span class="dim">below ${Math.round(i.gemini.assist_below_confidence * 100)}% rule confidence</span>`],
          ["Confidence ceiling", `${Math.round(i.gemini.confidence_ceiling * 100)}% <span class="dim">no AI proposal can read as auto-publishable</span>`],
          ["Limits", `<span class="dim">${i.gemini.timeout_seconds}s timeout · ${i.gemini.max_retries} retries · ${i.gemini.max_output_tokens} tokens · thinking ${i.gemini.thinking_budget}</span>`],
          ["Features", (state.ai.features || []).length ? state.ai.features.map((f) => `<span class="lz lc">${esc(f)}</span>`).join(" ") : '<span class="dim">none</span>'],
        ],
        actions: `<button class="btn sm" data-ping="gemini" type="button">Check status</button><a class="btn sm subtle" href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">Get a key ${icon("external")}</a>`,
      },
      {
        name: "umls", logo: "U", color: "#20558a", title: "NLM UMLS UTS", sub: "SNOMED CT and LOINC top-up for the terminology crosswalk",
        status: yes(i.umls.configured, i.umls.active ? "Live" : "Configured", "Off"),
        rows: [
          ["API key", i.umls.key_fingerprint ? `<span class="secret">${esc(i.umls.key_fingerprint)}</span> <span class="dim">via ${esc(i.umls.key_env)}</span>` : `<span class="dim">${esc(i.umls.key_env)} unset</span>`],
          ["Auth scheme", `<span class="dim">${esc(i.umls.auth_scheme)}</span>`],
          ["Client id", i.umls.client_id ? `${tagm(i.umls.client_id)} <span class="dim">license-flow credential, display only</span>` : '<span class="dim">none recorded</span>'],
          ["Client secret", i.umls.client_secret_fingerprint ? `<span class="secret">${esc(i.umls.client_secret_fingerprint)}</span> <span class="dim">never sent</span>` : '<span class="dim">none recorded</span>'],
          ["Endpoint", tagm(i.umls.api_base)],
          ["Vocabularies", i.umls.vocabularies.map((v) => `<span class="lz lc teal">${esc(v)}</span>`).join(" ")],
          ["Limits", `<span class="dim">${i.umls.timeout_seconds}s timeout · ${i.umls.max_retries} retries</span>`],
        ],
        actions: `<button class="btn sm" data-ping="umls" type="button">Check status</button><a class="btn sm subtle" href="https://uts.nlm.nih.gov/uts/profile" target="_blank" rel="noreferrer">UTS profile ${icon("external")}</a>`,
      },
      {
        name: "loinc", logo: "L", color: "#3b6e22", title: "LOINC table", sub: "Local, offline environmental LOINC search and validation",
        status: yes(i.loinc_table.available, "Loaded", "Missing"),
        rows: [
          ["Path", tagm(i.loinc_table.path)],
          ["Role", '<span class="dim">Finds terms scoped to Water/Air specimens and rejects UMLS results that are LOINC Parts or Metathesaurus ids.</span>'],
          ["Crosswalk sources", (state.umls.sources || []).length ? state.umls.sources.map((s) => `<span class="lz lc">${esc(s)}</span>`).join(" ") : '<span class="lz">none</span>'],
        ],
        actions: `<button class="btn sm" data-ping="terminology" type="button">Check crosswalk</button>`,
      },
      {
        name: "fhir", logo: "F", color: "#c9372c", title: "HAPI FHIR R4", sub: "Publication target for OneAquaHealth resources",
        status: stat(i.fhir.write_enabled ? "ok" : "warn", i.fhir.write_enabled ? "Writes enabled" : "Dry run"),
        rows: [
          ["Base URL", tagm(i.fhir.base_url)],
          ["Write mode", `<span class="dim">${i.fhir.write_enabled ? "Transaction bundles are POSTed to the server." : "Bundles are built and validated but not sent. Set FHIR_WRITE_ENABLED=true to publish."}</span>`],
          ["Observation profile", tagm(i.fhir.observation_profile)],
          ["Location profile", tagm(i.fhir.location_profile)],
          ["Timeout", `<span class="dim">${i.fhir.timeout_seconds}s</span>`],
        ],
        actions: `<button class="btn sm" data-ping="health" type="button">Check bridge</button><a class="btn sm subtle" href="${esc(i.fhir.base_url)}/metadata" target="_blank" rel="noreferrer">Capability statement ${icon("external")}</a>`,
      },
      {
        name: "webhook", logo: "W", color: "#6e5dc6", title: "Subscription webhook", sub: "R4 rest-hook receiver for Observation notifications",
        status: stat(i.webhook.using_default_secret ? "warn" : "ok", i.webhook.using_default_secret ? "Default secret" : "Secret set"),
        rows: [
          ["Endpoint", tagm(`POST ${i.webhook.endpoint}`)],
          ["Header", tagm(i.webhook.header)],
          ["Shared secret", i.webhook.secret_fingerprint ? `<span class="secret">${esc(i.webhook.secret_fingerprint)}</span> <span class="dim">via WEBHOOK_SHARED_SECRET</span>` : '<span class="dim">unset</span>'],
          ["Note", `<span class="dim">${i.webhook.using_default_secret ? "Rotate before any deployment. Demo authentication only." : "Demo authentication only: add TLS, rotation, and replay protection before production."}</span>`],
        ],
        actions: `<button class="btn sm" data-copy-text="curl -X POST ${location.origin}${i.webhook.endpoint} -H 'X-AquaFHIR-Secret: <secret>' -H 'Content-Type: application/json' -d '{}'" type="button">${icon("copy")}Copy curl</button>`,
      },
      {
        name: "app", logo: "A", color: "#0c66e4", title: "Bridge process", sub: "Runtime, storage, and policy wiring",
        status: stat(i.app.env === "production" ? "ok" : "off", i.app.env.charAt(0).toUpperCase() + i.app.env.slice(1)),
        rows: [
          ["Version", tagm(`aquafhir-bridge ${i.app.version}`)],
          ["Database", tagm(i.app.database_path)],
          ["Replay dataset", tagm(i.app.replay_data_path)],
          ["Threshold policy", `${tagm(i.policy.id)} <span class="lz lc amber">${esc(i.policy.status)}</span>`],
          ["Coding catalog", `${tagm(i.coding.path)} <span class="dim">${i.coding.codes} codes</span>`],
          ["API reference", `<a href="/docs" target="_blank" rel="noreferrer">/docs</a> · <a href="/openapi.json" target="_blank" rel="noreferrer">openapi.json</a>`],
        ],
        actions: `<button class="btn sm" data-ping="health" type="button">Check bridge</button>`,
      },
    ];
    $("#integrations").innerHTML = cards.map((c) => `<section class="integ">
      <div class="integ-head"><div class="integ-logo" style="background:${c.color}">${c.logo}</div><div style="flex:1;min-width:0"><h3>${esc(c.title)}</h3><p>${esc(c.sub)}</p></div>${c.status}</div>
      <dl class="dl">${c.rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>
      <div class="integ-foot">${c.actions}${ping(c.name === "loinc" ? "terminology" : c.name === "app" ? "health" : c.name)}</div>
    </section>`).join("");
  }

  async function ping(name, button) {
    const path = { gemini: "/ai/status", umls: "/terminology/status", terminology: "/terminology/status", health: "/health", fhir: "/health" }[name];
    const started = performance.now();
    await busy(button, async () => {
      try {
        const body = await api(path);
        const ms = Math.round(performance.now() - started);
        const text = name === "gemini" ? (body.enabled ? `OK · ${body.model} · ${ms} ms` : `Disabled · ${ms} ms`)
          : name === "health" || name === "fhir" ? `OK · ${body.fhir_write_mode} · ${body.terminology_crosswalk} · ${ms} ms`
          : (body.enabled ? `OK · ${body.sources.join("+")} · ${ms} ms` : `No source · ${ms} ms`);
        state.pingResults[name] = { ok: true, text };
      } catch (error) {
        state.pingResults[name] = { ok: false, text: error.message };
      }
      renderIntegrations();
    });
  }

  /* ── drawer ───────────────────────────────────────────────────────────── */

  function openDrawer(kind, id, tab) {
    state.drawer = { kind, id, tab: tab || state.drawer?.tab || "details" };
    if (kind === "proposal" || kind === "alert") state.focus = id;
    syncHash();
    renderDrawer();
  }
  function closeDrawer() {
    if (!state.drawer) return;
    state.drawer = null;
    syncHash();
    renderDrawer();
  }

  function renderDrawer() {
    const d = $("#drawer"), scrim = $("#scrim");
    if (!state.drawer) { d.classList.remove("show"); scrim.classList.remove("show"); window.setTimeout(() => { if (!state.drawer) d.hidden = true; }, 200); return; }
    d.hidden = false;
    const { kind, id } = state.drawer;
    let html = "";
    if (kind === "proposal") { const p = byId(id); html = p ? proposalDrawer(p) : missing("Proposal"); }
    else if (kind === "alert") { const a = alertById(id); html = a ? alertDrawer(a) : missing("Incident"); }
    else if (kind === "entry") { const e = state.provenance.find((x) => String(x.sequence) === String(id)); html = e ? entryDrawer(e) : missing("Audit entry"); }
    d.className = `drawer ${kind === "proposal" ? "wide" : ""}`;
    d.innerHTML = html;
    requestAnimationFrame(() => { d.classList.add("show"); scrim.classList.add("show"); });
  }
  const missing = (what) => `<div class="drawer-head"><div class="drawer-top"><span class="spacer"></span><button class="icon-btn" data-close-drawer type="button">${icon("x", "ic")}</button></div><h2>${what} not found</h2></div><div class="drawer-body single"><div class="drawer-main"><p class="quote">It may have been created in another session. Refresh and try again.</p></div></div>`;

  function proposalDrawer(p) {
    const tab = state.drawer.tab;
    const r = p.reading;
    const unres = isUnresolved(p);
    const tabs = [
      ["details", "Details"], ["copilot", "Co-pilot", p.ai ? "" : "dim"], ["crosswalk", "Crosswalk", p.status === "pending" ? "" : "dim"],
      ["fhir", "FHIR"], ["history", "History", state.provenance.filter((e) => e.entity_id === p.id).length],
    ];
    const actions = p.status === "pending"
      ? `<button class="btn primary" data-approve="${p.id}" type="button">${icon("check")}Approve</button><button class="btn" data-reject="${p.id}" type="button">Reject</button>`
      : `${statusLz(p.status)} <span class="quote">by ${esc(p.reviewer || "-")} · ${esc(fdate(p.reviewed_at))}</span>`;
    return `<div class="drawer-head">
      <div class="drawer-top">
        <span class="key">${keyOf(p.id)}</span><span class="dim">/</span>${tagm(p.id.slice(0, 8), p.id)}
        <span class="spacer"></span>
        <button class="icon-btn" data-copy-text="${esc(location.origin + location.pathname + "#/" + state.page + "?issue=" + p.id)}" title="Copy link" type="button">${icon("link", "ic")}</button>
        <button class="icon-btn" data-close-drawer title="Close (Esc)" type="button">${icon("x", "ic")}</button>
      </div>
      <h2>${esc(r.parameter)}<span class="to">→</span>${p.coding ? `<span class="code">${esc(p.coding.code)}</span>` : '<span class="lz red">no curated match</span>'}</h2>
      <div class="drawer-actions">${actions}<span class="spacer"></span>${statusLz(p.status)}${proposerLz(p)}${flagLzs(p)}</div>
    </div>
    <div class="tabs">${tabs.map(([k, l, extra]) => `<button class="tab ${tab === k ? "is-active" : ""}" data-tab="${k}" type="button">${l}${typeof extra === "number" ? `<span class="count">${extra}</span>` : ""}</button>`).join("")}</div>
    <div class="drawer-body">
      <div class="drawer-main">${{ details: detailsTab, copilot: copilotTab, crosswalk: crosswalkTab, fhir: fhirTab, history: historyTab }[tab](p)}</div>
      <aside class="drawer-side">
        <h4>Fields</h4>
        <dl class="dl">
          <dt>Status</dt><dd>${statusLz(p.status)}</dd>
          <dt>Site</dt><dd>${esc(r.site_name)}<br><span class="dim mono">${esc(r.site_code)}</span></dd>
          <dt>Coordinates</dt><dd><a href="https://www.openstreetmap.org/?mlat=${r.latitude}&mlon=${r.longitude}#map=12/${r.latitude}/${r.longitude}" target="_blank" rel="noreferrer">${r.latitude}, ${r.longitude}</a></dd>
          <dt>Source</dt><dd>${srcGlyph(r.source_type)} ${esc(r.source_type)}<br><span class="dim mono">${esc(r.source_id)}</span></dd>
          <dt>Observed</dt><dd>${esc(fdate(r.observed_at))}</dd>
          <dt>Confidence</dt><dd>${meter(p.confidence)}</dd>
          <dt>Proposer</dt><dd>${esc(p.proposer)}</dd>
          <dt>Requires review</dt><dd>${p.requires_review ? "Always" : "No"}</dd>
          <dt>Reviewer</dt><dd>${p.reviewer ? `<span class="avatar" style="display:inline-grid;vertical-align:middle">${esc(initials(p.reviewer))}</span> ${esc(p.reviewer)}` : '<span class="dim">Unassigned</span>'}</dd>
          <dt>Reviewed</dt><dd>${esc(fdate(p.reviewed_at))}</dd>
          <dt>Created</dt><dd>${esc(fdate(p.created_at))}</dd>
          ${r.evidence_url ? `<dt>Evidence</dt><dd><a href="${esc(r.evidence_url)}" target="_blank" rel="noreferrer">open ${icon("external")}</a></dd>` : ""}
        </dl>
      </aside>
    </div>`;

    function detailsTab() {
      return `<div class="sec">
        <div class="mapping">
          <div class="side"><div class="lbl">As received</div><div class="val">${fnum(r.value)} ${esc(r.unit)}</div><div class="term">${esc(r.parameter)}</div></div>
          <div class="arrow">${icon("chevr", "ic lg")}</div>
          <div class="side out ${unres ? "unres" : ""}"><div class="lbl">OneAquaHealth FHIR</div><div class="val">${unres ? "unit unresolved" : `${fnum(p.normalized_value)} ${esc(p.normalized_unit)}`}</div><div class="term">${p.coding ? `${esc(p.coding.display)} <span class="mono dim">${esc(p.coding.code)}</span>` : "a reviewer must choose a curated code"}</div></div>
        </div>
      </div>
      ${unres && p.status === "pending" ? `<div class="sec"><div class="note">${icon("alert")}<span>Approval needs a normalized value and a UCUM unit. Use <b>Approve</b> and tick <i>Correct the proposal</i> to supply them.</span></div></div>` : ""}
      <div class="sec"><h4>Rationale</h4><p class="quote">${esc(p.rationale)}</p></div>
      ${p.candidates?.length ? `<div class="sec"><h4>Candidates considered</h4><div class="chips">${p.candidates.map((c) => `<span class="chipbtn ${p.coding?.code === c.code ? "is-on" : ""}" title="${esc(c.origin)}"><span class="mono">${esc(c.code)}</span><span class="dim">${Math.round(c.score * 100)}%</span></span>`).join("")}</div></div>` : ""}
      ${p.secondary_coding ? `<div class="sec"><h4>Second coding published</h4><p>${tagm(p.secondary_coding.code)} ${esc(p.secondary_coding.display)} <span class="dim mono">${esc(p.secondary_coding.system)}</span></p></div>` : ""}
      <div class="sec"><div class="sec-head"><h4>Raw reading</h4><button class="btn sm subtle" data-copy-text="${esc(JSON.stringify(r, null, 2))}" type="button">${icon("copy")}Copy</button></div><pre class="json">${esc(JSON.stringify(r, null, 2))}</pre></div>`;
    }
    function copilotTab() {
      if (!p.ai) return `<div class="note info">${icon("info")}<span>Curated alias matching resolved this proposal on its own. ${state.ai.enabled ? `Gemini is consulted in <b>${esc(state.ai.assist_mode)}</b> mode only when rules are weak.` : "Gemini is not configured."}</span></div>`;
      const a = p.ai;
      return `<div class="sec">${a.disagreed_with_rules ? `<div class="note">${icon("alert")}<span>The model chose a different code than curated alias matching. Confidence was capped at 80%. Read the quoted evidence before approving.</span></div>` : ""}${a.needs_expert_review ? `<div class="note" style="margin-top:8px">${icon("flag")}<span>The model flagged this reading for expert review.</span></div>` : ""}</div>
      <div class="sec"><h4>Quoted evidence</h4>${a.evidence?.length ? `<p class="quote">${a.evidence.map((x) => `<q>${esc(x)}</q>`).join(" · ")}</p>` : '<p class="quote dim">No spans quoted.</p>'}</div>
      <div class="sec"><h4>Attribution</h4><dl class="dl">
        <dt>Provider</dt><dd>${esc(a.provider)}</dd>
        <dt>Model</dt><dd>${tagm(a.model)}</dd>
        <dt>Template</dt><dd>${tagm(a.template_id)}</dd>
        <dt>Prompt hash</dt><dd>${tagm(a.prompt_hash)}</dd>
        <dt>Response hash</dt><dd>${tagm(a.response_hash)}</dd>
        <dt>Latency</dt><dd>${a.latency_ms} ms</dd>
        <dt>Model confidence</dt><dd>${a.model_confidence === null || a.model_confidence === undefined ? "-" : `${Math.round(a.model_confidence * 100)}%`}</dd>
        <dt>Grounded to</dt><dd><div class="chips">${(a.grounded_codes || []).map((c) => `<span class="chipbtn ${p.coding?.code === c ? "is-on" : ""}"><span class="mono">${esc(c)}</span></span>`).join("")}</div></dd>
      </dl></div>
      <div class="note info">${icon("info")}<span>The model may only pick from the grounded codes above and never computes the published number. The prompt hash covers template, system instruction, and rendered input, so an auditor can separate a template change from an input change.</span></div>`;
    }
    function taxonSection() {
      // Keyed on the raw source label, not the curated display: `fishes` is not
      // a taxon, `Prymnesium parvum cell count` names one. So this half works
      // even when nothing could be coded.
      if (!(state.umls.sources || []).includes("gbif")) return "";
      const found = state.taxa[p.id];
      const pick = state.taxonPicks[p.id];
      return `<div class="sec"><div class="sec-head"><h4>Organism (GBIF Backbone)</h4><button class="btn sm" data-suggest-taxon="${p.id}" type="button">${found ? "Search again" : "Identify organism"}</button></div>
        <p class="quote">Reads the source label <b>${esc(p.reading.parameter)}</b>. The OneAquaHealth code system has no taxonomy, so a species name would otherwise be lost. GBIF refuses anything that is not an organism, so a chemical label returns nothing.</p>
        ${!found ? '<p class="quote dim">Not searched yet.</p>' : found.length ? `<div class="chips">${found.map((m) => `<button class="chipbtn wrap ${pick && pick.code === m.code ? "is-on" : ""}" data-pick-taxon="${p.id}" data-system="${esc(m.system)}" data-code="${esc(m.code)}" data-display="${esc(m.display)}" title="${esc(m.display)}" type="button"><span class="lz lc">GBIF</span><span class="mono">${esc(m.code)}</span><span>${esc(m.display)}</span></button>`).join("")}</div>` : `<div class="note info">${icon("info")}<span>No organism named in this label. That is the expected answer for a chemical or physical reading.</span></div>`}
        ${pick ? `<div class="note ok" style="margin-top:8px">${icon("check")}<span><b>${esc(pick.code)}</b> ${esc(pick.display)} will be published as an <code>Observation.component</code>, leaving the indicator coding untouched. <button class="btn link sm" data-unpick-taxon="${p.id}" type="button">Remove</button></span></div>` : ""}
      </div>`;
    }
    function crosswalkTab() {
      if (p.status !== "pending") return `<div class="note info">${icon("info")}<span>${p.secondary_coding ? `Published with second coding ${esc(p.secondary_coding.code)} (${esc(p.secondary_coding.display)}).` : "This proposal was decided without a second coding."}</span></div>${p.taxon ? `<div class="note info" style="margin-top:8px">${icon("info")}<span>Published with organism ${esc(p.taxon.code)} (${esc(p.taxon.display)}).</span></div>` : ""}`;
      if (!state.umls.enabled && !(state.umls.sources || []).includes("gbif")) return `<div class="note">${icon("alert")}<span>No terminology source is configured. Approvals carry the OAH coding alone. See Integrations.</span></div>`;
      if (!p.coding) return `<div class="note">${icon("alert")}<span>No curated code, so there is nothing to crosswalk to LOINC or SNOMED. The organism lookup below reads the source label directly and still works.</span></div>${taxonSection()}`;
      const found = state.suggestions[p.id];
      const pick = state.picks[p.id];
      return `<div class="sec"><p class="quote">Searches <b>${esc(p.coding.display)}</b> in ${(state.umls.sources || []).map((s) => `<span class="lz lc">${esc(s)}</span>`).join(" ")} for a real ${(state.umls.vocabularies || []).join(" / ")} concept a downstream EHR already understands. Nothing is attached until you approve.</p></div>
      <div class="sec"><div class="sec-head"><h4>Candidates</h4><button class="btn sm" data-suggest="${p.id}" type="button">${found ? "Search again" : "Suggest LOINC / SNOMED"}</button></div>
        ${!found ? '<p class="quote dim">Not searched yet.</p>' : found.length ? `<div class="chips">${found.map((m) => `<button class="chipbtn ${pick && pick.code === m.code && pick.system === m.system ? "is-on" : ""}" data-pick="${p.id}" data-system="${esc(m.system)}" data-code="${esc(m.code)}" data-display="${esc(m.display)}" title="${esc(m.display)}" type="button"><span class="lz lc teal">${esc(m.vocabulary)}</span><span class="mono">${esc(m.code)}</span><span>${esc(m.display)}</span><span class="dim">${Math.round(m.score * 100)}%</span></button>`).join("")}</div>` : `<div class="note info">${icon("info")}<span>No publishable candidate. Environmental LOINC genuinely has no term for some OAH concepts (dissolved oxygen, water temperature, NDCI). That is a real answer, not a lookup failure.</span></div>`}
      </div>
      ${pick ? `<div class="note ok">${icon("check")}<span><b>${esc(pick.code)}</b> ${esc(pick.display)} will be published as a second <code>Observation.code.coding</code> when you approve. <button class="btn link sm" data-unpick="${p.id}" type="button">Remove</button></span></div>` : ""}
      ${taxonSection()}`;
    }
    function fhirTab() {
      const got = state.observations[p.id];
      const system = state.catalog.system || p.coding?.system || "";
      const codings = [p.coding ? { system, code: p.coding.code, display: p.coding.display } : null, p.secondary_coding || state.picks[p.id] || null].filter(Boolean);
      return `<div class="sec"><h4>Codings to publish</h4>${codings.length ? `<dl class="dl">${codings.map((c, i) => `<dt>${i === 0 ? "Primary" : "Secondary"}</dt><dd>${tagm(c.code)} ${esc(c.display)}<br><span class="dim mono">${esc(c.system)}</span></dd>`).join("")}</dl>` : '<p class="quote dim">No coding yet.</p>'}</div>
      ${(p.taxon || state.taxonPicks[p.id]) ? `<div class="sec"><h4>Organism component</h4><dl class="dl"><dt>Taxon</dt><dd>${tagm((p.taxon || state.taxonPicks[p.id]).code)} ${esc((p.taxon || state.taxonPicks[p.id]).display)}<br><span class="dim mono">${esc((p.taxon || state.taxonPicks[p.id]).system)}</span></dd></dl><p class="quote dim">Published as <code>Observation.component</code>, not as a second <code>code.coding</code>: the indicator axis drives the alert policy and must stay untouched.</p></div>` : ""}
      <div class="sec"><h4>Profiles</h4><dl class="dl"><dt>Observation</dt><dd>${tagm(state.integrations?.fhir?.observation_profile || "-")}</dd><dt>Location</dt><dd>${tagm(state.integrations?.fhir?.location_profile || "-")}</dd><dt>Target</dt><dd>${tagm(state.integrations?.fhir?.base_url || "-")} <span class="lz lc ${state.health.fhir_write_mode === "enabled" ? "green" : "amber"}">${esc(state.health.fhir_write_mode || "-")}</span></dd></dl></div>
      ${got ? `<div class="sec"><div class="sec-head"><h4>Observation as published</h4><button class="btn sm subtle" data-copy-text="${esc(JSON.stringify(got.observation, null, 2))}" type="button">${icon("copy")}Copy</button></div><pre class="json">${esc(JSON.stringify(got.observation, null, 2))}</pre></div>
      <div class="sec"><div class="sec-head"><h4>Server response</h4><button class="btn sm subtle" data-copy-text="${esc(JSON.stringify(got.fhir_response, null, 2))}" type="button">${icon("copy")}Copy</button></div><pre class="json">${esc(JSON.stringify(got.fhir_response, null, 2))}</pre></div>`
      : `<div class="note info">${icon("info")}<span>${p.status === "approved" ? "The Observation was built when this proposal was approved. Approve from this session to see the exact resource and the server's validation response here." : "The Location, Organization, and Observation are built and validated at approval time, then sent as one transaction bundle."}</span></div>`}`;
    }
    function historyTab() {
      const entries = state.provenance.filter((e) => e.entity_id === p.id).sort((a, b) => a.sequence - b.sequence);
      const obsId = observationIdFor(p);
      const related = obsId ? state.alerts.filter((a) => a.observation_id === obsId) : [];
      return `<div class="sec"><h4>Provenance</h4>${entries.length ? `<div class="hist">${entries.map((e) => `<div class="hist-item" data-open-entry="${e.sequence}" style="cursor:pointer"><div class="hist-dot"><i class="evt ${esc(e.event_type)}" style="display:block"></i></div><div><div class="b"><b>${esc(EVENT_LABEL[e.event_type] || e.event_type)}</b> <span class="dim">#${e.sequence}</span> ${esc(actorOf(e))}</div><div class="t">${esc(fdate(e.created_at))} · ${esc(e.hash.slice(0, 16))}</div></div></div>`).join("")}</div>` : `<p class="quote dim">No chain entries loaded for this id. Raise the audit limit or refresh.</p>`}</div>
      ${related.length ? `<div class="sec"><h4>Incidents raised</h4><div class="stack">${related.map((a) => `<div class="note bad" data-open-alert="${a.id}" style="cursor:pointer">${icon("alert")}<span><b>${esc(a.rule_code)}</b> ${esc(a.severity)} · ${fnum(a.value)} ${esc(a.unit)} · ${a.audiences.map((x) => AUDIENCE_LABEL[x] || x).join(", ")}</span></div>`).join("")}</div></div>` : ""}`;
    }
  }

  function alertDrawer(a) {
    const rule = ruleFor(a);
    const drafts = state.briefings.filter((b) => b.alert_id === a.id);
    const done = new Set(drafts.map((b) => b.audience));
    const entry = state.provenance.find((e) => e.event_type === "alert-created" && e.entity_id === a.id);
    const sourceProposal = state.proposals.find((p) => observationIdFor(p) === a.observation_id);
    return `<div class="drawer-head">
      <div class="drawer-top"><span class="lz bold ${a.severity === "critical" ? "red" : "amber"}">${esc(a.severity)}</span>${tagm(a.id.slice(0, 8), a.id)}<span class="spacer"></span>
        <button class="icon-btn" data-copy-text="${esc(location.origin + location.pathname + "#/alerts?incident=" + a.id)}" title="Copy link" type="button">${icon("link", "ic")}</button>
        <button class="icon-btn" data-close-drawer type="button">${icon("x", "ic")}</button></div>
      <h2>${esc(a.rule_code)} at ${esc(a.site_code)}</h2>
      <div class="drawer-actions">${state.ai.enabled ? a.audiences.map((x) => `<button class="btn ${done.has(x) ? "" : "primary"} sm" data-brief="${a.id}" data-audience="${esc(x)}" type="button">${icon("sparkle")}${done.has(x) ? "Redraft" : "Draft"} · ${esc(AUDIENCE_LABEL[x] || x)}</button>`).join("") : `<span class="quote">Set GEMINI_API_KEY to draft advisories.</span>`}</div>
    </div>
    <div class="drawer-body">
      <div class="drawer-main">
        <div class="sec"><p class="quote" style="font-size:14px">${esc(a.message)}</p></div>
        <div class="sec"><div class="mapping"><div class="side"><div class="lbl">Observed</div><div class="val">${fnum(a.value)} ${esc(a.unit)}</div><div class="term">${esc(fdate(a.observed_at))}</div></div><div class="arrow">${icon("chevr", "ic lg")}</div><div class="side out"><div class="lbl">Rule</div><div class="val">${rule ? `${{ gte: "≥", gt: ">", lte: "≤", lt: "<" }[rule.operator] || rule.operator} ${fnum(rule.value)} ${esc(rule.unit)}` : esc(a.rule_code)}</div><div class="term">${esc(a.policy_id)}</div></div></div></div>
        <div class="sec"><h4>Advisory drafts</h4>${drafts.length ? drafts.map((b) => briefHtml(b, false)).join("") : `<p class="quote dim">None yet. Each audience gets its own framing; every draft is disclaimed and stays a draft.</p>`}</div>
      </div>
      <aside class="drawer-side"><h4>Fields</h4><dl class="dl">
        <dt>Severity</dt><dd>${sevLz(a.severity)}</dd>
        <dt>Site</dt><dd>${esc(a.site_code)}</dd>
        <dt>Audiences</dt><dd><span class="aud">${a.audiences.map(audLz).join("")}</span></dd>
        <dt>Observation</dt><dd>${tagm(a.observation_id.slice(0, 14) + "…", a.observation_id)}</dd>
        ${sourceProposal ? `<dt>Proposal</dt><dd><button class="btn link sm" data-open="${sourceProposal.id}" type="button">${keyOf(sourceProposal.id)}</button></dd>` : ""}
        <dt>Policy</dt><dd>${tagm(a.policy_id)}<br><span class="dim">${esc(state.health.threshold_policy_status || "")}</span></dd>
        <dt>Raised</dt><dd>${esc(fdate(a.created_at))}</dd>
        ${entry ? `<dt>Chain entry</dt><dd><button class="btn link sm" data-open-entry="${entry.sequence}" type="button">#${entry.sequence}</button></dd>` : ""}
      </dl></aside>
    </div>`;
  }

  function entryDrawer(e) {
    const p = byId(e.entity_id);
    const a = alertById(e.entity_id);
    return `<div class="drawer-head">
      <div class="drawer-top"><span class="evt ${esc(e.event_type)}"><i></i>${esc(EVENT_LABEL[e.event_type] || e.event_type)}</span><span class="dim">#${e.sequence}</span><span class="spacer"></span><button class="icon-btn" data-close-drawer type="button">${icon("x", "ic")}</button></div>
      <h2>Chain entry ${e.sequence}</h2>
      <div class="drawer-actions">${p ? `<button class="btn sm" data-open="${p.id}" type="button">Open ${keyOf(p.id)}</button>` : ""}${a ? `<button class="btn sm" data-open-alert="${a.id}" type="button">Open incident</button>` : ""}<span class="spacer"></span><span class="quote">${esc(fdate(e.created_at))}</span></div>
    </div>
    <div class="drawer-body single"><div class="drawer-main">
      <div class="sec"><dl class="dl"><dt>Entity</dt><dd>${tagm(e.entity_id)}</dd><dt>Hash</dt><dd>${tagm(e.hash)}</dd><dt>Previous</dt><dd>${tagm(e.previous_hash)}</dd></dl></div>
      <div class="sec"><div class="sec-head"><h4>Payload</h4><button class="btn sm subtle" data-copy-text="${esc(JSON.stringify(e.payload, null, 2))}" type="button">${icon("copy")}Copy</button></div><pre class="json">${esc(JSON.stringify(e.payload, null, 2))}</pre></div>
      <div class="note info">${icon("info")}<span>hash = SHA-256(previous_hash, event_type, entity_id, created_at, canonical payload). Verify recomputes every link from the genesis entry.</span></div>
    </div></div>`;
  }

  /* ── modals ───────────────────────────────────────────────────────────── */

  function openModal(id) { $(`#${id}`).classList.add("show"); const first = $(`#${id} input:not([type=checkbox]), #${id} textarea, #${id} select`); if (first) window.setTimeout(() => first.focus(), 30); }
  function closeModals() { $$(".modal.show").forEach((m) => m.classList.remove("show")); if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); }
  const anyModalOpen = () => Boolean($(".modal.show")) || $("#cmdk").classList.contains("show");

  function openReject(ids) {
    if (!requireReviewer()) return;
    state.pending.rejectIds = ids;
    $("#reject-target").innerHTML = ids.length === 1
      ? `<span class="key">${keyOf(ids[0])}</span> ${summaryHtml(byId(ids[0]))}`
      : `<b>${ids.length} proposals</b> will be rejected with the same reason: ${ids.map((i) => keyOf(i)).join(", ")}`;
    $("#reject-reason").value = "";
    openModal("modal-reject");
  }

  function openApprove(id) {
    if (!requireReviewer()) return;
    const p = byId(id); if (!p) return;
    state.pending.approveId = id;
    const unres = isUnresolved(p);
    $("#approve-summary").innerHTML = `<div class="mapping"><div class="side"><div class="lbl">As received</div><div class="val">${fnum(p.reading.value)} ${esc(p.reading.unit)}</div><div class="term">${esc(p.reading.parameter)}</div></div><div class="arrow">${icon("chevr", "ic lg")}</div><div class="side out ${unres ? "unres" : ""}"><div class="lbl">Will publish</div><div class="val">${unres ? "needs value + unit" : `${fnum(p.normalized_value)} ${esc(p.normalized_unit)}`}</div><div class="term">${p.coding ? esc(p.coding.code) : "needs a curated code"}</div></div></div>`;
    const sel = $("#approve-coding");
    sel.innerHTML = state.catalog.codes.map((c) => `<option value="${esc(c.code)}" ${p.coding?.code === c.code ? "selected" : ""}>${esc(c.code)} · ${esc(c.display)}</option>`).join("");
    $("#unit-list").innerHTML = [...new Set(state.catalog.codes.flatMap((c) => c.accepted_units))].map((u) => `<option value="${esc(u)}">`).join("");
    $("#approve-value").value = p.normalized_value ?? p.reading.value;
    $("#approve-unit").value = p.normalized_unit ?? "";
    const forced = unres || !p.coding;
    $("#approve-override").checked = forced;
    $("#approve-override").disabled = forced;
    $("#approve-override-fields").hidden = !forced;
    const pick = state.picks[id];
    $("#approve-secondary").innerHTML = pick
      ? `<div class="note ok">${icon("check")}<span>Second coding <b>${esc(pick.code)}</b> ${esc(pick.display)} will be attached.</span></div>`
      : state.umls.enabled && p.coding ? `<p class="quote">No second coding chosen. <button class="btn link sm" data-goto-crosswalk="${id}" type="button">Suggest LOINC / SNOMED</button> before approving if you want one.</p>` : "";
    $("#approve-foot").textContent = `Signing as ${reviewer()} · ${state.health.fhir_write_mode === "enabled" ? "writes to HAPI" : "dry run: bundle built, not sent"}`;
    openModal("modal-approve");
  }

  async function submitApprove(button) {
    const id = state.pending.approveId; const p = byId(id); if (!p) return;
    const body = { reviewer: reviewer() };
    if ($("#approve-override").checked) {
      const code = $("#approve-coding").value;
      const cat = state.catalog.codes.find((c) => c.code === code);
      if (cat && (!p.coding || p.coding.code !== code)) body.coding = { system: state.catalog.system, code: cat.code, display: cat.display };
      const v = $("#approve-value").value, u = $("#approve-unit").value.trim();
      if (v === "" || !u) { toast("Supply both a normalized value and a UCUM unit.", "bad"); return; }
      if (cat && !cat.accepted_units.includes(u) && !window.confirm(`"${u}" is not an accepted unit for ${cat.code} (${cat.accepted_units.join(", ")}). Publish anyway?`)) return;
      body.normalized_value = Number(v); body.normalized_unit = u;
    }
    if (state.picks[id]) body.secondary_coding = state.picks[id];
    if (state.taxonPicks[id]) body.taxon = state.taxonPicks[id];
    await busy(button, async () => {
      const result = await api(`/proposals/${id}/approve`, { method: "POST", body: JSON.stringify(body) });
      state.observations[id] = { observation: result.observation, fhir_response: result.fhir_response };
      delete state.picks[id];
      delete state.taxonPicks[id];
      closeModals();
      const n = result.alerts.length;
      toast(`${keyOf(id)} approved and ${state.health.fhir_write_mode === "enabled" ? "published" : "built (dry run)"}.${n ? ` ${n} incident${n > 1 ? "s" : ""} raised.` : ""}`, "ok",
        n ? { label: "View", run: () => { go("alerts"); openDrawer("alert", result.alerts[0].id); } } : null);
      await refresh();
      if (state.drawer?.id === id) openDrawer("proposal", id, "fhir");
    });
  }

  async function submitReject(button) {
    const reason = $("#reject-reason").value.trim();
    if (!reason) { toast("A reason is required.", "bad"); $("#reject-reason").focus(); return; }
    const ids = state.pending.rejectIds;
    await busy(button, async () => {
      let ok = 0; const failures = [];
      for (const id of ids) {
        try { await api(`/proposals/${id}/reject`, { method: "POST", body: JSON.stringify({ reviewer: reviewer(), reason }) }); ok += 1; }
        catch (e) { failures.push(`${keyOf(id)}: ${e.message}`); }
      }
      closeModals(); state.selected.clear();
      toast(`${ok} rejected.${failures.length ? ` ${failures.length} failed.` : ""}`, failures.length ? "bad" : "ok");
      failures.forEach((f) => toast(f, "bad"));
      await refresh();
    });
  }

  async function approveMany(ids, button) {
    if (!requireReviewer()) return;
    if (!ids.length) { toast("Nothing to approve."); return; }
    if (!window.confirm(`Approve ${ids.length} proposal${ids.length > 1 ? "s" : ""} as ${reviewer()}? Each is validated, published, and hash-chained individually.`)) return;
    await busy(button, async () => {
      const result = await api("/proposals/approve-batch", { method: "POST", body: JSON.stringify({ reviewer: reviewer(), proposal_ids: ids }) });
      result.approved.forEach((r) => { state.observations[r.proposal.id] = { observation: r.observation, fhir_response: r.fhir_response }; });
      state.selected.clear();
      const alerts = result.approved.reduce((n, r) => n + r.alerts.length, 0);
      toast(`Approved ${result.approved.length}.${result.failures.length ? ` ${result.failures.length} need a reviewer correction.` : ""}${alerts ? ` ${alerts} incident${alerts > 1 ? "s" : ""} raised.` : ""}`, result.failures.length ? "bad" : "ok");
      result.failures.slice(0, 3).forEach((f) => toast(`${keyOf(f.proposal_id)}: ${f.detail}`, "bad"));
      await refresh();
    });
  }

  /* create dialog */
  let createTab = "reading";
  function showCreateTab(tab) {
    createTab = tab;
    $$("#create-tabs .tab").forEach((t) => t.classList.toggle("is-active", t.dataset.ct === tab));
    $$("#modal-create [data-ct]:not(.tab)").forEach((f) => { f.hidden = f.dataset.ct !== tab; });
    $("#create-submit").textContent = { reading: "Create proposal", bulletin: "Extract readings", replay: "Load 5 readings" }[tab];
    $("#create-submit").disabled = tab === "bulletin" && !state.ai.enabled;
    $("#create-foot-hint").textContent = tab === "bulletin" && !state.ai.enabled ? "Bulletin intake needs GEMINI_API_KEY." : tab === "reading" ? "Lands in the queue as pending. Nothing is published." : "";
    if (tab === "replay") $("#replay-preview").innerHTML = `<p>Five synthetic readings across two sites, 24–29 July 2022: conductivity, NDCI, and dissolved oxygen. Three cross the demo policy once approved.</p><p class="quote dim">Loading the replay again creates a second set of proposals; the dataset is not de-duplicated.</p>`;
  }
  function openCreate(tab = "reading") {
    $("#ct-ai-lz").className = `lz ${state.ai.enabled ? "purple" : ""}`;
    const dt = $("#form-reading [name=observed_at]");
    if (!dt.value) dt.value = new Date().toISOString().slice(0, 16);
    $("#bulletin-result").innerHTML = "";
    showCreateTab(tab);
    openModal("modal-create");
  }
  async function submitCreate(button) {
    if (createTab === "reading") {
      const form = $("#form-reading");
      if (!form.reportValidity()) return;
      const d = new FormData(form);
      const observed = d.get("observed_at") ? new Date(d.get("observed_at") + "Z").toISOString() : new Date().toISOString();
      const payload = {
        source_id: d.get("source_id"), source_type: d.get("source_type"), parameter: d.get("parameter"),
        value: Number(d.get("value")), unit: d.get("unit"), observed_at: observed,
        site_code: d.get("site_code"), site_name: d.get("site_name"),
        latitude: Number(d.get("latitude")), longitude: Number(d.get("longitude")),
        ...(d.get("evidence_url") ? { evidence_url: d.get("evidence_url") } : {}),
      };
      await busy(button, async () => {
        const p = await api("/proposals", { method: "POST", body: JSON.stringify(payload) });
        closeModals();
        await refresh();
        toast(`${keyOf(p.id)} created${p.ai ? " with Gemini assistance" : ""}. Pending review.`, "ok", { label: "Open", run: () => openDrawer("proposal", p.id) });
      });
    } else if (createTab === "bulletin") {
      const form = $("#form-bulletin");
      if (!form.reportValidity()) return;
      const d = new FormData(form);
      await busy(button, async () => {
        const r = await api("/intake", { method: "POST", body: JSON.stringify({
          text: d.get("text"), source_id: d.get("source_id") || "unstructured-intake", source_type: d.get("source_type"),
          default_site_code: d.get("default_site_code") || "unknown-site", default_site_name: d.get("default_site_name") || "Unknown site",
          default_latitude: Number(d.get("default_latitude")), default_longitude: Number(d.get("default_longitude")),
        }) });
        $("#bulletin-result").innerHTML = `<div class="note ${r.extracted_count ? "ok" : ""}">${icon(r.extracted_count ? "check" : "alert")}<span><b>${r.extracted_count} reading${r.extracted_count === 1 ? "" : "s"} extracted</b>${r.ai ? ` · ${esc(r.ai.model)} · ${r.ai.latency_ms} ms` : ""}</span></div>${r.warnings.length ? `<div class="stack" style="margin-top:8px">${r.warnings.map((w) => `<div class="note">${icon("flag")}<span>${esc(w)}</span></div>`).join("")}</div>` : ""}`;
        await refresh();
        toast(`${r.extracted_count} reading${r.extracted_count === 1 ? "" : "s"} queued from the bulletin.`);
      });
    } else {
      await busy(button, async () => {
        const list = await api("/replay", { method: "POST" });
        closeModals();
        await refresh();
        toast(`Loaded ${list.length} readings from the synthetic Oder timeline.`, "ok", { label: "Board", run: () => go("board") });
      });
    }
  }

  /* ── command palette ──────────────────────────────────────────────────── */

  let cmdFocus = 0;
  function cmdItems(q) {
    const nav = PAGES.map((p) => ({ group: "Go to", label: PAGE_TITLES[p], icon: "chevr", run: () => go(p), hint: "" }));
    const actions = [
      { group: "Actions", label: "Create reading", icon: "plus", hint: "C", run: () => openCreate("reading") },
      { group: "Actions", label: "Extract from bulletin", icon: "sparkle", run: () => openCreate("bulletin") },
      { group: "Actions", label: "Load Oder replay", icon: "play", run: () => openCreate("replay") },
      { group: "Actions", label: "Approve all pending", icon: "check", run: () => approveMany(state.proposals.filter((p) => p.status === "pending").map((p) => p.id), null) },
      { group: "Actions", label: "Verify hash chain", icon: "shield", run: () => verifyChain(null) },
      { group: "Actions", label: "Generate situation report", icon: "chart", run: () => { go("reports"); situationReport(null); } },
      { group: "Actions", label: "Refresh data", icon: "refresh", run: () => refresh(true) },
      { group: "Actions", label: "Toggle theme", icon: "moon", hint: "T", run: toggleTheme },
      { group: "Actions", label: "Set reviewer identity", icon: "pin", run: () => openModal("modal-reviewer") },
      { group: "Actions", label: "Keyboard shortcuts", icon: "keyboard", hint: "?", run: () => openModal("modal-help") },
      { group: "Actions", label: "API reference", icon: "external", run: () => window.open("/docs", "_blank") },
    ];
    const ql = q.trim().toLowerCase();
    const items = [...nav, ...actions].filter((i) => !ql || i.label.toLowerCase().includes(ql));
    if (ql) {
      state.proposals.filter((p) => matchText(p, ql)).slice(0, 8).forEach((p) => items.push({ group: "Proposals", label: `${keyOf(p.id)} · ${proposalTitle(p)} · ${p.reading.site_name}`, icon: "board", hint: p.status, run: () => openDrawer("proposal", p.id) }));
      state.alerts.filter((a) => [a.rule_code, a.site_code, a.severity, a.message].join(" ").toLowerCase().includes(ql)).slice(0, 5).forEach((a) => items.push({ group: "Incidents", label: `${a.rule_code} · ${a.site_code} · ${fnum(a.value)} ${a.unit}`, icon: "alert", hint: a.severity, run: () => { go("alerts"); openDrawer("alert", a.id); } }));
      state.provenance.filter((e) => e.hash.startsWith(ql) || e.entity_id.startsWith(ql) || String(e.sequence) === ql).slice(0, 5).forEach((e) => items.push({ group: "Audit", label: `#${e.sequence} ${EVENT_LABEL[e.event_type] || e.event_type} · ${e.hash.slice(0, 16)}`, icon: "shield", run: () => { go("audit"); openDrawer("entry", e.sequence); } }));
    }
    return items;
  }
  function renderCmd() {
    const items = cmdItems($("#cmdk-input").value);
    cmdFocus = Math.min(cmdFocus, Math.max(0, items.length - 1));
    let last = null;
    $("#cmdk-list").innerHTML = items.length ? items.map((i, idx) => { const g = i.group !== last ? `<div class="cmdk-group">${esc(i.group)}</div>` : ""; last = i.group; return `${g}<div class="cmdk-item ${idx === cmdFocus ? "is-focus" : ""}" data-idx="${idx}">${icon(i.icon, "ic")}<span class="lbl">${esc(i.label)}</span>${i.hint ? `<span class="hint">${esc(i.hint)}</span>` : ""}</div>`; }).join("")
      : '<div class="cmdk-empty">No matches.</div>';
    $("#cmdk-list")._items = items;
    const f = $(".cmdk-item.is-focus"); if (f) f.scrollIntoView({ block: "nearest" });
  }
  function openCmd(prefill = "") { $("#cmdk").classList.add("show"); const i = $("#cmdk-input"); i.value = prefill; cmdFocus = 0; renderCmd(); i.focus(); }
  function closeCmd() { $("#cmdk").classList.remove("show"); $("#cmdk-input").blur(); if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); }
  function runCmd(idx) { const items = $("#cmdk-list")._items || []; const it = items[idx]; if (!it) return; closeCmd(); it.run(); }

  /* ── router & shell ───────────────────────────────────────────────────── */

  function parseHash() {
    const h = location.hash.replace(/^#\/?/, "");
    const [path, query = ""] = h.split("?");
    const page = PAGES.includes(path) ? path : "board";
    const params = new URLSearchParams(query);
    return { page, params };
  }
  let suppressHash = false;
  function syncHash() {
    const params = new URLSearchParams();
    if (state.drawer?.kind === "proposal") params.set("issue", state.drawer.id);
    if (state.drawer?.kind === "alert") params.set("incident", state.drawer.id);
    if (state.drawer?.kind === "entry") params.set("entry", state.drawer.id);
    const q = params.toString();
    const next = `#/${state.page}${q ? "?" + q : ""}`;
    if (location.hash !== next) { suppressHash = true; history.replaceState(null, "", next); suppressHash = false; }
  }
  function go(page) { state.page = page; syncHash(); renderShell(); }
  function applyRoute() {
    const { page, params } = parseHash();
    state.page = page;
    if (params.get("issue")) state.drawer = { kind: "proposal", id: params.get("issue"), tab: state.drawer?.tab || "details" };
    else if (params.get("incident")) state.drawer = { kind: "alert", id: params.get("incident") };
    else if (params.get("entry")) state.drawer = { kind: "entry", id: params.get("entry") };
    else state.drawer = null;
    renderShell(); renderDrawer();
  }

  function renderShell() {
    $$(".page").forEach((p) => p.classList.toggle("is-active", p.dataset.page === state.page));
    $$("[data-nav]").forEach((n) => n.classList.toggle("is-active", n.dataset.nav === state.page));
    document.title = `${PAGE_TITLES[state.page]} - AquaFHIR Bridge`;
    render();
  }

  function render() {
    assignKeys();
    const pending = state.proposals.filter((p) => p.status === "pending").length;
    $("#n-board").textContent = pending; $("#n-list").textContent = state.proposals.length;
    $("#n-alerts").textContent = state.alerts.length; $("#n-alerts").classList.toggle("hot", state.alerts.some((a) => a.severity === "critical"));
    $("#n-briefings").textContent = state.briefings.length; $("#n-audit").textContent = state.provenance.length;
    $("#notify-badge").hidden = !state.alerts.length;
    const pill = (id, cls, text, title) => { const n = $(id); n.className = `pill ${cls}`; n.lastChild.textContent = text; n.title = title; };
    pill("#pill-fhir", state.health.fhir_write_mode === "enabled" ? "on" : "warn", `FHIR ${state.health.fhir_write_mode || "…"}`, `FHIR write mode: ${state.health.fhir_write_mode || "unknown"}`);
    pill("#pill-ai", state.ai.enabled ? "on" : "off", state.ai.enabled ? `AI ${state.ai.model}` : "AI off", state.ai.detail || "");
    pill("#pill-umls", state.umls.enabled ? ((state.umls.sources || []).includes("umls") ? "on" : "warn") : "off", state.umls.enabled ? `Crosswalk ${(state.umls.sources || []).join("+")}` : "Crosswalk off", state.umls.detail || "");
    $("#foot-policy").textContent = state.health.threshold_policy || "policy";
    $("#foot-policy-status").textContent = state.health.threshold_policy_status || "";
    $("#foot-chain").textContent = state.chain ? (state.chain.valid ? `valid · ${state.chain.entries_checked}` : "BROKEN") : "-";
    $("#foot-chain").style.color = state.chain && !state.chain.valid ? "var(--red)" : "";
    $("#foot-version").textContent = state.integrations?.app?.version ? `v${state.integrations.app.version}` : "-";
    $("#foot-updated").textContent = state.lastRefresh ? ago(state.lastRefresh) : "-";
    $("#avatar").textContent = initials(reviewer());
    $("#avatar").title = reviewer() || "Set reviewer identity";
    $("#btn-approve-all").disabled = !pending;
    $("#btn-draft-all").disabled = !state.ai.enabled || !state.alerts.length;
    const siteOpts = `<option value="">All sites</option>${sites().map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("")}`;
    ["#board-site", "#list-site"].forEach((id) => { const n = $(id); const v = n.value; n.innerHTML = siteOpts; n.value = v; });
    ({ flow: renderFlow, board: renderBoard, list: renderList, alerts: renderAlerts, advisories: renderBriefs, reports: renderReports, audit: renderAudit, policy: renderPolicy, integrations: renderIntegrations })[state.page]();
    if (state.drawer) renderDrawer();
  }

  async function refresh(announce = false) {
    const limit = state.filters.audit.limit;
    try {
      const [health, ai, umls, proposals, alerts, briefings, provenance, chain, integrations, catalog] = await Promise.all([
        api("/health"), api("/ai/status"), api("/terminology/status"), api("/proposals?limit=500"), api("/alerts?limit=500"),
        api("/briefings?limit=500"), api(`/provenance?limit=${limit}`), api("/provenance/verify"),
        api("/integrations").catch(() => state.integrations), api("/coding/catalog").catch(() => state.catalog),
      ]);
      Object.assign(state, { health, ai, umls, proposals, alerts, briefings, provenance, chain, integrations, catalog, lastRefresh: new Date().toISOString() });
      $("#updated-board").classList.remove("stale");
      render();
      if (announce) toast("Refreshed.");
    } catch (error) {
      $("#updated-board").classList.add("stale");
      toast(`Refresh failed: ${error.message}`, "bad");
    }
  }

  async function verifyChain(button) {
    await busy(button, async () => {
      state.chain = await api("/provenance/verify");
      render();
      toast(state.chain.valid ? `Chain verified across ${state.chain.entries_checked} entries.` : `Chain broken at #${state.chain.first_invalid_sequence}.`, state.chain.valid ? "ok" : "bad");
    });
  }
  async function situationReport(button) {
    await busy(button, async () => {
      state.situation = await api("/ai/situation-report", { method: "POST" });
      await refresh();
      toast("Situation report generated from stored records.");
    });
  }
  async function draftBriefing(alertId, audience, button) {
    await busy(button, async () => {
      await api(`/alerts/${alertId}/briefings?audience=${encodeURIComponent(audience)}`, { method: "POST" });
      await refresh();
      toast(`Advisory drafted for ${AUDIENCE_LABEL[audience] || audience}.`);
    });
  }

  function toggleTheme() {
    const dark = document.documentElement.dataset.theme !== "dark";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try { window.localStorage.setItem("aquafhir.theme", dark ? "dark" : "light"); } catch (_) { /* ignore */ }
    $("#btn-theme use").setAttribute("href", dark ? "#i-sun" : "#i-moon");
  }

  /* ── events ───────────────────────────────────────────────────────────── */

  // Global delegated clicks: open drawers, copy, tabs, actions inside rendered HTML.
  document.addEventListener("click", async (event) => {
    const t = event.target;
    const el = (sel) => t.closest(sel);
    let n;
    if ((n = el("[data-map-site]"))) {
      event.preventDefault();
      const row = state.proposals.find((p) => p.reading.site_code === n.dataset.mapSite);
      if (row) { state.filters.list.site = row.reading.site_name; state.filters.list.status = "all"; go("list"); }
      return;
    }
    if ((n = el("[data-copy-text]"))) { event.preventDefault(); copy(n.dataset.copyText); return; }
    if ((n = el("[data-copy]"))) { event.preventDefault(); event.stopPropagation(); copy(n.dataset.copy); return; }
    if ((n = el("[data-close-drawer]"))) { closeDrawer(); return; }
    if ((n = el("[data-close]"))) { closeModals(); return; }
    if ((n = el("[data-tab]")) && state.drawer) { state.drawer.tab = n.dataset.tab; renderDrawer(); return; }
    if ((n = el("[data-approve]"))) { openApprove(n.dataset.approve); return; }
    if ((n = el("[data-reject]"))) { openReject([n.dataset.reject]); return; }
    if ((n = el("[data-suggest]"))) {
      const id = n.dataset.suggest;
      await busy(n, async () => { state.suggestions[id] = await api(`/proposals/${id}/terminology-suggestions`); renderDrawer(); toast(state.suggestions[id].length ? `${state.suggestions[id].length} candidate${state.suggestions[id].length > 1 ? "s" : ""} found.` : "No publishable candidate for this concept."); });
      return;
    }
    if ((n = el("[data-suggest-taxon]"))) {
      const id = n.dataset.suggestTaxon;
      await busy(n, async () => {
        state.taxa[id] = await api(`/proposals/${id}/taxon-suggestions`);
        renderDrawer();
        toast(state.taxa[id].length ? `${state.taxa[id].length} organism match${state.taxa[id].length > 1 ? "es" : ""} found.` : "No organism named in this label.");
      });
      return;
    }
    if ((n = el("[data-pick-taxon]"))) {
      const { pickTaxon, system, code, display } = n.dataset;
      const same = state.taxonPicks[pickTaxon] && state.taxonPicks[pickTaxon].code === code;
      if (same) delete state.taxonPicks[pickTaxon]; else state.taxonPicks[pickTaxon] = { system, code, display };
      renderDrawer(); toast(same ? "Organism removed." : `${display} will be attached on approval.`); return;
    }
    if ((n = el("[data-unpick-taxon]"))) { delete state.taxonPicks[n.dataset.unpickTaxon]; renderDrawer(); return; }
    if ((n = el("[data-pick]"))) {
      const { pick, system, code, display } = n.dataset;
      const same = state.picks[pick] && state.picks[pick].code === code && state.picks[pick].system === system;
      if (same) delete state.picks[pick]; else state.picks[pick] = { system, code, display };
      renderDrawer(); toast(same ? "Second coding removed." : `${code} will be attached on approval.`); return;
    }
    if ((n = el("[data-unpick]"))) { delete state.picks[n.dataset.unpick]; renderDrawer(); return; }
    if ((n = el("[data-goto-crosswalk]"))) { closeModals(); openDrawer("proposal", n.dataset.gotoCrosswalk, "crosswalk"); return; }
    if ((n = el("[data-brief]"))) { draftBriefing(n.dataset.brief, n.dataset.audience, n); return; }
    if ((n = el("[data-ping]"))) { ping(n.dataset.ping, n); return; }
    if ((n = el("[data-approve-shown]"))) { approveMany(applyProposalFilters(state.proposals, state.filters.board).filter((p) => p.status === "pending").map((p) => p.id), n); return; }
    if ((n = el("[data-select]"))) { event.stopPropagation(); if (n.checked) state.selected.add(n.dataset.select); else state.selected.delete(n.dataset.select); renderList(); return; }
    if ((n = el("[data-open-entry]"))) { event.stopPropagation(); openDrawer("entry", n.dataset.openEntry); return; }
    if ((n = el("[data-open-alert]"))) { event.stopPropagation(); if (state.page !== "alerts" && !state.drawer) go("alerts"); openDrawer("alert", n.dataset.openAlert); return; }
    if ((n = el("[data-open]"))) { if (t.closest("input")) return; openDrawer("proposal", n.dataset.open); return; }
    if ((n = el("[data-ev]"))) { const s = state.filters.audit.events; s.has(n.dataset.ev) ? s.delete(n.dataset.ev) : s.add(n.dataset.ev); renderAudit(); return; }
    if ((n = el(".cmdk-item"))) { runCmd(Number(n.dataset.idx)); return; }
    if ((n = el("[data-nav]"))) { event.preventDefault(); go(n.dataset.nav); return; }
  });

  $("#scrim").addEventListener("click", closeDrawer);
  $$(".modal").forEach((m) => m.addEventListener("click", (e) => { if (e.target === m) closeModals(); }));
  $("#cmdk").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeCmd(); });

  // top nav
  $("#btn-create").addEventListener("click", () => openCreate("reading"));
  $("#btn-theme").addEventListener("click", toggleTheme);
  $("#btn-help").addEventListener("click", () => openModal("modal-help"));
  $("#btn-notify").addEventListener("click", () => go("alerts"));
  $("#btn-reviewer").addEventListener("click", () => { $("#reviewer-input").value = reviewer(); openModal("modal-reviewer"); });
  $("#reviewer-save").addEventListener("click", () => { const v = $("#reviewer-input").value.trim(); try { window.localStorage.setItem("aquafhir.reviewer", v); } catch (_) { /* ignore */ } closeModals(); render(); toast(v ? `Signing as ${v}.` : "Reviewer identity cleared."); });
  $("#reviewer-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#reviewer-save").click(); });
  $$(".sys-pills .pill").forEach((p) => p.addEventListener("click", () => go("integrations")));
  $("#global-search").addEventListener("focus", (e) => { e.target.blur(); openCmd(); });
  $("#sidebar-toggle").addEventListener("click", () => { const c = $("#shell").classList.toggle("sidebar-collapsed"); $("#sidebar-toggle use").setAttribute("href", c ? "#i-chevr" : "#i-chevl"); try { window.localStorage.setItem("aquafhir.sidebar", c ? "collapsed" : ""); } catch (_) { /* ignore */ } });

  // board
  $("#btn-replay").addEventListener("click", () => openCreate("replay"));
  $("#btn-approve-all").addEventListener("click", (e) => approveMany(state.proposals.filter((p) => p.status === "pending").map((p) => p.id), e.currentTarget));
  $("#board-search").addEventListener("input", (e) => { state.filters.board.q = e.target.value; renderBoard(); });
  $("#board-site").addEventListener("change", (e) => { state.filters.board.site = e.target.value; renderBoard(); });
  $("#board-source").addEventListener("change", (e) => { state.filters.board.source = e.target.value; renderBoard(); });
  $("#board-quick").addEventListener("click", (e) => { const b = e.target.closest(".chipf"); if (!b) return; const s = state.filters.board.quick; s.has(b.dataset.q) ? s.delete(b.dataset.q) : s.add(b.dataset.q); renderBoard(); });

  // drag & drop on the board
  $("#board").addEventListener("dragstart", (e) => { const c = e.target.closest("[data-drag]"); if (!c || c.getAttribute("draggable") !== "true") { e.preventDefault(); return; } state.pending.dragId = c.dataset.drag; c.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", c.dataset.drag); });
  $("#board").addEventListener("dragend", () => { state.pending.dragId = null; $$(".card.dragging").forEach((c) => c.classList.remove("dragging")); $$(".col.is-over").forEach((c) => c.classList.remove("is-over")); });
  $("#board").addEventListener("dragover", (e) => { const col = e.target.closest(".col"); if (!col || !state.pending.dragId || col.dataset.col === "pending") return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; col.classList.add("is-over"); });
  $("#board").addEventListener("dragleave", (e) => { const col = e.target.closest(".col"); if (col && !col.contains(e.relatedTarget)) col.classList.remove("is-over"); });
  $("#board").addEventListener("drop", (e) => { const col = e.target.closest(".col"); if (!col) return; e.preventDefault(); const id = state.pending.dragId || e.dataTransfer.getData("text/plain"); col.classList.remove("is-over"); if (!id) return; if (col.dataset.col === "approved") openApprove(id); else if (col.dataset.col === "rejected") openReject([id]); });

  // list
  $("#list-search").addEventListener("input", (e) => { state.filters.list.q = e.target.value; renderList(); });
  $("#list-site").addEventListener("change", (e) => { state.filters.list.site = e.target.value; renderList(); });
  $("#list-proposer").addEventListener("change", (e) => { state.filters.list.proposer = e.target.value; renderList(); });
  $("#list-status").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; state.filters.list.status = b.dataset.s; state.selected.clear(); renderList(); });
  $("#list-quick").addEventListener("click", (e) => { const b = e.target.closest(".chipf"); if (!b) return; const s = state.filters.list.quick; s.has(b.dataset.q) ? s.delete(b.dataset.q) : s.add(b.dataset.q); renderList(); });
  $("#list-table thead").addEventListener("click", (e) => { const th = e.target.closest("th.sortable"); if (!th) return; const f = state.filters.list; if (f.sort === th.dataset.sort) f.dir = f.dir === "asc" ? "desc" : "asc"; else { f.sort = th.dataset.sort; f.dir = th.dataset.sort === "confidence" || th.dataset.sort === "observed" ? "desc" : "asc"; } renderList(); });
  $("#list-check-all").addEventListener("change", (e) => { const f = state.filters.list; let shown = applyProposalFilters(state.proposals, f); if (f.status !== "all") shown = shown.filter((p) => p.status === f.status); shown.filter((p) => p.status === "pending").forEach((p) => e.target.checked ? state.selected.add(p.id) : state.selected.delete(p.id)); renderList(); });
  $("#bulk-approve").addEventListener("click", (e) => approveMany([...state.selected], e.currentTarget));
  $("#bulk-reject").addEventListener("click", () => openReject([...state.selected]));
  $("#bulk-clear").addEventListener("click", () => { state.selected.clear(); renderList(); });
  $("#btn-refresh-list").addEventListener("click", (e) => busy(e.currentTarget, () => refresh(true)));
  $("#btn-export").addEventListener("click", () => { const f = state.filters.list; let shown = applyProposalFilters(state.proposals, f); if (f.status !== "all") shown = shown.filter((p) => p.status === f.status); copy(JSON.stringify(shown, null, 2), `Copied ${shown.length} proposals as JSON.`); });

  // incidents & advisories
  $("#alert-search").addEventListener("input", (e) => { state.filters.alerts.q = e.target.value; renderAlerts(); });
  $("#alert-audience").addEventListener("change", (e) => { state.filters.alerts.audience = e.target.value; renderAlerts(); });
  $("#alert-quick").addEventListener("click", (e) => { const b = e.target.closest(".chipf"); if (!b) return; const s = state.filters.alerts.quick; s.has(b.dataset.q) ? s.delete(b.dataset.q) : s.add(b.dataset.q); renderAlerts(); });
  $("#btn-draft-all").addEventListener("click", async (e) => {
    const todo = [];
    state.alerts.forEach((a) => { const done = new Set(state.briefings.filter((b) => b.alert_id === a.id).map((b) => b.audience)); a.audiences.filter((x) => !done.has(x)).forEach((x) => todo.push([a.id, x])); });
    if (!todo.length) { toast("Every audience already has a draft."); return; }
    if (!window.confirm(`Draft ${todo.length} advisories with Gemini? Each is a separate model call.`)) return;
    await busy(e.currentTarget, async () => {
      let ok = 0;
      for (const [id, aud] of todo) { try { await api(`/alerts/${id}/briefings?audience=${encodeURIComponent(aud)}`, { method: "POST" }); ok += 1; } catch (err) { toast(`${aud}: ${err.message}`, "bad"); } }
      await refresh(); toast(`${ok} of ${todo.length} advisories drafted.`);
    });
  });
  $("#brief-search").addEventListener("input", (e) => { state.filters.briefs.q = e.target.value; renderBriefs(); });
  $("#brief-audience").addEventListener("change", (e) => { state.filters.briefs.audience = e.target.value; renderBriefs(); });

  // data flow: light the wires that touch the hovered or focused node
  const flowCanvas = $("#flow-canvas");
  if (flowCanvas) {
    const lit = (e) => { const n = e.target.closest("[id^='fn-'], [id^='fa-']"); litWires(n ? n.id : null); };
    flowCanvas.addEventListener("mouseover", lit);
    flowCanvas.addEventListener("mouseout", (e) => { if (!flowCanvas.contains(e.relatedTarget)) litWires(null); });
    flowCanvas.addEventListener("focusin", lit);
    flowCanvas.addEventListener("focusout", () => litWires(null));
  }
  window.addEventListener("resize", () => {
    if (state.page === "flow") drawWires();
    if (state.page === "reports" && map.instance) map.instance.invalidateSize();
  });

  // map
  $("#map-fit").addEventListener("click", fitMapToSites);
  $("#map-search").addEventListener("input", (e) => {
    const q = e.target.value;
    window.clearTimeout(map.searchTimer);
    map.searchTimer = window.setTimeout(() => geocode(q), 700);
  });
  $("#map-search").addEventListener("keydown", (e) => { if (e.key === "Escape") { $("#map-suggest").hidden = true; e.target.blur(); } });
  $("#map-suggest").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-lat]");
    if (!b || !map.instance) return;
    map.instance.setView([Number(b.dataset.lat), Number(b.dataset.lon)], 11);
    $("#map-suggest").hidden = true;
    $("#map-search").value = "";
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".map-search")) { const s = $("#map-suggest"); if (s) s.hidden = true; }
  });

  // reports, audit, integrations
  $("#btn-situation").addEventListener("click", (e) => situationReport(e.currentTarget));
  $("#btn-verify").addEventListener("click", (e) => verifyChain(e.currentTarget));
  $("#btn-audit-copy").addEventListener("click", () => copy(JSON.stringify(state.provenance, null, 2), `Copied ${state.provenance.length} chain entries.`));
  $("#audit-search").addEventListener("input", (e) => { state.filters.audit.q = e.target.value; renderAudit(); });
  $("#audit-limit").addEventListener("change", (e) => { state.filters.audit.limit = Number(e.target.value); refresh(); });
  $("#btn-ping-all").addEventListener("click", async (e) => { await busy(e.currentTarget, async () => { await Promise.all(["gemini", "umls", "terminology", "health"].map((n) => ping(n, null))); toast("All integrations checked."); }); });

  // create / approve / reject
  $("#create-tabs").addEventListener("click", (e) => { const t = e.target.closest(".tab"); if (t) showCreateTab(t.dataset.ct); });
  $("#create-submit").addEventListener("click", (e) => submitCreate(e.currentTarget));
  $("#form-reading").addEventListener("submit", (e) => { e.preventDefault(); submitCreate($("#create-submit")); });
  $("#form-bulletin").addEventListener("submit", (e) => { e.preventDefault(); submitCreate($("#create-submit")); });
  $("#approve-override").addEventListener("change", (e) => { $("#approve-override-fields").hidden = !e.target.checked; });
  $("#approve-coding").addEventListener("change", (e) => { const c = state.catalog.codes.find((x) => x.code === e.target.value); if (c && c.accepted_units.length && !c.accepted_units.includes($("#approve-unit").value)) $("#approve-unit").value = c.accepted_units[0]; });
  $("#approve-submit").addEventListener("click", (e) => submitApprove(e.currentTarget));
  $("#reject-submit").addEventListener("click", (e) => submitReject(e.currentTarget));
  $("#reject-reason").addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") $("#reject-submit").click(); });

  // command palette
  $("#cmdk-input").addEventListener("input", () => { cmdFocus = 0; renderCmd(); });
  $("#cmdk-input").addEventListener("keydown", (e) => {
    const n = ($("#cmdk-list")._items || []).length;
    if (e.key === "ArrowDown") { e.preventDefault(); cmdFocus = (cmdFocus + 1) % Math.max(n, 1); renderCmd(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); cmdFocus = (cmdFocus - 1 + Math.max(n, 1)) % Math.max(n, 1); renderCmd(); }
    else if (e.key === "Enter") { e.preventDefault(); runCmd(cmdFocus); }
    else if (e.key === "Escape") { closeCmd(); }
  });

  // keyboard shortcuts
  let chord = null;
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select" || e.target.isContentEditable;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#cmdk").classList.contains("show") ? closeCmd() : openCmd(); return; }
    if (e.key === "Escape") { if ($("#cmdk").classList.contains("show")) closeCmd(); else if (anyModalOpen()) closeModals(); else if (state.drawer) closeDrawer(); return; }
    if (typing || anyModalOpen() || e.metaKey || e.ctrlKey || e.altKey) return;
    if (chord === "g") {
      chord = null;
      const dest = { f: "flow", b: "board", q: "list", l: "list", i: "alerts", a: "audit", r: "reports", p: "policy", n: "integrations", v: "advisories" };
      if (dest[e.key.toLowerCase()]) { e.preventDefault(); go(dest[e.key.toLowerCase()]); }
      return;
    }
    switch (e.key) {
      case "g": chord = "g"; window.setTimeout(() => { chord = null; }, 900); break;
      case "c": e.preventDefault(); openCreate("reading"); break;
      case "/": e.preventDefault(); openCmd(); break;
      case "?": e.preventDefault(); openModal("modal-help"); break;
      case "t": toggleTheme(); break;
      case "j": case "k": { e.preventDefault(); moveFocus(e.key === "j" ? 1 : -1); break; }
      case "Enter": if (state.focus && !state.drawer) { if (byId(state.focus)) openDrawer("proposal", state.focus); else if (alertById(state.focus)) openDrawer("alert", state.focus); } break;
      case "a": if (state.drawer?.kind === "proposal" && byId(state.drawer.id)?.status === "pending") openApprove(state.drawer.id); break;
      case "r": if (state.drawer?.kind === "proposal" && byId(state.drawer.id)?.status === "pending") openReject([state.drawer.id]); break;
      default: break;
    }
  });
  function moveFocus(delta) {
    let ids;
    if (state.page === "alerts") ids = filteredAlerts().map((a) => a.id);
    else if (state.page === "list") { const f = state.filters.list; let s = applyProposalFilters(state.proposals, f); if (f.status !== "all") s = s.filter((p) => p.status === f.status); ids = sortProposals(s, f.sort, f.dir).map((p) => p.id); }
    else ids = ["pending", "approved", "rejected"].flatMap((s) => applyProposalFilters(state.proposals, state.filters.board).filter((p) => p.status === s).map((p) => p.id));
    if (!ids.length) return;
    const i = ids.indexOf(state.focus);
    state.focus = ids[(i < 0 ? (delta > 0 ? 0 : ids.length - 1) : (i + delta + ids.length) % ids.length)];
    if (state.drawer && state.drawer.kind !== "entry") openDrawer(state.drawer.kind, state.focus); else render();
    const node = $(`[data-open="${state.focus}"], [data-open-alert="${state.focus}"]`); if (node) node.scrollIntoView({ block: "nearest" });
  }

  window.addEventListener("hashchange", () => { if (!suppressHash) applyRoute(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  window.setInterval(() => { if (!document.hidden && !anyModalOpen()) refresh(); else $("#foot-updated").textContent = state.lastRefresh ? ago(state.lastRefresh) : "-"; }, POLL_MS);
  window.setInterval(() => { $("#foot-updated").textContent = state.lastRefresh ? ago(state.lastRefresh) : "-"; }, 30000);

  /* ── boot ─────────────────────────────────────────────────────────────── */

  (function boot() {
    let theme = null, sidebar = "";
    try { theme = window.localStorage.getItem("aquafhir.theme"); sidebar = window.localStorage.getItem("aquafhir.sidebar") || ""; } catch (_) { /* ignore */ }
    if (theme) document.documentElement.dataset.theme = theme;
    else if (window.matchMedia("(prefers-color-scheme: dark)").matches) document.documentElement.dataset.theme = "dark";
    $("#btn-theme use").setAttribute("href", document.documentElement.dataset.theme === "dark" ? "#i-sun" : "#i-moon");
    if (sidebar === "collapsed") { $("#shell").classList.add("sidebar-collapsed"); $("#sidebar-toggle use").setAttribute("href", "#i-chevr"); }
    $$("#list-status button").forEach((b) => b.classList.toggle("is-on", b.dataset.s === state.filters.list.status));
    applyRoute();
    refresh().then(() => { if (state.drawer) renderDrawer(); });
  })();
})();
