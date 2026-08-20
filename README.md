# AquaFHIR Bridge

AquaFHIR Bridge is a FHIR-native One Health data bus with a **reviewed Gemini co-pilot**. It converts heterogeneous water and Earth-observation readings — including free-text agency bulletins — into reviewed [OneAquaHealth FHIR R4](https://build.fhir.org/ig/hl7-eu/oah/) resources, publishes them to a HAPI FHIR server, evaluates an explicit alert policy, drafts audience-specific advisories, and records each transformation in a tamper-evident audit chain.

The AI is deliberately bounded. Gemini decides *which curated code a messy label means*, *which measurements a note literally contains*, and *how to phrase an advisory*. Deterministic code decides *the published number*, *whether review is required* (always), *whether an alert fires*, and *what is written to FHIR*. Remove the API key and the whole pipeline still runs — that path is tested.

This repository contains only the first concept from the source brief: **the One Health data bus and reviewed coding agent**. It does not include the separate BloomGuard prediction product or StreamSentinel symptom-surveillance concept.

> Status: detailed prototype boilerplate. It is suitable for a hackathon demonstration and engineering handoff, not clinical, veterinary, public-warning, or regulatory production use.

## Hackathon alignment

Built for the **IEEE OneAquaHealth Global Hackathon 2026**, an EU Horizon Europe–funded event that connects urban aquatic ecosystem health to human, animal, and environmental well-being through the One Health approach.

- **Track:** Track 7 — Digital Health Standards ("Enable interoperability across systems"; challenge: "Fragmented data and lack of standards"; expected tooling: "FHIR models, AI agents, and integration frameworks").
- **Track statement:** AquaFHIR Bridge *is* the interoperability layer the track asks for — it takes fragmented agency, citizen-science, and Earth-observation readings and normalizes them into the project's own [OneAquaHealth FHIR IG](https://build.fhir.org/ig/hl7-eu/oah/), then routes standards-based alerts to human-health, veterinary, and water-authority consumers.
- **Hackathon period:** September 16–30, 2026. **Judging:** October 1–15, 2026. **Winners announced:** October 24, 2026 at the IEEE iGET Conference. **Registration closes:** August 31, 2026. (Some third-party listings show slightly different dates — treat the official OneAquaHealth hackathon page as authoritative.)

### Judging-criteria mapping

| Criterion | How this repository addresses it |
|---|---|
| **Impact & Alignment with the OneAquaHealth mission** | Every environmental reading is normalized into the *same* FHIR resource model the OneAquaHealth project already publishes, and a crossed threshold routes an alert to human-health, veterinary, *and* water-authority audiences in one step — the ecosystem→health link is the product, not a bolt-on chart. |
| **Innovation & Creativity** | A working Gemini co-pilot that maps multilingual, abbreviated, and free-text source data onto OAH terminology under enum-constrained grounding, and drafts audience-specific advisories — with a hash-chained ledger recording the model id and the exact prompt hash behind every proposal (§ [The Gemini co-pilot](#the-gemini-co-pilot)). FHIR-for-environment bridges with reviewer gating are rare; ones that can *prove* what the model was asked are rarer. |
| **Architecture** | HAPI FHIR R4 loaded with the real `hl7.eu.fhir.oah` package, R4 rest-hook Subscriptions, a versioned/unit-aware alert policy, a swappable `CodingProposer` contract the model plugs into without touching the FHIR or alerting layers, and documented sequence diagrams (see [architecture.md](docs/architecture.md)). 70 tests, all offline. |
| **UX** | A dependency-free review dashboard shows the proposal queue with the model's quoted evidence, competing candidates, and a visible flag when the AI disagrees with the curated rules — then audience-tagged alert cards with one-click advisory drafting. The reviewer sees what the model saw. See the [demo script](docs/demo-script.md). |
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
5. Publish those resources plus the source `Organization` as one HAPI FHIR R4 transaction, or return them in dry-run mode.
6. Evaluate a versioned demonstration threshold policy — deterministically, with no model involvement — and route any alert to human-health, veterinary, and/or water-authority audiences.
7. Draft an audience-specific advisory for a routed alert, marked `draft` and disclaimed, from the facts the policy engine already established.
8. Hash-chain every proposal, decision, alert, and model call — including the prompt hash and model id — so later modification is detectable.

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
    D -->|approve| E[OAH FHIR bundle builder]
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
```

Gemini appears in three places and in none of them can it publish: it feeds the *proposal*
queue, it feeds the *draft* advisory queue, and every call it makes is hash-chained with
its model id and prompt hash. The policy engine and the FHIR builder never see a model.

The prototype keeps its review queue, alerts, and provenance in SQLite. HAPI uses PostgreSQL. That separation makes the boundary clear: FHIR is the interoperable record; workflow state is application state. See [architecture.md](docs/architecture.md) for component and sequence details.

## Quick start with Docker

Requirements: Docker Engine/Desktop with Compose v2.

```bash
cp .env.example .env
# Add your key: GEMINI_API_KEY=...   (free at https://aistudio.google.com/apikey)
docker compose up --build
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`.

The key is optional. Without it the bridge starts in deterministic-only mode: the header
badge reads `AI off`, curated coding and the full FHIR/alerting pipeline work normally, and
the four AI endpoints return `503` with an explanation rather than failing obscurely.
Compose reads `.env` for substitution and passes the key through as an environment
variable; `.dockerignore` keeps `.env` out of the image so no key is baked into a layer.

Open:

- Dashboard: <http://localhost:8000>
- OpenAPI: <http://localhost:8000/docs>
- HAPI FHIR UI: <http://localhost:8080>
- HAPI FHIR base: <http://localhost:8080/fhir>

HAPI can take a minute or two on its first start while PostgreSQL initializes and the `hl7.eu.fhir.oah#0.1.0-ci-build` package is installed. The Compose image is pinned to HAPI `v8.10.0-3`; pin it by digest as well before a controlled deployment.

In the dashboard, choose **Replay Oder demo**, inspect each terminology proposal, and approve it (or use **Approve pending queue**). Three of the five readings cross the demonstration policy and create audience-specific alert cards; press **Draft veterinary** on one to see Gemini write the advisory. The header shows the FHIR write mode (`enabled` vs `dry-run`) and the AI mode (`gemini-2.5-flash · auto` vs `AI off`).

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
```

Then start and test:

```bash
uvicorn aquafhir.main:app --reload
pytest          # 70 tests, fully offline — no key needed, no network touched
ruff check .
```

The suite never calls Gemini. `tests/fakes.py` replaces only the HTTP hop, so the schema
construction, JSON parsing, hashing, and every guardrail still run for real.

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

A reviewer who disagrees with the model overrides it in the approve body:

```bash
curl -X POST http://localhost:8000/api/v1/proposals/PROPOSAL_ID/approve \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer":"reviewer@example.org",
    "coding":{"system":"http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu",
              "code":"chloride","display":"Chloride"},
    "normalized_value":120.0,
    "normalized_unit":"mg/L"
  }'
```

The override is recorded in the provenance payload alongside the model's prompt hash, so
the disagreement itself is auditable.

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

The OAH IG currently carries environmental concepts such as `electrical-conductivity`, `dissolved-oxygen`, `waterTemperature`, and `ndci` in its temporary project code system. The scaffold uses those codes rather than inventing unsupported LOINC mappings. Add a second LOINC or SNOMED CT coding only after terminology review.

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
| Which known unit string a source unit denotes | The conversion factor and the published number |
| Which measurements a free-text note literally contains | Whether review is required — always yes |
| How to phrase an advisory for one audience | Whether an alert fires, at what severity, to whom |
| | What is written to FHIR |

Three guardrails hold it:

1. **Closed vocabulary.** The curated catalog is injected into the prompt, the
   `responseSchema` constrains `code` to an enum of exactly those codes plus `NO_MATCH`,
   and [`coding_llm.py`](src/aquafhir/coding_llm.py) re-checks the returned code against
   the catalog anyway. A schema is a request, not a proof. An out-of-catalog code is
   discarded and the curated proposal stands.
2. **No model arithmetic.** The model may say *"this `uS/cm` string denotes the `uS/cm`
   unit"*. The factor and the multiplication live in
   `ReviewedCodingAgent.normalize_unit`, from reviewed YAML. The prompt never contains the
   converted value, so the model cannot anchor on the answer — there is a test asserting
   exactly that.
3. **Capped confidence.** Any AI-influenced proposal is capped at
   `GEMINI_CONFIDENCE_CEILING` (0.95). A disagreement with the curated match, or a
   model-raised expert-review flag, caps it at 0.80 and surfaces a warning on the card.
   No value publishes anything; `requires_review` is unconditional.

### Four wired features

| Feature | Endpoint | What the model is allowed to return |
|---|---|---|
| Terminology coding co-pilot | `POST /api/v1/proposals` | One catalog code, one known unit name, evidence, confidence |
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

## Repository map

```text
.
├── config/                    # reviewed terminology and demo alert policy
├── data/                      # transparent synthetic Oder replay CSV
├── docs/                      # architecture, API, demo, production notes
├── infra/hapi/               # HAPI R4 + OAH package configuration
├── src/aquafhir/
│   ├── coding.py             # curated proposer + the catalog the model is grounded in
│   ├── coding_llm.py         # Gemini coding co-pilot and its guardrails
│   ├── gemini.py             # minimal Generative Language REST client
│   ├── prompts.py            # versioned prompt templates and response schemas
│   ├── intake.py             # free text -> literal readings -> pending proposals
│   ├── briefing.py           # audience advisories and grounded situation reports
│   ├── fhir.py               # conformant resources, bundles, subscriptions
│   ├── repository.py         # SQLite workflow state + hash chain
│   ├── service.py            # review-gated orchestration
│   ├── thresholds.py         # unit-aware versioned policy evaluation
│   ├── main.py               # FastAPI surface
│   └── static/               # dependency-free review dashboard
├── tests/                    # coding, AI guardrail, transport, policy, audit tests
├── compose.yaml              # bridge + HAPI + PostgreSQL
└── Dockerfile
```

## Implemented versus production work

| Capability | In this scaffold | Required before real deployment |
|---|---|---|
| Ingestion | Typed JSON API and transparent replay CSV | Authenticated connectors, source schemas, retries, dead-letter queue |
| Coding | Curated proposals, unit conversion, and a grounded Gemini co-pilot | Terminology service, labelled model evaluation set, reviewer roles, dual control |
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
| `GEMINI_MODEL` | `gemini-2.5-flash` | Pin explicitly; recorded on every proposal |
| `GEMINI_ASSIST_MODE` | `auto` | `off`, `auto` (only where rules are weak), or `always` |
| `GEMINI_ASSIST_BELOW_CONFIDENCE` | `0.95` | `auto` consults the model below this curated confidence |
| `GEMINI_CONFIDENCE_CEILING` | `0.95` | Hard cap on any AI-influenced confidence |
| `GEMINI_TIMEOUT_SECONDS` | `30` | Per-call timeout |
| `GEMINI_MAX_OUTPUT_TOKENS` | `2048` | Truncated responses are rejected, never half-parsed |
| `GEMINI_MAX_RETRIES` | `2` | Retries only 408/429/5xx and network errors |
| `GEMINI_THINKING_BUDGET` | `0` | `0` for latency; `-1` omits the field for models that reject it |

## Source standards

- [OneAquaHealth FHIR IG continuous build](https://build.fhir.org/ig/hl7-eu/oah/)
- [OAH artifacts and profiles](https://build.fhir.org/ig/hl7-eu/oah/artifacts.html)
- [OAH package download](https://build.fhir.org/ig/hl7-eu/oah/downloads.html)
- [FHIR R4 Subscription](https://hl7.org/fhir/R4/subscription.html)
- [HAPI FHIR JPA starter](https://github.com/hapifhir/hapi-fhir-jpaserver-starter)

The OAH guide is an unauthorised, changing continuous build. Freeze and archive the exact NPM package used by a release; never assume `0.1.0-ci-build` is immutable merely because the version string stays the same.
