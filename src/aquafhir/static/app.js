/* AquaFHIR Bridge — reviewer console.
   Vanilla ES2020, no build step. Rendering is a pure function of `state`;
   every mutation ends in render() so the sidebar counts can never drift from
   the list a reviewer is looking at. */

const API = "/api/v1";
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const state = {
  health: {},
  ai: { enabled: false },
  umls: { enabled: false },
  proposals: [],
  alerts: [],
  briefings: [],
  provenance: [],
  chain: null,
  suggestions: {},      // proposal id -> UMLS candidates
  secondaryPicks: {},   // proposal id -> Coding the reviewer chose
  filter: "pending",
  situation: null,
};

/* ── plumbing ───────────────────────────────────────────────────────────── */

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

let toastTimer;
function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = isError ? "toast show error" : "toast show";
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { node.className = "toast"; }, 4000);
}

async function withBusy(button, work) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Working…";
  try {
    await work();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function esc(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
}

function reviewer() {
  return $("#reviewer-name").value.trim() || "demo-reviewer";
}

function ago(iso) {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return new Date(iso).toISOString().slice(0, 10);
}

function shortDate(iso) {
  return iso ? String(iso).replace("T", " ").replace(/(\+00:00|Z)$/, "").slice(0, 16) : "—";
}

/* ── proposal rendering ─────────────────────────────────────────────────── */

function aiDetail(ai) {
  if (!ai) return "";
  const flags = [];
  if (ai.disagreed_with_rules) {
    flags.push('<span class="tag warn">disagrees with curated rules</span>');
  }
  if (ai.needs_expert_review) {
    flags.push('<span class="tag warn">model flagged for expert review</span>');
  }
  const evidence = (ai.evidence || []).length
    ? `<div class="detail-row">
         <span class="detail-label">Quoted</span>
         <span class="quote">${ai.evidence.map((item) => `“${esc(item)}”`).join(" · ")}</span>
       </div>`
    : "";
  return `
    <div class="detail-row">
      <span class="detail-label">Co-pilot</span>
      <span class="tag ai">${esc(ai.model)}</span>
      <span class="tag mono">${esc(ai.template_id)}</span>
      <span class="tag mono" title="SHA-256 of the exact rendered prompt">prompt ${esc(ai.prompt_hash.slice(0, 12))}</span>
      <span class="tag mono">${ai.latency_ms} ms</span>
      ${flags.join("")}
    </div>
    ${evidence}`;
}

function candidatesDetail(candidates) {
  if (!candidates || candidates.length < 2) return "";
  return `
    <div class="detail-row">
      <span class="detail-label">Also considered</span>
      ${candidates.map((item) => `<span class="tag mono" title="${esc(item.origin)}">${esc(item.code)} ${item.score.toFixed(2)}</span>`).join("")}
    </div>`;
}

function terminologyDetail(proposal) {
  if (proposal.status !== "pending" || !proposal.coding) return "";
  if (!state.umls.enabled) {
    return `<div class="detail-row">
      <span class="detail-label">LOINC / SNOMED</span>
      <span class="quote">Set UMLS_API_KEY to suggest a second coding.</span>
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
    body = `<button type="button" class="btn btn-sm" data-suggest="${proposal.id}">Suggest a code</button>`;
  } else if (found.length) {
    body = found
      .map((item) => `<button type="button" class="chip-btn" data-pick="${proposal.id}"
          data-system="${esc(item.system)}" data-code="${esc(item.code)}"
          data-display="${esc(item.display)}"
          title="${esc(item.display)} (score ${item.score})">${esc(item.vocabulary)} ${esc(item.code)}</button>`)
      .join("");
  } else {
    body = '<span class="quote">No UMLS candidate matched this term.</span>';
  }
  return `<div class="detail-row"><span class="detail-label">LOINC / SNOMED</span>${body}</div>`;
}

function proposalMarkup(proposal) {
  const { reading } = proposal;
  const resolved = proposal.normalized_value !== null && proposal.normalized_unit;
  const out = resolved
    ? `<div class="value">${proposal.normalized_value} ${esc(proposal.normalized_unit)}</div>
       <div class="term">${esc(proposal.coding ? proposal.coding.code : "")}</div>`
    : `<div class="value">unit unresolved</div>
       <div class="term">a reviewer must correct this before approval</div>`;

  const actions = proposal.status === "pending"
    ? `<div class="proposal-actions">
         <button class="btn btn-sm btn-primary" data-approve="${proposal.id}">Approve</button>
         <button class="btn btn-sm btn-danger" data-reject="${proposal.id}">Reject</button>
       </div>`
    : `<div class="proposal-actions"><span class="tag ${proposal.status}">${esc(proposal.status)}</span></div>`;

  const details = [
    candidatesDetail(proposal.candidates),
    aiDetail(proposal.ai),
    terminologyDetail(proposal),
  ].filter(Boolean).join("");

  return `<article class="proposal">
    <div class="proposal-main">
      <div>
        <div class="mapping">
          <div class="side">
            <div class="side-label">As received</div>
            <div class="value">${reading.value} ${esc(reading.unit)}</div>
            <div class="term">${esc(reading.parameter)}</div>
          </div>
          <div class="arrow" aria-hidden="true">→</div>
          <div class="side out ${resolved ? "" : "unresolved"}">
            <div class="side-label">OneAquaHealth FHIR</div>
            ${out}
          </div>
        </div>
        <div class="meta">
          <span><b>${esc(reading.site_name)}</b></span>
          <span>${esc(reading.source_type)} · ${esc(reading.source_id)}</span>
          <span>observed ${shortDate(reading.observed_at)}</span>
          <span>confidence <b>${Math.round(proposal.confidence * 100)}%</b></span>
          <span>${esc(proposal.proposer)}</span>
          ${proposal.reviewer ? `<span>reviewed by <b>${esc(proposal.reviewer)}</b></span>` : ""}
        </div>
        <p class="rationale">${esc(proposal.rationale)}</p>
      </div>
      ${actions}
    </div>
    ${details ? `<div class="detail">${details}</div>` : ""}
  </article>`;
}

/* ── alert rendering ────────────────────────────────────────────────────── */

function briefingMarkup(briefing) {
  return `<div class="briefing">
    <h4>${esc(briefing.audience)} — ${esc(briefing.headline)}</h4>
    <p>${esc(briefing.summary)}</p>
    <ul>${briefing.recommended_actions.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
    <p><b>Uncertainty.</b> ${esc(briefing.uncertainty)}</p>
    <p><b>Next question.</b> ${esc(briefing.escalation_question)}</p>
    <p class="disclaimer">${esc(briefing.disclaimer)}</p>
  </div>`;
}

function alertMarkup(alert) {
  const drafted = state.briefings.filter((item) => item.alert_id === alert.id);
  const done = new Set(drafted.map((item) => item.audience));
  const buttons = state.ai.enabled
    ? alert.audiences.map((audience) => `<button type="button" class="btn btn-sm"
          data-brief="${alert.id}" data-audience="${esc(audience)}">
          ${done.has(audience) ? "Redraft for" : "Draft for"} ${esc(audience)}</button>`).join("")
    : '<span class="quote">Set GEMINI_API_KEY to draft advisories.</span>';

  return `<article class="card alert sev-${esc(alert.severity)}">
    <div class="proposal-main">
      <div>
        <div class="alert-head">
          <h3>${esc(alert.rule_code)}</h3>
          <span class="alert-value">${alert.value} ${esc(alert.unit)}</span>
          <span class="tag ${alert.severity === "critical" ? "rejected" : "pending"}">${esc(alert.severity)}</span>
        </div>
        <p class="rationale">${esc(alert.message)}</p>
        <div class="meta">
          <span><b>${esc(alert.site_code)}</b></span>
          <span>observed ${shortDate(alert.observed_at)}</span>
          <span>policy ${esc(alert.policy_id)}</span>
          <span>routed to ${alert.audiences.map(esc).join(", ")}</span>
        </div>
      </div>
    </div>
    <div class="detail"><div class="detail-row">${buttons}</div></div>
    ${drafted.map(briefingMarkup).join("")}
  </article>`;
}

/* ── situation report ───────────────────────────────────────────────────── */

function situationMarkup(report) {
  if (!report) return "";
  return `<article class="card" style="margin-bottom:14px">
    <header class="card-head">
      <h2>${esc(report.headline)}</h2>
      <p>Considered ${report.observations_considered} observations, ${report.alerts_considered} alerts,
         ${report.pending_reviews} mappings still awaiting review.</p>
    </header>
    <div class="briefing" style="border-top:0">
      <p>${esc(report.situation)}</p>
      ${report.by_site.map((item) => `<p><b>${esc(item.site_code)}</b> — ${esc(item.assessment)}</p>`).join("")}
      <div class="split">
        <div><h4>Data gaps</h4><ul>${report.data_gaps.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></div>
        <div><h4>Next steps</h4><ul>${report.next_steps.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></div>
      </div>
      <p class="disclaimer">${esc(report.disclaimer)}</p>
    </div>
  </article>`;
}

/* ── render ─────────────────────────────────────────────────────────────── */

function setChip(id, label, on) {
  const node = $(id);
  node.textContent = label;
  node.className = `chip ${on ? "on" : "off"}`;
}

function render() {
  const pending = state.proposals.filter((item) => item.status === "pending");

  setChip("#chip-fhir", `FHIR ${state.health.fhir_write_mode || "—"}`,
    state.health.fhir_write_mode === "enabled");
  setChip("#chip-ai", state.ai.enabled ? `AI ${state.ai.model}` : "AI off", state.ai.enabled);
  setChip("#chip-umls",
    state.umls.enabled ? `UMLS ${(state.umls.vocabularies || []).join(" · ")}` : "UMLS off",
    state.umls.enabled);

  $("#nav-pending").textContent = pending.length;
  $("#nav-alerts").textContent = state.alerts.length;
  $("#stat-proposals").textContent = state.proposals.length;
  $("#stat-pending").textContent = pending.length;
  $("#stat-alerts").textContent = state.alerts.length;
  $("#stat-briefings").textContent = state.briefings.length;

  const chainCell = $("#stat-chain");
  if (state.chain) {
    chainCell.textContent = state.chain.valid ? "verified" : "broken";
    chainCell.className = state.chain.valid ? "ok" : "bad";
  }

  $("#intake-submit").disabled = !state.ai.enabled;
  $("#btn-situation").disabled = !state.ai.enabled;
  $("#intake-state").textContent = state.ai.enabled
    ? "Free text is read by Gemini and extracted literally."
    : "Needs GEMINI_API_KEY. Use the single-reading form meanwhile.";

  // Review queue
  const shown = state.filter === "all"
    ? state.proposals
    : state.proposals.filter((item) => item.status === state.filter);
  $("#proposal-list").innerHTML = shown.length
    ? shown.map(proposalMarkup).join("")
    : `<div class="empty"><b>Nothing ${state.filter === "all" ? "here" : state.filter}</b>
         ${state.proposals.length ? "Try another filter." : "Load the Oder replay or submit a reading from Ingest."}</div>`;

  // Alerts
  $("#alert-list").innerHTML = state.alerts.length
    ? state.alerts.map(alertMarkup).join("")
    : `<div class="empty"><b>No thresholds crossed</b>
         Alerts appear here once an approved observation crosses the policy.</div>`;

  // Audit
  const banner = $("#chain-banner");
  if (state.chain) {
    banner.className = `banner ${state.chain.valid ? "ok" : "bad"}`;
    banner.textContent = state.chain.valid
      ? `Hash chain verified across ${state.chain.entries_checked} entries.`
      : `Chain broken at sequence ${state.chain.first_invalid_sequence}.`;
  }
  $("#situation-report").innerHTML = situationMarkup(state.situation);
  $("#provenance-rows").innerHTML = state.provenance.length
    ? state.provenance.map((entry) => `<tr>
        <td class="num">${entry.sequence}</td>
        <td><b>${esc(entry.event_type)}</b></td>
        <td class="mono">${esc(entry.entity_id.slice(0, 20))}</td>
        <td class="mono" title="${esc(entry.hash)}">${esc(entry.hash.slice(0, 16))}</td>
        <td>${ago(entry.created_at)}</td>
      </tr>`).join("")
    : '<tr><td colspan="5">No events recorded yet.</td></tr>';
}

async function refresh() {
  try {
    const [health, ai, umls, proposals, alerts, briefings, provenance, chain] = await Promise.all([
      request("/health"), request("/ai/status"), request("/terminology/status"),
      request("/proposals"), request("/alerts"), request("/briefings"),
      request("/provenance?limit=25"), request("/provenance/verify"),
    ]);
    Object.assign(state, { health, ai, umls, proposals, alerts, briefings, provenance, chain });
    render();
  } catch (error) {
    toast(error.message, true);
  }
}

/* ── interactions ───────────────────────────────────────────────────────── */

$$(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item === button));
    $$(".view").forEach((view) => {
      view.classList.toggle("is-active", view.dataset.view === button.dataset.view);
    });
  });
});

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    state.filter = tab.dataset.filter;
    $$(".tab").forEach((item) => item.classList.toggle("is-active", item === tab));
    render();
  });
});

$("#reviewer-name").addEventListener("change", (event) => {
  window.localStorage.setItem("aquafhir.reviewer", event.target.value.trim());
});

$("#reading-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const payload = {
    source_id: "manual-console",
    source_type: "agency",
    parameter: data.get("parameter"),
    value: Number(data.get("value")),
    unit: data.get("unit"),
    observed_at: new Date().toISOString(),
    site_code: "oder-kostrzyn",
    site_name: data.get("site_name"),
    latitude: Number(data.get("latitude")),
    longitude: Number(data.get("longitude")),
  };
  await withBusy(event.currentTarget.querySelector("button[type=submit]"), async () => {
    await request("/proposals", { method: "POST", body: JSON.stringify(payload) });
    toast("Proposal created. It is pending in the review queue.");
    await refresh();
  });
});

$("#intake-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  await withBusy($("#intake-submit"), async () => {
    const result = await request("/intake", {
      method: "POST",
      body: JSON.stringify({
        text: data.get("text"),
        source_id: data.get("source_id"),
        source_type: "agency",
        default_site_code: data.get("default_site_code"),
        default_site_name: "Oder at Kostrzyn",
      }),
    });
    $("#intake-warnings").innerHTML = result.warnings
      .map((item) => `<p class="note">${esc(item)}</p>`).join("");
    toast(`Extracted ${result.extracted_count} reading(s) into the review queue.`);
    await refresh();
  });
});

$("#proposal-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const { approve, reject, suggest, pick } = button.dataset;

  if (suggest) {
    await withBusy(button, async () => {
      state.suggestions[suggest] = await request(`/proposals/${suggest}/terminology-suggestions`);
      render();
    });
    return;
  }
  if (pick) {
    state.secondaryPicks[pick] = {
      system: button.dataset.system,
      code: button.dataset.code,
      display: button.dataset.display,
    };
    toast(`${button.dataset.code} will be attached when this proposal is approved.`);
    render();
    return;
  }
  if (!approve && !reject) return;

  await withBusy(button, async () => {
    if (approve) {
      const secondary = state.secondaryPicks[approve];
      await request(`/proposals/${approve}/approve`, {
        method: "POST",
        body: JSON.stringify({
          reviewer: reviewer(),
          ...(secondary ? { secondary_coding: secondary } : {}),
        }),
      });
      toast("Approved. FHIR resources built and the policy evaluated.");
    } else {
      await request(`/proposals/${reject}/reject`, {
        method: "POST",
        body: JSON.stringify({ reviewer: reviewer(), reason: "Rejected during review" }),
      });
      toast("Rejected. The decision is recorded and immutable.");
    }
    await refresh();
  });
});

$("#alert-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-brief]");
  if (!button) return;
  await withBusy(button, async () => {
    const audience = button.dataset.audience;
    await request(`/alerts/${button.dataset.brief}/briefings?audience=${encodeURIComponent(audience)}`,
      { method: "POST" });
    toast(`Draft advisory ready for ${audience}.`);
    await refresh();
  });
});

$("#btn-replay").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    const proposals = await request("/replay", { method: "POST" });
    toast(`Loaded ${proposals.length} readings from the synthetic Oder timeline.`);
    await refresh();
  });
});

$("#btn-approve-all").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    const ids = state.proposals.filter((item) => item.status === "pending").map((item) => item.id);
    if (!ids.length) { toast("Nothing is pending."); return; }
    const result = await request("/proposals/approve-batch", {
      method: "POST",
      body: JSON.stringify({ reviewer: reviewer(), proposal_ids: ids }),
    });
    const failed = result.failures.length;
    toast(`Approved ${result.approved.length}${failed ? `; ${failed} need a reviewer correction` : ""}.`);
    await refresh();
  });
});

$("#btn-situation").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    state.situation = await request("/ai/situation-report", { method: "POST" });
    render();
  });
});

$("#btn-refresh").addEventListener("click", refresh);

$("#reviewer-name").value = window.localStorage.getItem("aquafhir.reviewer") || "";
refresh();
