const api = "/api/v1";
const $ = (selector) => document.querySelector(selector);

const demoReadings = [
  ["agency", "EC", 1.2, "mS/cm", "2022-07-24T08:00:00Z"],
  ["satellite", "NDCI", 0.18, "1", "2022-07-25T10:15:00Z"],
  ["agency", "electrical conductivity", 2.35, "mS/cm", "2022-07-27T08:00:00Z"],
  ["satellite", "normalized difference chlorophyll index", 0.43, "1", "2022-07-28T10:15:00Z"],
  ["agency", "dissolved O2", 3.6, "mg/L", "2022-07-29T07:30:00Z"],
].map(([source_type, parameter, value, unit, observed_at], index) => ({
  source_id: source_type === "satellite" ? "copernicus-s2" : `oder-agency-${index + 1}`,
  source_type,
  parameter,
  value,
  unit,
  observed_at,
  site_code: index === 4 ? "oder-frankfurt" : "oder-kostrzyn",
  site_name: index === 4 ? "Oder at Frankfurt" : "Oder at Kostrzyn",
  latitude: index === 4 ? 52.3471 : 52.5887,
  longitude: index === 4 ? 14.5506 : 14.6495,
}));

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
  window.setTimeout(() => { node.className = ""; }, 2800);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
}

function proposalMarkup(proposal) {
  const coding = proposal.coding
    ? `<code>${escapeHtml(proposal.coding.code)} · ${escapeHtml(proposal.normalized_unit || "unit unresolved")}</code>`
    : `<code>No terminology candidate</code>`;
  const actions = proposal.status === "pending"
    ? `<div class="card-actions"><button class="primary" data-approve="${proposal.id}">Approve</button><button class="secondary" data-reject="${proposal.id}">Reject</button></div>`
    : `<span class="status ${proposal.status}">${proposal.status}</span>`;
  return `<article class="data-card"><div><h3>${escapeHtml(proposal.reading.parameter)} · ${proposal.reading.value} ${escapeHtml(proposal.reading.unit)}</h3><p>${escapeHtml(proposal.reading.site_name)} · confidence ${Math.round(proposal.confidence * 100)}%</p>${coding}<p>${escapeHtml(proposal.rationale)}</p></div>${actions}</article>`;
}

function alertMarkup(alert) {
  return `<article class="data-card"><div><h3 class="severity-${escapeHtml(alert.severity)}">${escapeHtml(alert.severity.toUpperCase())} · ${escapeHtml(alert.rule_code)}</h3><p>${escapeHtml(alert.message)}</p><p>${alert.value} ${escapeHtml(alert.unit)} · ${escapeHtml(alert.site_code)}</p><div class="audiences">${alert.audiences.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div></div></article>`;
}

function provenanceMarkup(entry) {
  return `<div class="timeline-item"><strong>${escapeHtml(entry.event_type)}</strong><p>#${entry.sequence} · ${escapeHtml(entry.entity_id)}</p><p>${entry.hash.slice(0, 18)}…</p></div>`;
}

async function refresh() {
  try {
    const [health, proposals, alerts, provenance, chain] = await Promise.all([
      request("/health"), request("/proposals"), request("/alerts"),
      request("/provenance?limit=20"), request("/provenance/verify"),
    ]);
    $("#mode-badge").textContent = health.fhir_write_mode;
    $("#proposal-count").textContent = proposals.length;
    $("#pending-count").textContent = proposals.filter((item) => item.status === "pending").length;
    $("#alert-count").textContent = alerts.length;
    $("#chain-status").textContent = chain.valid ? "VALID" : "BROKEN";
    $("#proposal-list").innerHTML = proposals.length ? proposals.map(proposalMarkup).join("") : '<p class="empty">No proposals yet.</p>';
    $("#alert-list").innerHTML = alerts.length ? alerts.map(alertMarkup).join("") : '<p class="empty">No thresholds crossed.</p>';
    $("#provenance-list").innerHTML = provenance.length ? provenance.map(provenanceMarkup).join("") : '<p class="empty">No events recorded.</p>';
  } catch (error) { toast(error.message, true); }
}

$("#reading-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const payload = {
    source_id: "manual-dashboard", source_type: "agency",
    parameter: data.get("parameter"), value: Number(data.get("value")), unit: data.get("unit"),
    observed_at: new Date().toISOString(), site_code: "oder-kostrzyn",
    site_name: data.get("site_name"), latitude: Number(data.get("latitude")), longitude: Number(data.get("longitude")),
  };
  try {
    await request("/proposals", { method: "POST", body: JSON.stringify(payload) });
    toast("Mapping proposal created for review."); await refresh();
  } catch (error) { toast(error.message, true); }
});

$("#proposal-list").addEventListener("click", async (event) => {
  const approveId = event.target.dataset.approve;
  const rejectId = event.target.dataset.reject;
  try {
    if (approveId) await request(`/proposals/${approveId}/approve`, { method: "POST", body: JSON.stringify({ reviewer: "demo-reviewer" }) });
    if (rejectId) await request(`/proposals/${rejectId}/reject`, { method: "POST", body: JSON.stringify({ reviewer: "demo-reviewer", reason: "Rejected during demo review" }) });
    if (approveId || rejectId) { toast(approveId ? "FHIR mapping approved and published." : "Proposal rejected."); await refresh(); }
  } catch (error) { toast(error.message, true); }
});

$("#replay-button").addEventListener("click", async (event) => {
  event.currentTarget.disabled = true;
  try {
    for (const reading of demoReadings) await request("/proposals", { method: "POST", body: JSON.stringify(reading) });
    toast("Oder timeline loaded. Review the five proposals below."); await refresh();
  } catch (error) { toast(error.message, true); }
  finally { event.currentTarget.disabled = false; }
});

$("#refresh-button").addEventListener("click", refresh);
refresh();

