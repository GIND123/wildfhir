# Five-minute demo

The point of the demo is not that an AI reads water data. It is that an AI reads water
data **and cannot publish anything**. Land that and the standards story lands with it.

## Setup

1. Put a Gemini key in `.env` as `GEMINI_API_KEY=...` (free at
   <https://aistudio.google.com/apikey>).
2. Set `GEMINI_ASSIST_MODE=always` for the recording so every card shows its AI
   attribution. `auto` is the sensible default outside a demo.
3. If the UMLS license has been approved by NLM by demo day, put the key from
   <https://uts.nlm.nih.gov/uts/profile> in `.env` as `UMLS_API_KEY=...`. If not, skip this —
   the badge reads `UMLS off`, the "Suggest LOINC/SNOMED" beat below is skipped, and nothing
   else in the script changes.
4. Run `docker compose up --build` and wait for all three services to become healthy.
5. Open the console (<http://localhost:8000>) and the HAPI UI in separate tabs.
6. Confirm the header shows `AI gemini-2.5-flash · always`, `FHIR enabled`, and an audit
   chain of `VALID` (plus `UMLS LNC/SNOMEDCT_US` if the key is set).

Rehearse once, then **stop rebuilding**. Repeated `docker compose up --build` re-pulls
`hapiproject/hapi` and `postgres` and can hit Docker Hub's anonymous pull limit on shared
conference Wi-Fi. `docker login` with a free account before you travel.

## Narrative

**0:00–0:35 — The problem, stated concretely.** Cross-border water evidence arrives as
`EC_uScm`, `Leitfähigkeit`, `przewodność`, and as a paragraph in a voivodeship bulletin.
A public-health or veterinary consumer cannot act on any of it. In 2022 that fragmentation
was part of why the Oder fish kill outran the warning.

**0:35–1:20 — The hard case first.** In the structured ingest form the parameter is already
`Leitfähigkeit`, unit `uS/cm`. Submit it. Say plainly: string matching scores this at 0.31
and gives up. The card comes back mapped to `electrical-conductivity` with the OAH code, a
`GEMINI` chip, the evidence fragment the model quoted, the prompt hash, and the latency.

**1:20–2:00 — The guardrail, out loud.** Point at `2.35 mS/cm`. The model never computed
that. It named the unit; the conversion factor comes from the reviewed
`coding-rules.yaml`, and the prompt never contained the answer. The model could only choose
from a closed enum of catalog codes. Confidence is capped at 0.95 and the card is still
`pending`. There is no confidence value that publishes anything.

**2:00–2:50 — Unstructured intake.** Paste the German bulletin in the right-hand panel and
press **Extract readings**. Readings appear in the same review queue, with the
original labels preserved and a warning that the anglers' dead-fish report carried no
measurement and was not extracted. Two AI stages, both landing in the same place: a human's
work queue.

**2:50–3:30 — Standards, not a chart.** If `UMLS_API_KEY` is set, click **Suggest
LOINC/SNOMED (UMLS)** on the pending card first and pick the top candidate — say plainly
that this closes the exact gap the OAH IG's own conformance notes flag: the temporary
project code system is what OAH uses today, LOINC/SNOMED CT is what a hospital already has
loaded, and a reviewer decides whether to publish both. Approve the proposal. Show the
Observation in HAPI: the OAH profile URL in `meta.profile`, a `Location` subject, an
`Organization` performer, an effective time, a UCUM-coded quantity, and — if UMLS ran —
two entries in `code.coding`. This is the interoperability claim, and it is checkable.

**3:30–4:20 — Alert and advisory.** In **Review queue**, press **Load Oder replay**, then
**Approve all pending**. Three readings cross the demonstration policy. Note that the *policy engine*
decided severity and audience — deterministic, versioned, in a separate file from the
terminology. Now press **Draft veterinary** on the low-oxygen alert. Gemini writes the
advisory the phone call would have carried, marked `draft`, with its uncertainty stated and
a disclaimer that an accountable authority must review it.

**4:20–5:00 — Trust.** Open **Audit trail** and press **Draft situation report** for a grounded cross-site summary, then
scroll the provenance timeline: `mapping-proposed`, `unstructured-intake`,
`mapping-approved`, `alert-created`, `briefing-drafted`, `situation-report` — each carrying
the model id and prompt hash, each hash-chained, verification `VALID`. Close on the
boundary: the bridge gives earlier machine-readable decision support; accountable
authorities review and communicate the warning.

## The question judges will ask

*"What if the model is wrong?"* Have the answer ready and demonstrate it if there is time:

- Wrong code → the reviewer sees the disagreement flag, the competing candidates, and the
  quoted evidence, and overrides with `coding` in the approve body.
- No safe code → the model returns `NO_MATCH`, confidence drops to zero, and approval is
  blocked until a human supplies one.
- Unknown unit → the quantity stays empty and approval is blocked. A code without a
  normalized UCUM quantity cannot be published.
- Model down or key missing → delete `GEMINI_API_KEY` and restart. Everything still works;
  the badge reads `AI off` and the AI-only endpoints return `503` with an explanation.
- *"Why isn't the LOINC/SNOMED coding automatic?"* Because a wrong crosswalk is worse than
  none — UMLS ranks candidates by name similarity only, and a reviewer decides. The same
  answer as the coding co-pilot: suggest, never select.

## Evidence to capture

- Count of records ingested, mapped, approved, rejected, and alerted.
- FHIR transaction response and profile URL.
- Median raw-to-proposal and approval-to-publication latency, and Gemini latency separately.
- Reviewer override rate, and the `NO_MATCH` refusal rate.
- Validator output against the frozen OAH package.
- Exact demo policy id, model id, prompt-template ids, and source-data checksum.
- Whether the UMLS crosswalk ran, which vocabularies it searched, and the code picked.
