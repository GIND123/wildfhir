# AquaFHIR Bridge

AquaFHIR Bridge is a FHIR-native One Health data bus with a **reviewed Gemini co-pilot** and a **LOINC/SNOMED CT terminology crosswalk**. It converts heterogeneous water and Earth-observation readings — including free-text agency bulletins — into reviewed [OneAquaHealth FHIR R4](https://build.fhir.org/ig/hl7-eu/oah/) resources, publishes them to a HAPI FHIR server, evaluates an explicit alert policy, drafts audience-specific advisories, and records each transformation in a tamper-evident audit chain.

The AI is deliberately bounded, and so is the terminology assist built on top of it. Gemini decides *which curated code a messy label means*, *which measurements a note literally contains*, and *how to phrase an advisory*. The crosswalk decides only *which real LOINC/SNOMED CT concepts match this curated code's name* — validated against the published LOINC term list, and a reviewer must explicitly pick one before it is attached. Deterministic code decides *the published number*, *whether review is required* (always), *whether an alert fires*, and *what is written to FHIR*. Remove either API key and the whole pipeline still runs — both paths are tested.

This repository contains only the first concept from the source brief: **the One Health data bus and reviewed coding agent**. It does not include the separate BloomGuard prediction product or StreamSentinel symptom-surveillance concept.

> Status: detailed prototype boilerplate. It is suitable for a hackathon demonstration and engineering handoff, not clinical, veterinary, public-warning, or regulatory production use.

## Current status: done vs. pending

**Done and tested (332 offline tests, no live Gemini or UMLS call ever runs in CI):**

- Curated OAH terminology coding and reviewed unit conversion ([coding.py](src/aquafhir/coding.py))
- Gemini coding co-pilot, unstructured-bulletin intake, audience advisory drafting, grounded situation reports — all human-reviewed, all degrade cleanly with no key ([coding_llm.py](src/aquafhir/coding_llm.py), [intake.py](src/aquafhir/intake.py), [briefing.py](src/aquafhir/briefing.py))
- **Terminology crosswalk** — suggests real LOINC/SNOMED CT codes for a curated OAH code, searching the committed LOINC table locally first (finds `9481-3` pH of Water, `12530-2` Chloride in Water) and topping up from UMLS UTS; invalid UMLS results are rejected against the published term list. A reviewer explicitly attaches one at approval, and it is published as a second `Coding` on the FHIR Observation ([loinc_table.py](src/aquafhir/loinc_table.py), [terminology.py](src/aquafhir/terminology.py), [umls.py](src/aquafhir/umls.py); see [§ The terminology crosswalk](#the-terminology-crosswalk))
- **UMLS license approved** (2026-08-20) and the live UTS API verified end to end against the 2026AA release
- HAPI FHIR R4 publication against the real `hl7.eu.fhir.oah` profiles, transaction bundles, Subscription install and rest-hook processing ([fhir.py](src/aquafhir/fhir.py))
- Versioned, unit-aware threshold policy with audience routing ([thresholds.py](src/aquafhir/thresholds.py))
- SQLite-backed, hash-chained provenance for every proposal, decision, alert, and model/terminology call
- A dependency-free review console in the shape of a work-management tool: a Kanban board (drag a card to Approved or Rejected), a sortable queue with bulk sign-off, an issue-style detail panel with Details / Co-pilot / Crosswalk / FHIR / History tabs, incidents with per-audience advisory drafting, a hash-chain audit log, a policy & catalog page, an integrations page that shows every credential as a fingerprint, a command palette (⌘K), and keyboard shortcuts
- **Defensive ingestion boundaries.** The rest-hook Subscription surface accepts whatever a FHIR server sends: null or non-numeric quantities, absent ids, FHIR partial dates (`2022-07`), and wrong-typed `code.coding` are skipped with a log line instead of raising. Non-finite quantities are rejected at the model boundary rather than published as a JSON-null `valueQuantity.value` ([test_robustness.py](tests/test_robustness.py))
- **A failed sensor cannot raise an alert.** Each indicator carries a reviewed `plausible_range` in [coding-rules.yaml](config/coding-rules.yaml), enforced in the single place both proposers compute a published number. A dissolved-oxygen probe reporting `-5.0 mg/L`, a `pH` of `130.0`, or a temperature below absolute zero is coded but its *quantity is withheld* — no publication, no alert, approval blocked until a person corrects it (see [§ The incident catalogue](#the-incident-catalogue))
- **An executable incident catalogue.** Twelve real water-and-health incidents — Oder 2022, Milwaukee 1993, Walkerton 2000, Toledo 2014, Havelock North 2016, Flint 2014, Baia Mare 2000, Ajka 2010, Mar Menor 2021, Akerselva 2011, Seine 2024, Brixham 2024 — replayed as fixtures with their expected coding, refusal, and audience-routing outcomes enforced in CI ([incidents.md](docs/incidents.md), [test_incidents.py](tests/test_incidents.py), [simulate.py](scripts/simulate.py))
- **A biodiversity crosswalk that fills a gap the official IG left open.** The OAH code system has ten biological indicators and no taxonomy at all. This suggests a GBIF Backbone taxon for the organism named in a source label, keyless, reviewer-gated, published as an `Observation.component` that validates against the OAH profile with zero errors ([gbif.py](src/aquafhir/gbif.py); see [§ The biodiversity crosswalk](#the-biodiversity-crosswalk))
- Docker Compose stack: bridge + HAPI + PostgreSQL, pinned image versions

**Pending — tracked honestly rather than hidden:**

- **Environmental LOINC coverage is genuinely incomplete.** LOINC has exact terms for pH, chloride, and conductivity in water, but *none* for dissolved oxygen or water temperature in an environmental specimen, and nothing for a satellite-derived index like NDCI. The crosswalk returns nothing for those rather than offering a plausible-looking wrong code, which is why the OAH IG's temporary code system exists at all. Submitting the gaps to LOINC is the real fix.
- **Crosswalk provenance detail.** Approval today hash-chains only a boolean (`reviewer_attached_secondary_coding`). A production version should hash-chain the exact query/response the same way Gemini calls already are (prompt hash, response hash, latency) — tracked in [production-checklist.md](docs/production-checklist.md).
- **SNOMED CT candidates are unvalidated.** LOINC results are checked against the published term table; SNOMED concept ids are passed through, because this repository deliberately does not vendor the SNOMED release.
- **The One Health loop is only half published.** The OAH IG already defines the human leg (`gastrointestinal`, `campylobacter`, `cryptosporidium`, `hospitalization-*`) and the animal leg (`fish`, `amphibians`, `ticks`), plus a second profile for them — `observation-health-measure-oah`. This bridge publishes only the environmental leg. Publishing the human counterpart against the same `Location` is the single highest-value next addition ([incidents.md](docs/incidents.md#terminology-gaps-this-catalogue-found)).
- **Coded-value indicators are not supported.** `foam` (Foam/colour/smell), `macrophytes`, and `macroinvertebreates` are `CodeableConcept` observations, not quantities, and this bridge publishes `valueQuantity` only. They are the backbone of citizen-science stream assessment.
- **Live Earth-observation and agency connectors.** Still replaying transparent synthetic CSVs; a real Copernicus Sentinel-2 or national river-monitoring feed is the next highest-value connector (see [§ Judging-criteria mapping](#judging-criteria-mapping), Scale row).
- Everything else listed in [§ Implemented versus production work](#implemented-versus-production-work).

## Hackathon alignment

Built for the **IEEE OneAquaHealth Global Hackathon 2026**, an EU Horizon Europe–funded event that connects urban aquatic ecosystem health to human, animal, and environmental well-being through the One Health approach.

- **Track:** Track 7 — Digital Health Standards ("Enable interoperability across systems"; challenge: "Fragmented data and lack of standards"; expected tooling: "FHIR models, AI agents, and integration frameworks").
- **Track statement:** AquaFHIR Bridge *is* the interoperability layer the track asks for — it takes fragmented agency, citizen-science, and Earth-observation readings and normalizes them into the project's own [OneAquaHealth FHIR IG](https://build.fhir.org/ig/hl7-eu/oah/), then routes standards-based alerts to human-health, veterinary, and water-authority consumers.
- **Hackathon period:** September 16–30, 2026. **Judging:** October 1–15, 2026. **Winners announced:** October 24, 2026 at the IEEE iGET Conference. **Registration closes:** August 31, 2026. (Some third-party listings show slightly different dates — treat the official OneAquaHealth hackathon page as authoritative.)

### Judging-criteria mapping

| Criterion | How this repository addresses it |
|---|---|
| **Impact & Alignment with the OneAquaHealth mission** | Every environmental reading is normalized into the *same* FHIR resource model the OneAquaHealth project already publishes, and a crossed threshold routes an alert to human-health, veterinary, *and* water-authority audiences in one step — the ecosystem→health link is the product, not a bolt-on chart. The claim is tested against twelve real incidents rather than asserted: the [incident catalogue](docs/incidents.md) includes an urban stream in an OAH pilot city (Oslo's Akerselva), a citizen-signal-first outbreak (Brixham 2024), and an animal→water→human pathway routed to veterinary and public-health audiences from one reading (Havelock North 2016). |
| **Innovation & Creativity** | A working Gemini co-pilot that maps multilingual, abbreviated, and free-text source data onto OAH terminology under enum-constrained grounding, and drafts audience-specific advisories — with a hash-chained ledger recording the model id and the exact prompt hash behind every proposal (§ [The Gemini co-pilot](#the-gemini-co-pilot)). Layered on top, a **terminology crosswalk** finds the real LOINC code for the same curated OAH concept — searching the published LOINC table scoped to environmental specimens, which surfaces `9481-3` pH of Water where a generic clinical UMLS search returns *Peliosis hepatis* — so a reviewer can publish both the project-specific code and a standard one a downstream EHR already understands (§ [The terminology crosswalk](#the-terminology-crosswalk)). FHIR-for-environment bridges with reviewer gating are rare; ones that also close the "temporary code system → real terminology" gap are rarer still. On top of that, a **biodiversity crosswalk** names the organism a source label mentions, filling a white space the official IG itself leaves open: it defines ten biological indicators and binds none of them to a taxonomy (§ [The biodiversity crosswalk](#the-biodiversity-crosswalk)). |
| **Architecture** | HAPI FHIR R4 loaded with the real `hl7.eu.fhir.oah` package, R4 rest-hook Subscriptions, a versioned/unit-aware alert policy, a swappable `CodingProposer` contract the model plugs into without touching the FHIR or alerting layers, a two-source `TerminologyCrosswalk` that validates every LOINC candidate against the published term table and degrades source-by-source, and documented sequence diagrams (see [architecture.md](docs/architecture.md)). 332 tests, all offline, including a malformed-input suite covering every shape a FHIR server or a source can push at it, and **an executable incident catalogue** — twelve real water-and-health incidents replayed as fixtures with their expected coding, refusal, and audience-routing outcomes enforced in CI ([incidents.md](docs/incidents.md)). |
| **UX** | A dependency-free review console built like a work-management tool, not a dashboard of charts. Every proposal is a card that reads *as received → OneAquaHealth FHIR*; opening it shows the model's quoted evidence, the competing candidates, a visible flag when the AI disagrees with the curated rules, the LOINC/SNOMED crosswalk, the exact FHIR Observation once approved, and its own hash-chain history. Reviewers can drag a card to a decision, bulk-approve inspected rows, or use ⌘K and keyboard shortcuts. Incidents carry one-click advisory drafting per audience; the audit log is a real table with verification. The reviewer sees what the model saw. See the [demo script](docs/demo-script.md). |
| **Scale** | Config-driven terminology ([coding-rules.yaml](config/coding-rules.yaml)) and policy ([thresholds.yaml](config/thresholds.yaml)) — adding an indicator is a YAML edit, and the model's vocabulary widens with it automatically. `auto` assist mode spends a model call only where rules are weak, so cost scales with novelty rather than volume. Gap analysis in § [Implemented versus production work](#implemented-versus-production-work). |

### Submission checklist

| Required item | Where it lives |
|---|---|
| Track alignment statement | This section |
| Project description (problem, solution, users, impact) | This README's opening summary + [Real-world anchor](#real-world-anchor-the-2022-oder-river-disaster) |
| 3–5 minute demo video | Script in [demo-script.md](docs/demo-script.md); record against the Docker stack |
| Public code repository with documentation | This repository |
| Working prototype / proof-of-concept | `docker compose up --build` (§ [Quick start with Docker](#quick-start-with-docker)) |

## What the system proves

The end-to-end slice is intentionally narrow:

1. Accept an agency, citizen, or satellite reading — structured, or as a free-text bulletin — without discarding the original label or source.
2. Propose an OAH terminology code and normalize the unit to UCUM, using curated rules first and a grounded Gemini call only where those rules are weak.
3. Require a person to approve or reject the proposal. No confidence score, and no model, bypasses review.
4. Build and validate an OAH `Location` and environmental `Observation` against their profiles.
5. Optionally suggest a real LOINC/SNOMED CT code for the proposal's OAH concept via UMLS; a reviewer may attach one, never the other way around.
6. Publish those resources — the OAH coding, and the reviewer-attached secondary coding if any — plus the source `Organization` as one HAPI FHIR R4 transaction, or return them in dry-run mode.
7. Evaluate a versioned demonstration threshold policy — deterministically, with no model involvement — and route any alert to human-health, veterinary, and/or water-authority audiences.
8. Draft an audience-specific advisory for a routed alert, marked `draft` and disclaimed, from the facts the policy engine already established.
9. Hash-chain every proposal, decision, alert, model call, and terminology-crosswalk attachment — including the prompt hash and model id where applicable — so later modification is detectable.

The included Oder replay is synthetic demonstration data shaped around the 2022 incident narrative. It is not a scientifically reconstructed incident dataset, and the sample thresholds are not WFD/EQS limits.

### Real-world anchor: the 2022 Oder River disaster

In July–August 2022, a *Prymnesium parvum* ("golden algae") bloom — triggered by elevated salinity (linked to industrial discharges) combined with heat and low flow — killed fish and molluscs across the Poland–Germany border stretch of the Oder river. Reported figures vary by source and method: the Leibniz Institute of Freshwater Ecology and Inland Fisheries (IGB) put the toll at up to 1,000 tonnes of fish, mussels, and snails; a European Commission report cites roughly 360 tonnes as the figure scientifically confirmed; and Poland's own government reporting recorded 249 metric tonnes of dead fish physically collected within its territory between late July and 12 September 2022. IGB scientists measured algal concentrations reaching around 100,000 cells per millilitre in the river at the height of the bloom.

The bloom's spread was already visible in Copernicus Sentinel-2 imagery, and salinity/conductivity readings were already measurably elevated — but that evidence sat in fragmented Polish and German agency systems and reached downstream communities and cross-border authorities too slowly to change the outcome. AquaFHIR Bridge's Oder replay demonstrates, with clearly labeled synthetic data, how normalizing that same class of signal (conductivity, an NDCI-style bloom index, dissolved oxygen) into shared FHIR resources with a threshold policy and cross-audience Subscription alerting could plausibly compress that delay. This is presented as a *plausible earlier-warning* case, not a claim that the tool would have prevented the fish kill — the underlying pollution and ecological trigger are a policy and enforcement problem the data layer alone does not solve.

## Architecture

```mermaid
flowchart LR
    A[Agency CSV / citizen app / Sentinel index] --> B[Ingestion API]
    T[Free-text bulletin or field note] --> X[Gemini extractor]
    X -->|literal readings only| B
    B --> C[Curated coding agent]
    C -->|weak match or unknown unit| Y[Gemini coding co-pilot]
    Y -->|catalog code + unit name| C
    C -->|pending proposal| D[Human review UI]
    D -->|suggest crosswalk| W[UMLS UTS search]
    W -->|candidate LOINC/SNOMED| D
    D -->|approve, optional secondary coding| E[OAH FHIR bundle builder]
    D -->|reject| P[(Hash-chained audit)]
    E --> F[(HAPI FHIR R4)]
    F -->|R4 rest-hook Subscription| G[Policy engine]
    E -->|demo fast path| G
    G --> H[Human health inbox]
    G --> I[Veterinary inbox]
    G --> J[Water authority inbox]
    G --> Z[Gemini advisory drafter]
    Z -->|draft, disclaimed| H
    Z --> I
    Z --> J
    B --> P
    D --> P
    G --> P
    Y --> P
    Z --> P
    W --> P
```

Gemini appears in three places and in none of them can it publish: it feeds the *proposal*
queue, it feeds the *draft* advisory queue, and every call it makes is hash-chained with
its model id and prompt hash. UMLS appears in exactly one place and cannot publish either:
it only ever offers the review UI a candidate second coding, which a reviewer must choose
to carry into the bundle builder. The policy engine and the FHIR builder never see a model
or a UMLS response directly — only what a human already decided to approve.

The prototype keeps its review queue, alerts, and provenance in SQLite. HAPI uses PostgreSQL. That separation makes the boundary clear: FHIR is the interoperable record; workflow state is application state. See [architecture.md](docs/architecture.md) for component and sequence details.

## Quick start with Docker

Requirements: Docker Engine/Desktop with Compose v2.

```bash
cp .env.example .env
# Add your keys:
#   GEMINI_API_KEY=...   (free at https://aistudio.google.com/apikey)
#   UMLS_API_KEY=...     (free at https://uts.nlm.nih.gov/uts/profile, after NLM approves
#                          your UMLS license -- typically a 3-business-day review)
docker compose up --build
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`.

Both keys are optional and independent. Without `GEMINI_API_KEY` the bridge starts in
deterministic-only mode: the header badge reads `AI off`, curated coding and the full
FHIR/alerting pipeline work normally, and the AI endpoints return `503` with an explanation
rather than failing obscurely. Without `UMLS_API_KEY` the terminology-crosswalk badge reads
`UMLS off`, the "Suggest LOINC/SNOMED" action disappears from the review UI, and
`/api/v1/terminology/*` returns the same kind of explanatory `503` — approvals simply carry
one coding instead of two. Compose reads `.env` for substitution and passes both keys through
as environment variables; `.dockerignore` keeps `.env` out of the image so neither key is
baked into a layer.

Open:

- Review console: <http://localhost:8000> (Board, Queue, Incidents, Advisories, Reports, Audit log, Policy & catalog, Integrations)
- OpenAPI: <http://localhost:8000/docs>
- HAPI FHIR UI: <http://localhost:8080>
- HAPI FHIR base: <http://localhost:8080/fhir>

HAPI can take a minute or two on its first start while PostgreSQL initializes and the `hl7.eu.fhir.oah#0.1.0-ci-build` package is installed. The Compose image is pinned to HAPI `v8.10.0-3`; pin it by digest as well before a controlled deployment.

Set your reviewer identity from the avatar in the top right, then on the **Board** press **Load Oder replay**. Open a card to inspect the proposal, press **Suggest LOINC / SNOMED** on its Crosswalk tab, and approve it, or drag cards straight to the Approved column, or use **Approve all pending**. Three of the five readings cross the demonstration policy and appear under **Incidents**; open one and press **Draft · Veterinary** to see Gemini write the advisory. The top bar shows the FHIR write mode (`enabled` vs `dry-run`), the AI model (`gemini-3.1-pro-preview` vs `AI off`), and the crosswalk sources (`loinc-table+umls`); each pill opens **Integrations**, which lists every external dependency with a masked credential fingerprint. Press `?` for keyboard shortcuts and `⌘K` for the command palette.

With `UMLS_API_KEY` set, a pending proposal also shows **Suggest LOINC/SNOMED (UMLS)**. Click it, then click a candidate chip to mark it "will attach on approval" — the next **Approve** on that card publishes an Observation with two codings: the curated OAH one and the reviewer-picked LOINC/SNOMED CT one.

To submit the harder case, use the structured form's default — the German label
`Leitfähigkeit` with unit `uS/cm`. Curated alias matching scores it at 0.31 and refuses;
the co-pilot resolves it and the reviewer still decides.

## Run the bridge locally

This path is faster for development and defaults to safe FHIR dry-run mode.

```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
# bash/zsh:  source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env`:

```dotenv
DATABASE_PATH=aquafhir.db
FHIR_BASE_URL=http://localhost:8080/fhir
FHIR_WRITE_ENABLED=false
GEMINI_API_KEY=your-key-or-leave-empty
GEMINI_ASSIST_MODE=auto
UMLS_API_KEY=your-key-or-leave-empty
```

Then start and test:

```bash
uvicorn aquafhir.main:app --reload
pytest          # 332 tests, fully offline — no keys needed, no network touched
ruff check .
```

The suite never calls Gemini or UMLS. `tests/fakes.py` replaces only the HTTP hop for each,
so the schema construction, JSON parsing, hashing, and every guardrail still run for real.

## Try the API

Check what the AI layer is allowed to do:

```bash
curl http://localhost:8000/api/v1/ai/status
```

Create a review proposal. `Leitfähigkeit` is the interesting case: curated alias matching
scores it at 0.31 and refuses, so `auto` mode consults Gemini.

```bash
curl -X POST http://localhost:8000/api/v1/proposals \
  -H "Content-Type: application/json" \
  -d '{
    "source_id":"pl-agency-001",
    "source_type":"agency",
    "parameter":"Leitfähigkeit",
    "value":2350,
    "unit":"uS/cm",
    "observed_at":"2022-07-27T08:00:00Z",
    "site_code":"oder-kostrzyn",
    "site_name":"Oder at Kostrzyn",
    "latitude":52.5887,
    "longitude":14.6495
  }'
```

The response carries `proposer: "gemini-assisted"`, the OAH code, `2.35 mS/cm` computed
from the reviewed factor, and an `ai` block with the model id and prompt hash.

Extract readings from an unstructured bulletin instead:

```bash
curl -X POST http://localhost:8000/api/v1/intake \
  -H "Content-Type: application/json" \
  -d '{
    "text":"WIOŚ Szczecin, 27.07.2022 08:00 UTC — Oder at Kostrzyn. Leitfähigkeit 2350 uS/cm. Gelöster Sauerstoff 3,6 mg/L. Angler melden tote Fische — keine Messung.",
    "source_id":"wios-szczecin-bulletin",
    "default_site_code":"oder-kostrzyn",
    "default_site_name":"Oder at Kostrzyn"
  }'
```

Both paths produce `pending` proposals and warnings — never a published resource. Load the
whole synthetic Oder timeline the same way:

```bash
curl -X POST http://localhost:8000/api/v1/replay
```

The result remains `pending`, even for an exact match and even when the model is confident.
Approve it with the returned ID:

```bash
curl -X POST http://localhost:8000/api/v1/proposals/PROPOSAL_ID/approve \
  -H "Content-Type: application/json" \
  -d '{"reviewer":"reviewer@example.org"}'
```

Inspect alerts, draft an advisory for one audience, and verify the audit chain:

```bash
curl http://localhost:8000/api/v1/alerts
curl -X POST "http://localhost:8000/api/v1/alerts/ALERT_ID/briefings?audience=veterinary"
curl -X POST http://localhost:8000/api/v1/ai/situation-report
curl http://localhost:8000/api/v1/provenance/verify
```

Approval is resolved on the server. Ask it what a given code would publish before
deciding:

```bash
curl "http://localhost:8000/api/v1/proposals/PROPOSAL_ID/normalization?code=electrical-conductivity"
# -> {"status":"ok","formula":"2444 uS/cm × 0.001 = 2.444 mS/cm","normalized_value":2.444, ...}
```

If the source label cannot be coded but the source unit uniquely belongs to one
reviewed rule, the proposal keeps `coding: null` and adds a `reviewed-unit`
candidate. The console shows that candidate in the drawer and preselects it in
the approval dialog, where the reviewer can still change the code before signing
off.

A reviewer who disagrees with the model selects a different catalog code. Only the
`code` is read; the published system and display text come from the catalog, and the
quantity is re-derived for the code actually chosen:

```bash
curl -X POST http://localhost:8000/api/v1/proposals/PROPOSAL_ID/approve \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer":"reviewer@example.org",
    "coding":{"system":"ignored","code":"chloride","display":"ignored"}
  }'
```

Replacing the *number* is a separate, heavier action. It requires a written reason,
and it is still held to the selected rule's accepted units and plausible range:

```bash
curl -X POST http://localhost:8000/api/v1/proposals/PROPOSAL_ID/approve \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer":"reviewer@example.org",
    "normalized_value":120.0,
    "normalized_unit":"mg/L",
    "correction_reason":"Probe recalibrated after the reading was filed"
  }'
```

An unknown code, a unit the rule does not accept, or a value outside its plausible
range is a `422`: nothing is published and no incident is raised.

The override is recorded in the provenance payload alongside the model's prompt hash, so
the disagreement itself is auditable.

The approval dialog recognizes common source spellings such as `µS/cm`, `°C`,
`µg/L`, `pH`, and `CFU / 100 mL`, while preserving the original record. Reviewed
conversions and spelling aliases have a green label. The catalog defines this
project's accepted target units; it is not an exhaustive list of FHIR/UCUM units.

For unresolved units, the dialog requests
`POST /api/v1/proposals/{id}/unit-suggestion?code=CODE`. Gemini can interpret an
unfamiliar spelling or suggest a conversion factor and offset to an existing
accepted target. The server computes the candidate value and checks its range.
Suggestions are amber and labeled **Gemini suggestion · Uncited**: this integration
does not search the internet or verify sources. A valid target unit does not
establish that an AI-suggested conversion is correct.

**Use suggestion as expert correction** fills editable value, unit, and reason
fields. The reviewer can change them, cancel, or reject the proposal. Approval
requires a complete correction and rechecks the selected indicator's accepted
units and range. The request includes `unit_suggestion_id`; provenance records
the original suggestion, model attribution, and final approved quantity. An AI
unit interpretation made during intake follows the same explicit review gate.
Suggestions are reused per proposal and selected code; failures can be retried.
With Gemini disabled or unavailable, reviewed conversions and manual corrections
remain available. No database migration or new dependency is required.

With `UMLS_API_KEY` set, ask for a real-terminology crosswalk on a pending proposal, then
carry the pick into approval as `secondary_coding`:

```bash
curl "http://localhost:8000/api/v1/proposals/PROPOSAL_ID/terminology-suggestions"

curl -X POST http://localhost:8000/api/v1/proposals/PROPOSAL_ID/approve \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer":"reviewer@example.org",
    "secondary_coding":{"system":"http://loinc.org","code":"11556-8","display":"Dissolved oxygen"}
  }'
```

The resulting Observation carries both codings in `code.coding`: the curated OAH one first,
the reviewer-attached LOINC/SNOMED CT one second. Without a key, the suggestions endpoint
returns `503` and approval works exactly as before, with one coding.

See [api.md](docs/api.md) for every endpoint and error contract.

## FHIR conformance choices

The current OAH continuous build is based on FHIR 4.0.1. Its environmental Observation profile requires:

- `status = final`;
- a code drawn preferably from the OAH non-health indicator value set;
- a `subject` referencing an OAH `Location`;
- an `effective[x]` time;
- at least one `performer`;
- a quantity or coded value.

The builder therefore creates all required surrounding resources, uses `http://unitsofmeasure.org` for quantity codes, and places this canonical profile URL in `Observation.meta.profile`:

```text
http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-indicators-oah
```

The OAH IG's temporary project code system publishes **286 concepts**, spanning the environmental leg (`electrical-conductivity`, `dissolved-oxygen`, `waterTemperature`, `ndci`, `nitrate`, `ammonium`, `tss`, `coliforms`, the dissolved-metals series), the animal leg (`fish`, `amphibians`, `birds`, `ticks`), and the human leg (`gastrointestinal`, `campylobacter`, `cryptosporidium`, `hospitalization-*`). The curated catalog uses 19 of them, every one verified against the published code system and guarded by a test that fails if an unpublished code is ever introduced. Concepts the IG does not define — turbidity, free chlorine residual, cyanide, microcystin, enterococci — are refused rather than mapped to a neighbour; the resulting gap list is in [incidents.md](docs/incidents.md#terminology-gaps-this-catalogue-found).

A second coding is now supported, but only after terminology review by a person: the crosswalk (§ [The terminology crosswalk](#the-terminology-crosswalk)) suggests a real LOINC/SNOMED CT candidate for the curated code's display text, and `Observation.code.coding` only ever gains a second entry when a reviewer supplies `ReviewDecision.secondary_coding` at approval time — never automatically.

FHIR R4 Subscription filtering is search-based, not threshold-expression based. The supplied Subscription watches final Observations and sends an empty rest-hook notification; the bridge then queries HAPI for resources updated since its durable cursor and applies the versioned numerical policy. The approval pipeline also evaluates the same policy immediately to keep the demo deterministic.

## The Gemini co-pilot

Real environmental feeds do not say `electrical conductivity`. They say `EC_uScm`,
`Leitfähigkeit`, `przewodność`, `cond. (25C)` — or they say it in a paragraph of a
voivodeship bulletin. Alias similarity fails on all of those. A language model does not.
But a language model must never be trusted with the parts that decide what gets published.

### The split, enforced in code

| Gemini may decide | Deterministic code decides |
|---|---|
| Which catalog code a messy label denotes | The code's display text, read from the YAML |
| Which known unit string a source unit denotes | Reviewed conversion arithmetic and validation |
| An uncited factor/offset when no reviewed conversion exists | Candidate arithmetic; publication requires an explicit expert correction |
| Which measurements a free-text note literally contains | Whether review is required — always yes |
| How to phrase an advisory for one audience | Whether an alert fires, at what severity, to whom |
| | What is written to FHIR |

Three guardrails hold it:

1. **Closed vocabulary.** The curated catalog is injected into the prompt, the
   `responseSchema` constrains `code` to an enum of exactly those codes plus `NO_MATCH`,
   and [`coding_llm.py`](src/aquafhir/coding_llm.py) re-checks the returned code against
   the catalog anyway. A schema is a request, not a proof. An out-of-catalog code is
   discarded and the curated proposal stands.
2. **Explicit unit review.** Known-unit interpretations use reviewed YAML factors;
   model-suggested factors and offsets are confined to uncited suggestions in
   `unit_assist.py`. The server computes candidate values. Every AI unit suggestion
   needs explicit acceptance as an expert correction before publication. Ordinary
   approval re-derives the quantity from the original reading and reviewed rules.
3. **Capped confidence.** Any AI-influenced proposal is capped at
   `GEMINI_CONFIDENCE_CEILING` (0.95). A disagreement with the curated match, or a
   model-raised expert-review flag, caps it at 0.80 and surfaces a warning on the card.
   No value publishes anything; `requires_review` is unconditional.

### Wired features

| Feature | Endpoint | What the model is allowed to return |
|---|---|---|
| Terminology coding co-pilot | `POST /api/v1/proposals` | One catalog code, one known unit name, evidence, confidence |
| Unit review assistant | `POST /api/v1/proposals/{id}/unit-suggestion?code=CODE` | An uncited unit interpretation or factor/offset for explicit expert correction |
| Unstructured intake | `POST /api/v1/intake` | Measurements literally present in the note, plus warnings |
| Audience advisory drafting | `POST /api/v1/alerts/{id}/briefings` | Prose for one already-decided alert, marked `draft` |
| Grounded situation report | `POST /api/v1/ai/situation-report` | A summary of this bridge's own stored records only |

### Provenance for model calls

Every call records provider, model id, versioned prompt-template id, SHA-256 of the exact
rendered prompt, SHA-256 of the response, latency, the grounded code list, and the model's
quoted evidence. Approval and rejection events carry the prompt hash into the hash chain,
so an auditor can distinguish a prompt-template change from an input change months later.

### Failure is a degradation, not an outage

An unreachable, rate-limited, blocked, truncated, or out-of-catalog response falls back to
the curated proposal with a note in the rationale. A missing key disables the AI features
and leaves the rest untouched. Both paths are covered by tests, and the transport tests
cover 429 retry, 401 non-retry, network error retry, and a model that rejects
`thinkingConfig`.

Prompt templates live in [prompts.py](src/aquafhir/prompts.py). The curated vocabulary is
in [coding-rules.yaml](config/coding-rules.yaml). Demonstration alert rules live separately
in [thresholds.yaml](config/thresholds.yaml), which prevents a terminology edit — or a
model — from silently changing safety policy.

## The biodiversity crosswalk

The OneAquaHealth IG's temporary code system carries biological indicators as
coarse buckets: `fishes`, `diatomes`, `macroinvertebreates`, `macrophytes`,
`amphibians`, `birds`. Ten such codes, and **not one of them is backed by a
taxonomy**. There is no Darwin Core, no GBIF, no ENVO, no NCBI Taxonomy
anywhere in the guide. A reading that says *Prymnesium parvum* loses the
organism the moment it is coded, which for a One Health bus is the part that
matters most: the species is what links the water body to the fish kill to the
human advisory.

This crosswalk closes that gap the same way the LOINC one does. It suggests a
[GBIF Backbone Taxonomy](https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c)
key for the organism named in a source label, and a reviewer attaches it or
ignores it. It needs no key and no registration.

### It reads the source label, not the curated code

The two crosswalks sit on different axes, and getting this wrong makes the
feature useless. The OAH display `fishes` is not a taxon and GBIF refuses it;
the raw source label `Prymnesium parvum cell count` names one exactly. So the
taxon lookup keys on `reading.parameter`, and it deliberately still runs when
the curated catalog could not code the reading at all. That is not an edge
case: a reading the catalog cannot code is precisely where an organism name
most often survives untranslated.

### Unlike a clinical search, GBIF declines cleanly

The [terminology crosswalk](#the-terminology-crosswalk) has to work hard to
stop UMLS offering *Peliosis hepatis* for `pH`. GBIF has the opposite
character, which is what makes it safe to run over raw, uncurated text:

| Source label | GBIF answer |
|---|---|
| `Prymnesium parvum cell count` | `7513065` *Prymnesium parvum* N.Carter, EXACT |
| `dissolved oxygen` | no match |
| `pH` | no match |
| `Leitfähigkeit` | no match |
| `chloride` | no match |

There is one trap, and the client is built around it. A refusal comes back as
`{"matchType": "NONE", "confidence": 100}` — a **full** confidence score
attached to a non-answer. Any implementation that thresholds on `confidence`
accepts every miss. [`gbif.py`](src/aquafhir/gbif.py) therefore decides on
`matchType` alone and treats `confidence` as display metadata, and there is a
test asserting exactly that.

### Where the taxon lands, and why not in `code.coding`

The indicator axis and the organism axis are different things, and the
threshold policy reads `Observation.code.coding[0]`. Putting a taxon there
would let a biodiversity suggestion reach the alerting path. So the taxon is
published as an `Observation.component`:

```json
"code":      { "coding": [{ "code": "fishes" }] },
"valueQuantity": { "value": 214, "code": "{count}" },
"component": [{
  "code":  { "coding": [{ "system": "http://loinc.org", "code": "41852-5" }] },
  "valueCodeableConcept": {
    "coding": [{ "system": "https://doi.org/10.15468/39omei", "code": "8215487",
                 "display": "Salmo trutta Linnaeus, 1758" }] }
}]
```

The component code is **not** a repeat of the OAH indicator. The first
implementation did that and HAPI's validator rejected it under FHIR invariant
`obs-7`: *"If Observation.code is the same as an Observation.component.code
then the value element associated with the code SHALL NOT be present."* It is
now LOINC `41852-5` *Microorganism or agent identified in Specimen* — real,
ACTIVE, specimen-agnostic, nominal scale, and checked against the vendored
LOINC table by a test rather than taken on trust. The corrected resource
validates against `observation-indicators-oah` with **zero errors** and is
accepted by HAPI.

### The system URI is a deliberate choice, not a standard

There is no HL7-registered code system URI for GBIF taxon keys. This project
publishes the DOI of the GBIF Backbone Taxonomy,
`https://doi.org/10.15468/39omei`, because it identifies the exact checklist a
key belongs to. That is a project decision pending registration, recorded here
in the same register as the OAH temporary code system it sits beside.

### What it still cannot do

Naming the organism does not create an indicator to hang it on. The Oder
replay's *Prymnesium parvum* reading resolves to GBIF `7513065` at 99%
confidence and **still cannot be published**, because the OAH code system has
no concept for phytoplankton cell density. The crosswalk surfaces the
identification and the gap in the same breath, which is the honest result and
one more entry for [the gap list](docs/incidents.md#terminology-gaps-this-catalogue-found).

## The terminology crosswalk

The OAH IG's environmental concepts live in a temporary project code system
(`http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu`) — reasonable for a
continuous-build IG, but a downstream hospital or public-health system will not have that
code system loaded. It will have LOINC and SNOMED CT. The crosswalk closes that gap by
offering the real-world code for a curated OAH concept, for a reviewer to accept or ignore.

### Why a plain UMLS search is not enough

The obvious implementation — ask the UMLS Metathesaurus for the curated code's display text —
does not work, and it fails in two distinct ways that are worth stating because both are
easy to ship without noticing.

**It returns codes that are not LOINC codes.** A `sabs=LNC` search also returns LOINC *Parts*
(`LP14752-7`) and Metathesaurus-internal identifiers (`MTHU001949`) minted where a concept has
no source-asserted code. Neither exists in the published LOINC table, so publishing one under
`system = http://loinc.org` asserts a code that is not real. A reviewer cannot be expected to
know that by sight, so [`loinc_table.py`](src/aquafhir/loinc_table.py) checks every LOINC
candidate against the published term list and drops the rest.

**It ranks clinically.** UMLS has no idea the subject is a river. Asking it for `pH` returns
*pH measurement* and *Peliosis hepatis* well above anything about water; `Water temperature`
returns *Checking bath water temperature*; `Electrical conductivity` returns *Skin electrical
conductivity meter*. Every one of those would be wrong to publish.

Meanwhile LOINC itself already carries the right answers. Scoping the search to environmental
specimens finds them immediately:

| OAH concept | LOINC code found locally | What plain UMLS search ranked first |
|---|---|---|
| `ph` | **9481-3** — pH of Water | *Peliosis hepatis* |
| `chloride` | **12530-2** — Chloride [Moles/volume] in Water | *Sodium chloride* |
| `electrical-conductivity` | **87444-6** — Electron [Electrical Conductivity] of Water | *Skin electrical conductivity meter* |
| `dissolved-oxygen` | *(none — genuine gap)* | *Dissolved oxygen meter, battery-powered* |
| `waterTemperature` | *(none — genuine gap)* | *Checking bath water temperature* |

So the crosswalk searches the committed LOINC table first and uses UMLS to top up the
remainder — chiefly SNOMED CT, which this repository does not vendor. The local path needs no
key and no network.

The two blank rows are not a bug to paper over. Environmental LOINC genuinely has no term for
dissolved oxygen or water temperature in water, and none for a satellite index like NDCI. The
crosswalk returns nothing rather than a plausible-looking wrong code — which is precisely why
the OAH IG needs a temporary code system in the first place.

### Authentication, done the way NLM actually documents it

The UMLS Terminology Services (UTS) REST API authenticates with a single `apiKey` query
parameter issued from a UTS profile
(<https://documentation.uts.nlm.nih.gov/rest/authentication.html>) — the older
ticket-granting-ticket flow is deprecated, and there is **no OAuth2 client_id/client_secret
grant** for this API as of 2026. [`umls.py`](src/aquafhir/umls.py) implements exactly that
scheme. A client_id/client_secret pair from an app registration made while *requesting* the
license will not authenticate against `uts-ws.nlm.nih.gov`; use the API key from your UTS
profile.

### The split, enforced in code

| The crosswalk may suggest | Deterministic code / a human decides |
|---|---|
| Which real LOINC/SNOMED CT concepts match this OAH code's display text | Whether that suggestion is ever attached to a proposal (`ReviewDecision.secondary_coding`) |
| A ranked list of candidates, scored only by name similarity | The published OAH coding, the quantity, and whether the alert fires — none of which the crosswalk can see or touch |

Guardrails mirror `coding_llm.py`'s posture:

1. **Codes are validated, not trusted.** Every LOINC candidate must appear in the published
   term table. `UMLS_VOCABULARIES` (default `LNC,SNOMEDCT_US`) is sent as the UTS `sabs`
   filter *and* re-checked against every result — a request is not a proof. Only `ACTIVE`
   terms are suggested, though a deprecated code still validates, because it was legitimately
   published.
2. **Specimen scope is an allowlist.** Local search covers exactly `Water`, `Air`, `Envir`,
   and `Environmental specimen`. Not a substring test — LOINC's `Airway adaptor` and
   `Airway.proximal` are respiratory-device systems, not air quality.
3. **Suggestion only, never selection.** `suggest_terminology()` is read-only. Nothing is
   written to a proposal, let alone to FHIR, until a reviewer supplies a `Coding` explicitly.
4. **Independent failure domains.** A UMLS outage degrades to the local LOINC results. A
   UMLS failure with *no* local results is surfaced as a `502` rather than an empty list, so a
   reviewer is never told "no match" when the truth is "the lookup broke". A missing LOINC
   table disables local search and validation with a warning, and never blocks startup.

### Two wired surfaces

| Feature | Endpoint | What it returns |
|---|---|---|
| Terminology status | `GET /api/v1/terminology/status` | Which sources are live (`loinc-table`, `umls`) and which vocabularies are searched |
| Crosswalk suggestions | `GET /api/v1/proposals/{id}/terminology-suggestions` | Up to 5 candidate `TerminologyMatch` objects (`system`, `code`, `display`, `vocabulary`, `score`), local environmental LOINC first |

`ReviewDecision.secondary_coding` carries a chosen candidate into `POST
.../proposals/{id}/approve`; `build_resources()` in [fhir.py](src/aquafhir/fhir.py) appends it
as a second entry in `Observation.code.coding`, and the approval provenance entry records
`reviewer_attached_secondary_coding: true`.

## The incident catalogue

A prototype that only replays its own happy path proves very little. So the pipeline is
driven against **twelve real water-and-health incidents**, reconstructed as fixtures, with
their expected outcome written down and enforced in CI.

| Incident | What it exercises |
|---|---|
| **Oder River fish kill** (PL/DE, 2022) | Cross-border latency; `Leitfähigkeit` and `chlorki` defeating alias matching; µS/cm → mS/cm |
| **Milwaukee cryptosporidiosis** (US, 1993) | A ten-year turbidity baseline breached and not acted on — and turbidity having no OAH code |
| **Walkerton *E. coli*** (CA, 2000) | Falsified operating records → the hash chain; two spellings of one unit |
| **Toledo "do not drink"** (US, 2014) | Satellite bloom indices crossing a day before the advisory; microcystin gap |
| **Havelock North campylobacteriosis** (NZ, 2016) | The One Health pathway: one reading routed to veterinary *and* public health |
| **Flint drinking-water crisis** (US, 2014–15) | Two high lead samples excluded from a regulatory round → the tamper drill |
| **Baia Mare cyanide spill** (RO/HU/RS, 2000) | A plume across three countries — and the contaminant having no OAH code at all |
| **Ajka red-mud spill** (HU, 2010) | pH 13 caustic release, a `130.0` decimal typo blocked, downstream dilution |
| **Mar Menor anoxic fish kill** (ES, 2021) | The full nutrient→heat→bloom→anoxia chain; a global threshold failing on a saline lagoon |
| **Akerselva chlorine release** (NO, 2011) | An urban stream in an **OAH pilot city**; upstream normal, downstream critical |
| **Seine bathing water** (FR, 2024) | Two sources, same site, same instant, MPN vs CFU — refused rather than converted |
| **Brixham cryptosporidiosis** (UK, 2024) | Citizen illness reports preceding the laboratory result |

Plus a thirteenth synthetic fixture of deliberate abuse cases: sensor faults, threshold
boundaries, nonsense units, and unknown indicators.

```bash
pytest tests/test_incidents.py -q     # 84 assertions, offline, no keys, ~0.1s

uvicorn aquafhir.main:app --reload    # terminal 1
python scripts/simulate.py            # terminal 2 — every scenario over real HTTP
```

The harness ingests each fixture, approves what is approvable, **rejects what is not with a
written reason**, collects the alerts, and verifies the hash chain. It exits non-zero when a
scenario stops matching the document, so it doubles as a release gate:

```
Summary
  scenarios      13/13 matched the documented outcome
  alerts raised  46
  approved       67
  refused        22
  audit chain    VALID over 224 entries
```

Two results are worth reading the catalogue for. **The refusals are the point:** free
chlorine residual — the single most important operational indicator in drinking-water
treatment — appears in *five* of the twelve incidents and has no code in the OAH IG, so the
bridge refuses it five times rather than mapping it to a neighbour. That produces an
exportable list of gaps to submit to the IG and to LOINC, which is a more useful Track 7
output than a chart. And **building the catalogue found a real defect:** a dissolved-oxygen
probe reporting a physically impossible `-5.0 mg/L` used to raise a *critical* alert to the
veterinary and water-authority audiences at 0.99 confidence. Reviewed plausible ranges now
withhold the number instead.

Full write-ups, sources for every incident, the edge-case matrix, and an explicit honesty
statement are in **[docs/incidents.md](docs/incidents.md)**.

## Repository map

```text
.
├── config/                    # reviewed terminology and demo alert policy
├── data/
│   ├── oder-replay.csv        # transparent synthetic Oder replay
│   └── incidents/             # 13 incident fixtures + expectations manifest
├── docs/                      # architecture, API, demo, incidents, production notes
├── scripts/simulate.py        # drives the incident catalogue against a live bridge
├── infra/hapi/               # HAPI R4 + OAH package configuration
├── src/aquafhir/
│   ├── coding.py             # curated proposer + the catalog the model is grounded in
│   ├── coding_llm.py         # Gemini coding co-pilot and its guardrails
│   ├── gemini.py             # minimal Generative Language REST client
│   ├── prompts.py            # versioned prompt templates and response schemas
│   ├── intake.py             # free text -> literal readings -> pending proposals
│   ├── briefing.py           # audience advisories and grounded situation reports
│   ├── loinc_table.py        # published LOINC terms: validation + environmental search
│   ├── umls.py               # minimal UMLS UTS REST client (apiKey auth)
│   ├── gbif.py               # keyless GBIF Backbone client for organism identity
│   ├── terminology.py        # local LOINC first, UMLS top-up, into suggested codings
│   ├── fhir.py               # conformant resources, bundles, subscriptions
│   ├── repository.py         # SQLite workflow state + hash chain
│   ├── service.py            # review-gated orchestration
│   ├── thresholds.py         # unit-aware versioned policy evaluation
│   ├── main.py               # FastAPI surface
│   └── static/               # dependency-free review console: board, queue, incidents, audit, integrations (no build step)
├── tests/                    # coding, AI guardrail, terminology, transport, policy, audit,
│                             # robustness, and incident-catalogue tests
├── compose.yaml              # bridge + HAPI + PostgreSQL
└── Dockerfile
```

## Implemented versus production work

| Capability | In this scaffold | Required before real deployment |
|---|---|---|
| Ingestion | Typed JSON API and transparent replay CSV | Authenticated connectors, source schemas, retries, dead-letter queue |
| Coding | Curated proposals, unit conversion, and a grounded Gemini co-pilot | Labelled model evaluation set, reviewer roles, dual control |
| Terminology crosswalk | UMLS UTS search suggesting real LOINC/SNOMED CT candidates, vocabulary allowlist re-check, reviewer-gated attachment, tested no-key fallback | UMLS license approved (requested; NLM review pending), full query/response provenance hashing to match Gemini's, coverage beyond `LNC`/`SNOMEDCT_US`, cached lookups |
| AI governance | Prompt versioning, prompt/response hashing, capped confidence, catalog re-check, tested no-key fallback | Evaluation metrics published per release, over-trust sampling, prompt-injection tests, quota and circuit breaker, DPIA for the provider transfer |
| FHIR | OAH R4 resources and transaction publication | CI validation with the exact frozen IG package, server capability checks |
| Alerting | Unit-aware YAML policy and audience tags | Approved jurisdiction policy, suppression, escalation, delivery receipts |
| Subscription | R4 rest-hook creation endpoint | Public TLS callback, rotation, replay protection, network allowlist |
| Provenance | Local SHA-256 hash chain | Signed checkpoints/WORM storage and FHIR `Provenance` resources |
| Security | Shared-secret webhook example | OIDC/SMART, RBAC, secret manager, encryption, audit export, threat review |
| Operations | Health endpoint, container stack, CI | Metrics, tracing, backups, SLOs, disaster recovery, runbooks |

The detailed hardening gates are in [production-checklist.md](docs/production-checklist.md).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_PATH` | `aquafhir.db` | Bridge workflow SQLite file |
| `FHIR_BASE_URL` | `http://localhost:8080/fhir` | HAPI R4 endpoint |
| `FHIR_WRITE_ENABLED` | `false` | Enables external FHIR mutation only when explicit |
| `FHIR_TIMEOUT_SECONDS` | `15` | HAPI request timeout |
| `REVIEW_CONFIDENCE_THRESHOLD` | `0.90` | UI/routing signal; never auto-approves |
| `WEBHOOK_SHARED_SECRET` | local demo value | Validates example Subscription callbacks |
| `CODING_RULES_PATH` | `config/coding-rules.yaml` | Curated mapping catalog |
| `THRESHOLDS_PATH` | `config/thresholds.yaml` | Versioned alert policy |
| `REPLAY_DATA_PATH` | `data/oder-replay.csv` | Synthetic replay dataset |
| `GEMINI_API_KEY` | *(empty)* | Enables the co-pilot. Empty is a supported, tested mode |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | Pin explicitly; recorded on every proposal |
| `GEMINI_ASSIST_MODE` | `auto` | `off`, `auto` (only where rules are weak), or `always` |
| `GEMINI_ASSIST_BELOW_CONFIDENCE` | `0.95` | `auto` consults the model below this curated confidence |
| `GEMINI_CONFIDENCE_CEILING` | `0.95` | Hard cap on any AI-influenced confidence |
| `GEMINI_TIMEOUT_SECONDS` | `30` | Per-call timeout |
| `GEMINI_MAX_OUTPUT_TOKENS` | `2048` | Truncated responses are rejected, never half-parsed |
| `GEMINI_MAX_RETRIES` | `2` | Retries only 408/429/5xx and network errors |
| `GEMINI_THINKING_BUDGET` | `0` | `0` for latency; `-1` omits the field for models that reject it |
| `LOINC_TABLE_PATH` | `loinc/LoincTableCore/LoincTableCore.csv` | Published LOINC terms: local environmental search, and validation of UMLS LOINC hits. Missing file disables both with a warning |
| `UMLS_API_KEY` | *(empty)* | Adds UMLS top-up (notably SNOMED CT). Empty is a supported, tested mode — local LOINC search still works. This is a UTS **apiKey**, not an OAuth2 client_id/client_secret |
| `UMLS_API_BASE` | `https://uts-ws.nlm.nih.gov/rest` | UTS REST API base |
| `UMLS_TIMEOUT_SECONDS` | `15` | Per-call timeout |
| `UMLS_MAX_RETRIES` | `2` | Retries only 408/429/5xx and network errors |
| `GBIF_ENABLED` | `true` | Biodiversity crosswalk. No key exists to configure: GBIF read calls are unauthenticated, so this is a plain on/off switch |
| `GBIF_API_BASE` | `https://api.gbif.org/v1` | GBIF REST API base |
| `GBIF_TIMEOUT_SECONDS` | `15` | Per-call timeout |
| `GBIF_MAX_RETRIES` | `2` | Retries only 408/429/5xx and network errors |
| `UMLS_VOCABULARIES` | `LNC,SNOMEDCT_US` | Comma-separated UMLS source-vocabulary abbreviations searched and allowlist-checked |
| `UMLS_CLIENT_ID` / `UMLS_CLIENT_SECRET` | *(empty)* | The client credentials NLM issues during the license request. Shown on the Integrations page for reference (id in full, secret as a fingerprint); never sent to the UTS API, which does not accept them |

## Source standards

- [OneAquaHealth FHIR IG continuous build](https://build.fhir.org/ig/hl7-eu/oah/)
- [OAH artifacts and profiles](https://build.fhir.org/ig/hl7-eu/oah/artifacts.html)
- [OAH package download](https://build.fhir.org/ig/hl7-eu/oah/downloads.html)
- [FHIR R4 Subscription](https://hl7.org/fhir/R4/subscription.html)
- [HAPI FHIR JPA starter](https://github.com/hapifhir/hapi-fhir-jpaserver-starter)
- [UMLS Terminology Services (UTS) REST API authentication](https://documentation.uts.nlm.nih.gov/rest/authentication.html)
- [UMLS UTS Search API reference](https://documentation.uts.nlm.nih.gov/rest/search/)
- [LOINC](https://loinc.org/) · [SNOMED CT (SNOMED International)](https://www.snomed.org/)
- [GBIF Backbone Taxonomy](https://doi.org/10.15468/39omei) · [GBIF API (no key required)](https://techdocs.gbif.org/en/openapi/)

The OAH guide is an unauthorised, changing continuous build. Freeze and archive the exact NPM package used by a release; never assume `0.1.0-ci-build` is immutable merely because the version string stays the same.
