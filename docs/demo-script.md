# Five-minute demo

The point of the demo is not that an AI reads water data. It is that an AI reads water
data **and cannot publish anything**. Land that and the standards story lands with it.

## Setup

1. Put a Gemini key in `.env` as `GEMINI_API_KEY=...` (free at
   <https://aistudio.google.com/apikey>).
2. Set `GEMINI_ASSIST_MODE=always` for the recording so every card shows its AI
   attribution. `auto` is the sensible default outside a demo.
3. Put your UTS key from <https://uts.nlm.nih.gov/uts/profile> in `.env` as
   `UMLS_API_KEY=...`. Optional: the local LOINC table answers the water-quality codes on its
   own, and the key only adds SNOMED CT breadth.
4. Run `docker compose up --build` and wait for all three services to become healthy.
5. Open the console (<http://localhost:8000>) and the HAPI UI in separate tabs.
6. Confirm the top-bar pills read `AI gemini-3.1-pro-preview`, `FHIR enabled`, and
   `Crosswalk loinc-table+umls`, and that the sidebar footer shows the chain as `valid`.
   Set your reviewer identity from the avatar (top right) so approvals carry a name.
   Note: 3.1 Pro needs a billed Gemini project; on a free-tier key set
   `GEMINI_MODEL=gemini-3.1-flash-lite` instead.

Rehearse once, then **stop rebuilding**. Repeated `docker compose up --build` re-pulls
`hapiproject/hapi` and `postgres` and can hit Docker Hub's anonymous pull limit on shared
conference Wi-Fi. `docker login` with a free account before you travel.

## Narrative

**0:00–0:35 — The problem, stated concretely.** Cross-border water evidence arrives as
`EC_uScm`, `Leitfähigkeit`, `przewodność`, and as a paragraph in a voivodeship bulletin.
A public-health or veterinary consumer cannot act on any of it. In 2022 that fragmentation
was part of why the Oder fish kill outran the warning.

**0:35–1:20 — The hard case first.** Press **Create** (or `C`). The parameter is already
`Leitfähigkeit`, unit `uS/cm`. Submit it, then open the new card. Say plainly: string matching scores this at 0.31
and gives up. The card comes back mapped to `electrical-conductivity` with the OAH code, a
`GEMINI` chip, the evidence fragment the model quoted, the prompt hash, and the latency.

**1:20–2:00 — The guardrail, out loud.** Point at `2.35 mS/cm`. The model never computed
that. It named the unit; the conversion factor comes from the reviewed
`coding-rules.yaml`, and the prompt never contained the answer. The model could only choose
from a closed enum of catalog codes. Confidence is capped at 0.95 and the card is still
`pending`. There is no confidence value that publishes anything.

**2:00–2:50 — Unstructured intake.** Press **Create**, switch to the **Bulletin** tab, and
press **Extract readings**. Readings appear on the same board, with the
original labels preserved and a warning that the anglers' dead-fish report carried no
measurement and was not extracted. Two AI stages, both landing in the same place: a human's
work queue.

**2:50–3:30 — Standards, not a chart.** Open a pending card, go to its **Crosswalk** tab,
press **Suggest LOINC / SNOMED**, and pick the top candidate — for pH that is `9481-3` *pH of Water*. Say plainly what this closes: the
OAH temporary project code system is what the IG uses today, LOINC is what a hospital already
has loaded, and a reviewer decides whether to publish both. Approve the proposal. Show the
Observation in HAPI: the OAH profile URL in `meta.profile`, a `Location` subject, an
`Organization` performer, an effective time, a UCUM-coded quantity, and two entries in
`code.coding`. This is the interoperability claim, and it is checkable.

If you have 20 spare seconds, this is the strongest technical beat in the demo — see the
question below.

**3:30–4:20 — Alert and advisory.** On the **Board**, press **Load Oder replay**, then
**Approve all pending** (or drag the cards to the Approved column). Three readings cross the demonstration policy. Note that the *policy engine*
decided severity and audience — deterministic, versioned, in a separate file from the
terminology. Now open **Incidents**, open the low-oxygen incident, and press **Draft · Veterinary**. Gemini writes the
advisory the phone call would have carried, marked `draft`, with its uncertainty stated and
a disclaimer that an accountable authority must review it.

**4:20–5:00 — Trust.** Open **Reports** and press **Generate situation report** for a grounded
cross-site summary, then open **Audit log**, press **Verify chain**, and scroll the entries: `mapping-proposed`, `unstructured-intake`,
`mapping-approved`, `alert-created`, `briefing-drafted`, `situation-report` — each carrying
the model id and prompt hash, each hash-chained, verification `VALID`. Close on the
boundary: the bridge gives earlier machine-readable decision support; accountable
authorities review and communicate the warning.

## The question judges will ask

*"What if the model is wrong?"* Have the answer ready and demonstrate it if there is time:

- Wrong code → the reviewer sees the disagreement flag, the competing candidates, and the
  quoted evidence, and overrides the coding and quantity in the approve dialog
  (**Correct the proposal before publishing**).
- No safe code → the model returns `NO_MATCH`, confidence drops to zero, and approval is
  blocked until a human supplies one.
- Unknown unit → the quantity stays empty and approval is blocked. A code without a
  normalized UCUM quantity cannot be published.
- Model down or key missing → delete `GEMINI_API_KEY` and restart. Everything still works;
  the badge reads `AI off` and the AI-only endpoints return `503` with an explanation.
- *"Why isn't the LOINC/SNOMED coding automatic?"* Because a wrong crosswalk is worse than
  none. The same answer as the coding co-pilot: suggest, never select.
- *"Why not just query UMLS?"* Because a generic Metathesaurus search is a clinical search.
  Ask it for `pH` and it ranks *Peliosis hepatis* above anything about water; ask for
  `Water temperature` and it offers *Checking bath water temperature*. It also returns LOINC
  Parts (`LP...`) and Metathesaurus ids (`MTHU...`) that are not publishable LOINC codes at
  all. So the bridge searches the published LOINC table scoped to environmental specimens
  first — which finds `9481-3` pH of Water and `12530-2` Chloride in Water exactly — and
  validates every candidate against that table before a reviewer ever sees it.
- *"What about dissolved oxygen?"* Environmental LOINC has no term for it, nor for water
  temperature in water, nor for a satellite index like NDCI. The crosswalk returns nothing
  rather than a plausible-looking wrong code. That gap is exactly why the OAH IG needs a
  temporary code system, and saying so is more convincing than pretending full coverage.

## Evidence to capture

- Count of records ingested, mapped, approved, rejected, and alerted.
- FHIR transaction response and profile URL.
- Median raw-to-proposal and approval-to-publication latency, and Gemini latency separately.
- Reviewer override rate, and the `NO_MATCH` refusal rate.
- Validator output against the frozen OAH package.
- Exact demo policy id, model id, prompt-template ids, and source-data checksum.
- Which crosswalk sources answered, and the code picked (or the honest gap).
