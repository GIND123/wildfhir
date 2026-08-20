const api = "/api/v1";
const $ = (selector) => document.querySelector(selector);

const state = {
  ai: { enabled: false },
  umls: { enabled: false },
  briefings: [],
  proposals: [],
  suggestions: {},
  secondaryPicks: {},
};

async function request(path, options = {}) {
  const response = await fetch(`${api}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = error ? "show error" : "show";
  window.setTimeout(() => { node.className = ""; }, 3600);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
}

async function withBusy(button, work) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Working…";
  try { await work(); } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = label; }
}

/* ---------- renderers ---------- */

function aiMarkup(ai) {
  if (!ai) return "";
  const flags = [];
  if (ai.disagreed_with_rules) flags.push('<span class="flag warn">AI disagrees with curated rules</span>');
  if (ai.needs_expert_review) flags.push('<span class="flag warn">Model asked for expert review</span>');
  const evidence = (ai.evidence || []).length
    ? `<p class="evidence">Evidence: ${ai.evidence.map((item) => `“${escapeHtml(item)}”`).join(" · ")}</p>`
    : "";
  return `<div class="ai-strip">
    <span class="flag ai">GEMINI ${escapeHtml(ai.model)}</span>
    <span class="flag">${escapeHtml(ai.template_id)}</span>
    <span class="flag mono" title="SHA-256 of the exact prompt">prompt ${escapeHtml(ai.prompt_hash.slice(0, 10))}…</span>
    <span class="flag mono">${ai.latency_ms} ms</span>
    ${flags.join("")}
    ${evidence}
  </div>`;
}

function candidatesMarkup(candidates) {
  if (!candidates || candidates.length < 2) return "";
  return `<div class="audiences">${candidates
    .map((item) => `<span title="${escapeHtml(item.origin)}">${escapeHtml(item.code)} ${item.score.toFixed(2)}</span>`)
    .join("")}</div>`;
}

function terminologyMarkup(proposal) {
  if (proposal.status !== "pending" || !proposal.coding) return "";
  if (!state.umls.enabled) {
    return `<p class="evidence">Set UMLS_API_KEY to suggest a real LOINC/SNOMED CT code.</p>`;
  }
  const picked = state.secondaryPicks[proposal.id];
  if (picked) {
    return `<div class="terminology">
      <span class="chip-button picked">${escapeHtml(picked.system)} ${escapeHtml(picked.code)}
        · ${escapeHtml(picked.display)} — will attach on approval</span>
    </div>`;
  }
  const suggestions = state.suggestions[proposal.id];
  const chips = suggestions && suggestions.length
    ? `<div class="chip-row">${suggestions
        .map((item) => `<button type="button" class="chip-button" data-pick="${proposal.id}"
            data-system="${escapeHtml(item.system)}" data-code="${escapeHtml(item.code)}"
            data-display="${escapeHtml(item.display)}">
            ${escapeHtml(item.vocabulary)} ${escapeHtml(item.code)} · ${escapeHtml(item.display)}
          </button>`)
        .join("")}</div>`
    : suggestions
      ? `<p class="evidence">No UMLS candidates found for this code.</p>`
      : "";
  return `<div class="terminology">
    <button type="button" class="secondary" data-suggest="${proposal.id}">Suggest LOINC/SNOMED (UMLS)</button>
    ${chips}
  </div>`;
}

function proposalMarkup(proposal) {
  const quantity = proposal.normalized_value === null
    ? "unit unresolved — reviewer must correct"
    : `${proposal.normalized_value} ${escapeHtml(proposal.normalized_unit)}`;
  const coding = proposal.coding
    ? `<code>${escapeHtml(proposal.coding.code)} → ${quantity}</code>`
    : `<code class="danger">No terminology candidate</code>`;
  const actions = proposal.status === "pending"
    ? `<div class="card-actions">
         <button class="primary" data-approve="${proposal.id}">Approve</button>
         <button class="secondary" data-reject="${proposal.id}">Reject</button>
       </div>`
    : `<span class="status ${proposal.status}">${proposal.status}</span>`;
  return `<article class="data-card">
    <div>
      <h3>${escapeHtml(proposal.reading.parameter)} · ${proposal.reading.value} ${escapeHtml(proposal.reading.unit)}</h3>
      <p>${escapeHtml(proposal.reading.site_name)} · ${escapeHtml(proposal.reading.source_type)} ·
         confidence ${Math.round(proposal.confidence * 100)}% ·
         <span class="mono">${escapeHtml(proposal.proposer)}</span></p>
      ${coding}
      <p>${escapeHtml(proposal.rationale)}</p>
      ${candidatesMarkup(proposal.candidates)}
      ${aiMarkup(proposal.ai)}
      ${terminologyMarkup(proposal)}
    </div>
    ${actions}
  </article>`;
}

function renderProposalList() {
  $("#proposal-list").innerHTML = state.proposals.length
    ? state.proposals.map(proposalMarkup).join("") : '<p class="empty">No proposals yet.</p>';
}

function briefingMarkup(briefing) {
  return `<div class="briefing">
    <strong>${escapeHtml(briefing.audience)} · ${escapeHtml(briefing.headline)}</strong>
    <p>${escapeHtml(briefing.summary)}</p>
    <ul>${briefing.recommended_actions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    <p class="evidence">Uncertainty: ${escapeHtml(briefing.uncertainty)}</p>
    <p class="evidence">Next question: ${escapeHtml(briefing.escalation_question)}</p>
    <p class="disclaimer">${escapeHtml(briefing.disclaimer)}</p>
    ${aiMarkup(briefing.ai)}
  </div>`;
}

function alertMarkup(alert) {
  const drafted = state.briefings.filter((item) => item.alert_id === alert.id);
  const draftedAudiences = new Set(drafted.map((item) => item.audience));
  const buttons = state.ai.enabled
    ? `<div class="card-actions wrap">${alert.audiences
        .map((audience) => `<button class="secondary" data-brief="${alert.id}" data-audience="${escapeHtml(audience)}">
            ${draftedAudiences.has(audience) ? "Redraft" : "Draft"} ${escapeHtml(audience)}
          </button>`)
        .join("")}</div>`
    : `<p class="evidence">Set GEMINI_API_KEY to draft audience advisories.</p>`;
  return `<article class="data-card stacked">
    <div>
      <h3 class="severity-${escapeHtml(alert.severity)}">${escapeHtml(alert.severity.toUpperCase())} · ${escapeHtml(alert.rule_code)}</h3>
      <p>${escapeHtml(alert.message)}</p>
      <p>${alert.value} ${escapeHtml(alert.unit)} · ${escapeHtml(alert.site_code)} · policy ${escapeHtml(alert.policy_id)}</p>
      <div class="audiences">${alert.audiences.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
      ${buttons}
      ${drafted.map(briefingMarkup).join("")}
    </div>
  </article>`;
}

function provenanceMarkup(entry) {
  return `<div class="timeline-item">
    <strong>${escapeHtml(entry.event_type)}</strong>
    <p>#${entry.sequence} · ${escapeHtml(entry.entity_id)}</p>
    <p>${escapeHtml(entry.hash.slice(0, 18))}…</p>
  </div>`;
}

function renderSituation(report) {
  $("#situation-panel").classList.remove("hidden");
  $("#situation-headline").textContent = report.headline || "Situation report";
  $("#situation-body").innerHTML = `
    <p>${escapeHtml(report.situation)}</p>
    ${report.by_site.map((item) => `<p><strong>${escapeHtml(item.site_code)}</strong> — ${escapeHtml(item.assessment)}</p>`).join("")}
    <div class="split">
      <div><h4>Data gaps</h4><ul>${report.data_gaps.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
      <div><h4>Next steps</h4><ul>${report.next_steps.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
    </div>
    <p class="evidence">Considered ${report.observations_considered} observations, ${report.alerts_considered} alerts,
       ${report.pending_reviews} mappings still awaiting review.</p>
    <p class="disclaimer">${escapeHtml(report.disclaimer)}</p>
    ${aiMarkup(report.ai)}`;
  $("#situation-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ---------- data flow ---------- */

async function refresh() {
  try {
    const [health, ai, umls, proposals, alerts, briefings, provenance, chain] = await Promise.all([
      request("/health"), request("/ai/status"), request("/terminology/status"),
      request("/proposals"), request("/alerts"),
      request("/briefings"), request("/provenance?limit=20"), request("/provenance/verify"),
    ]);
    state.ai = ai;
    state.umls = umls;
    state.briefings = briefings;
    state.proposals = proposals;

    $("#mode-badge").textContent = `FHIR ${health.fhir_write_mode}`;
    const aiBadge = $("#ai-badge");
    aiBadge.textContent = ai.enabled ? `AI ${ai.model} · ${ai.assist_mode}` : "AI off";
    aiBadge.classList.toggle("off", !ai.enabled);
    $("#intake-availability").textContent = ai.enabled ? "" : "needs GEMINI_API_KEY";
    $("#intake-submit").disabled = !ai.enabled;
    $("#situation-button").disabled = !ai.enabled;

    const umlsBadge = $("#umls-badge");
    umlsBadge.textContent = umls.enabled ? `UMLS ${umls.vocabularies.join("/")}` : "UMLS off";
    umlsBadge.classList.toggle("off", !umls.enabled);

    $("#proposal-count").textContent = proposals.length;
    $("#pending-count").textContent = proposals.filter((item) => item.status === "pending").length;
    $("#alert-count").textContent = alerts.length;
    $("#briefing-count").textContent = briefings.length;
    $("#chain-status").textContent = chain.valid ? "VALID" : "BROKEN";
    $("#chain-status").className = chain.valid ? "" : "danger";

    renderProposalList();
    $("#alert-list").innerHTML = alerts.length
      ? alerts.map(alertMarkup).join("") : '<p class="empty">No thresholds crossed.</p>';
    $("#provenance-list").innerHTML = provenance.length
      ? provenance.map(provenanceMarkup).join("") : '<p class="empty">No events recorded.</p>';
  } catch (error) { toast(error.message, true); }
}

$("#reading-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const payload = {
    source_id: "manual-dashboard",
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
  await withBusy(form.querySelector("button"), async () => {
    await request("/proposals", { method: "POST", body: JSON.stringify(payload) });
    toast("Mapping proposal created for review.");
    await refresh();
  });
});

$("#intake-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const payload = {
    text: data.get("text"),
    source_id: data.get("source_id"),
    source_type: "agency",
    default_site_code: data.get("default_site_code"),
    default_site_name: "Oder at Kostrzyn",
  };
  await withBusy($("#intake-submit"), async () => {
    const result = await request("/intake", { method: "POST", body: JSON.stringify(payload) });
    $("#intake-warnings").innerHTML = result.warnings
      .map((item) => `<p class="warn">⚠ ${escapeHtml(item)}</p>`).join("");
    toast(`Extracted ${result.extracted_count} reading(s) into the review queue.`);
    await refresh();
  });
});

$("#proposal-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const approveId = button.dataset.approve;
  const rejectId = button.dataset.reject;
  const suggestId = button.dataset.suggest;
  const pickId = button.dataset.pick;

  if (suggestId) {
    await withBusy(button, async () => {
      state.suggestions[suggestId] = await request(
        `/proposals/${suggestId}/terminology-suggestions`,
      );
      renderProposalList();
    });
    return;
  }
  if (pickId) {
    state.secondaryPicks[pickId] = {
      system: button.dataset.system,
      code: button.dataset.code,
      display: button.dataset.display,
    };
    toast(`Attached ${button.dataset.code} — included when this proposal is approved.`);
    renderProposalList();
    return;
  }
  if (!approveId && !rejectId) return;
  await withBusy(button, async () => {
    if (approveId) {
      const secondaryCoding = state.secondaryPicks[approveId];
      await request(`/proposals/${approveId}/approve`, {
        method: "POST",
        body: JSON.stringify({
          reviewer: "demo-reviewer",
          ...(secondaryCoding ? { secondary_coding: secondaryCoding } : {}),
        }),
      });
      toast("Approved. FHIR resources built and policy evaluated.");
    } else {
      await request(`/proposals/${rejectId}/reject`, {
        method: "POST",
        body: JSON.stringify({ reviewer: "demo-reviewer", reason: "Rejected during demo review" }),
      });
      toast("Proposal rejected and recorded.");
    }
    await refresh();
  });
});

$("#alert-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-brief]");
  if (!button) return;
  await withBusy(button, async () => {
    await request(
      `/alerts/${button.dataset.brief}/briefings?audience=${encodeURIComponent(button.dataset.audience)}`,
      { method: "POST" },
    );
    toast(`Draft advisory ready for ${button.dataset.audience}.`);
    await refresh();
  });
});

$("#replay-button").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    const proposals = await request("/replay", { method: "POST" });
    toast(`Oder timeline loaded — ${proposals.length} proposals awaiting review.`);
    await refresh();
  });
});

$("#approve-all-button").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    const proposals = await request("/proposals");
    const ids = proposals.filter((item) => item.status === "pending").map((item) => item.id);
    if (!ids.length) { toast("Nothing pending."); return; }
    const result = await request("/proposals/approve-batch", {
      method: "POST",
      body: JSON.stringify({ reviewer: "demo-reviewer", proposal_ids: ids }),
    });
    const failed = result.failures.length;
    toast(`Approved ${result.approved.length}${failed ? `, ${failed} need reviewer correction` : ""}.`);
    await refresh();
  });
});

$("#situation-button").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    renderSituation(await request("/ai/situation-report", { method: "POST" }));
  });
});

$("#refresh-button").addEventListener("click", refresh);
refresh();
