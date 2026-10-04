# API contract

Interactive documentation is available at `/docs`; the OpenAPI document is `/openapi.json`.

## Endpoints

| Method | Path | Purpose | Needs Gemini | Needs UMLS |
|---|---|---|---|---|
| `GET` | `/api/v1/health` | Process, policy, FHIR write mode, AI mode, and terminology-crosswalk mode | no | no |
| `GET` | `/api/v1/ai/status` | Which AI features are wired and what bounds them | no | no |
| `GET` | `/api/v1/terminology/status` | Which crosswalk sources are live (`loinc-table`, `umls`) and which vocabularies they search | no | no |
| `GET` | `/api/v1/integrations` | Every external dependency as the process sees it: model, endpoints, modes, policy rules, and masked credential fingerprints (first and last four characters; never the key) | no | no |
| `GET` | `/api/v1/coding/catalog` | The curated OAH catalog (codes, displays, aliases, accepted UCUM units, conversions, One Health `leg`, coded `value_set`) a reviewer may choose from when overriding a coding | no | no |
| `GET` | `/api/v1/connectors` | The two live connectors: enabled, auth mode (`keyless`, `credentials-required`, `credentials-configured`), whether live, configured stations/sites | no | no |
| `POST` | `/api/v1/connectors/hubeau/pull` | Pull real river-quality analyses from Hub'Eau (keyless) for configured Toulouse stations and queue them as pending proposals | optional | no |
| `GET` | `/api/v1/connectors/sentinel2/scenes?site_code=` | Which Sentinel-2 L2A scenes cover a configured site, with cloud cover (Copernicus catalogue, keyless) | no | no |
| `POST` | `/api/v1/connectors/sentinel2/pull` | Compute NDCI over a configured site's water pixels and queue one proposal per clear day; needs `CDSE_CLIENT_ID`/`CDSE_CLIENT_SECRET` | optional | no |
| `POST` | `/api/v1/proposals` | Validate a raw reading (a numeric `value` + `unit`, or a `coded_value` word) and create a pending mapping | optional | no |
| `GET` | `/api/v1/proposals` | List recent proposals | no | no |
| `GET` | `/api/v1/proposals/{id}` | Read one proposal | no | no |
| `GET` | `/api/v1/proposals/{id}/terminology-suggestions` | Suggest real LOINC/SNOMED CT candidates for the proposal's OAH code | no | optional |
| `GET` | `/api/v1/proposals/{id}/taxon-suggestions` | Suggest a GBIF Backbone taxon for the organism named in the source label | no | no |
| `POST` | `/api/v1/replay?dataset=` | Load a fixture as pending proposals: `oder-replay` (default, `data/oder-replay.csv`) or `incidents` (`data/incidents.csv`, the twelve real incidents from the catalogue in one file). Each proposal's `raw_payload` names its `replay_source` and `incident_fixture` | optional | no |
| `POST` | `/api/v1/replay/run?dataset=&reviewer=` | Load a fixture and drive it through the whole round under the named reviewer: publishable rows approved (FHIR build, policy, routing), the rest rejected with the pipeline's reason, chain verified; returns an `IncidentRunReport` with per-incident counts and the alerts | optional | no |
| `POST` | `/api/v1/intake` | Extract readings from an unstructured note | **yes** | no |
| `GET` | `/api/v1/proposals/{id}/normalization?code=` | What approving under a given catalog code would publish, with the formula | no | no |
| `GET` | `/api/v1/proposals/{id}/observation` | The stored Observation and FHIR receipt for an approved proposal | no | no |
| `POST` | `/api/v1/proposals/{id}/approve` | Publish reviewed resources through the profile the code's One Health leg requires and evaluate policy; accepts optional `secondary_coding`, `taxon`, and an expert correction (`normalized_value`+`normalized_unit` or `coded_value`, each with `correction_reason`) | no | no |
| `POST` | `/api/v1/proposals/{id}/reject` | Reject a proposal with a reason | no | no |
| `POST` | `/api/v1/proposals/approve-batch` | Sign off several inspected proposals at once | no | no |
| `GET` | `/api/v1/alerts` | List generated alert intents | no | no |
| `POST` | `/api/v1/alerts/{id}/briefings?audience=` | Draft an audience-specific advisory | **yes** | no |
| `GET` | `/api/v1/alerts/{id}/briefings` | List drafts for one alert | no | no |
| `GET` | `/api/v1/briefings` | List all advisory drafts | no | no |
| `POST` | `/api/v1/ai/situation-report` | Summarise stored observations and alerts | **yes** | no |
| `GET` | `/api/v1/provenance` | List newest hash-chain entries | no | no |
| `GET` | `/api/v1/provenance/verify` | Recompute and verify the complete chain | no | no |
| `POST` | `/api/v1/subscriptions?callback_url=...` | Install or preview the R4 rest-hook Subscription | no | no |
| `POST` | `/api/v1/webhooks/fhir` | Receive an R4 rest-hook notification and evaluate updates | no | no |

"Optional" means the endpoint works without a key and simply produces a curated-rules
proposal instead of a Gemini-assisted one. For the "Needs UMLS" column, "optional" means the
endpoint answers from the local LOINC table without a key and only loses SNOMED CT breadth;
it returns `503` only when the LOINC table is *also* missing.

## Review rules

- All new proposals are `pending` and `requires_review=true`, whether a model was consulted or not.
- Approval needs a non-empty reviewer, a coding, and a publishable value: a numeric
  normalized value with a UCUM unit, **or** a coded value from the indicator's reviewed value
  set (`absent` / `present` / `extensive` for `foam`, `macrophytes`, `macroinvertebreates`).
- The code's One Health `leg` decides the profile: environmental and animal codes publish
  through `observation-indicators-oah`, human codes through
  `observation-health-measure-oah`. Overriding to a human code at approval switches the
  profile; the leg is also recorded as a `meta.tag` and in the provenance payload.
- **Approval is resolved on the server, not by the client.** Only `coding.code` is
  read from the request; the published `system` and `display` always come from the
  curated catalog. An unknown code is a `422`.
- By default the server *derives* the quantity with `ReviewedCodingAgent.normalize_unit`,
  so an ordinary approval sends no numbers at all. Use
  `GET .../normalization?code=` to show the reviewer what that will be.
- Supplying `normalized_value` is an **expert correction** and requires
  `normalized_unit` and `correction_reason` together. It is still checked: the unit
  must be in the selected rule's `accepted_units`, and the value must pass its
  `plausible_range`. Either failure is a `422` and nothing is published or alerted.
- For a coded reading the correction is `coded_value` plus `correction_reason`; it must be
  one of the reviewed value-set concepts (aliases accepted), never a free word. A quantity
  correction on a coded reading, or a coded correction on a quantity reading, is a `422`.
- A word the source used that is not in the value set is **withheld** (`normalized_coding`
  is null), exactly like an unresolvable unit; it is never rounded to the nearest concept.
- A live pull (`connectors/*/pull`) creates ordinary pending proposals and one
  `connector-pull` provenance entry carrying the query, row counts, skipped reasons and the
  proposal ids. Live readings carry `raw_payload.synthetic = false` and cite their source
  record as `evidence_url`.
- A reviewer may also supply `taxon` (typically a GBIF candidate from
  `GET .../taxon-suggestions`), which becomes an `Observation.component` carrying
  LOINC `41852-5` as the component code and the taxon as `valueCodeableConcept`.
  It never touches `Observation.code.coding`, so it cannot influence the alert
  policy, and it is never inferred.
- A reviewer may also supply `secondary_coding` (typically a crosswalk-suggested LOINC/SNOMED CT
  candidate from `GET .../terminology-suggestions`), which becomes a second entry in
  `Observation.code.coding`. It is never inferred or attached automatically.
- Approved and rejected decisions are immutable through the API.
- `approve-batch` is not a bypass: each id is validated, decided, stored, and hash-chained
  individually, and per-item failures are returned rather than aborting the batch.

## AI response fields

A proposal that consulted Gemini carries an `ai` object and `proposer = "gemini-assisted"`:

```json
{
  "proposer": "gemini-assisted",
  "confidence": 0.93,
  "coding": { "code": "electrical-conductivity", "display": "Electrical conductivity" },
  "normalized_value": 2.35,
  "normalized_unit": "mS/cm",
  "ai": {
    "provider": "google-gemini",
    "model": "gemini-3.1-pro-preview",
    "template_id": "coding-proposer/v1",
    "prompt_hash": "960ceef7b312f4e8...",
    "response_hash": "…",
    "latency_ms": 63,
    "grounded_codes": ["electrical-conductivity", "ndci", "…"],
    "evidence": ["Leitfähigkeit"],
    "model_confidence": 0.93,
    "disagreed_with_rules": false,
    "needs_expert_review": false
  }
}
```

`prompt_hash` covers the template id, system instruction, and rendered prompt together, so
an auditor can tell a prompt-template change from an input change. Both hashes are written
into the provenance chain on approval and rejection.

`disagreed_with_rules` is true when the model chose a different code than curated alias
matching did. That case is capped at confidence 0.80 and surfaced in the dashboard, because
it is the case a reviewer most needs to look at.

## Terminology crosswalk response fields

`GET /api/v1/proposals/{id}/terminology-suggestions` returns up to 5 `TerminologyMatch`
objects, ranked by name similarity to the proposal's curated OAH display text:

```json
[
  {
    "system": "http://loinc.org",
    "code": "9481-3",
    "display": "pH of Water",
    "vocabulary": "LNC",
    "score": 1.0
  }
]
```

`system` is the canonical FHIR coding system URI (`LNC` → `http://loinc.org`,
`SNOMEDCT_US` → `http://snomed.info/sct`); `code` is the source vocabulary's own code, not a
UMLS CUI. Environmental LOINC matches from the local table rank first, then UMLS results.
Every LOINC candidate is checked against the published term table, so LOINC Parts (`LP...`)
and Metathesaurus ids (`MTHU...`) never appear. Pass any one candidate back verbatim as
`secondary_coding` on approval to publish it as a second `Coding`.

An empty list means no publishable candidate matched — environmental LOINC genuinely has no
term for dissolved oxygen or water temperature in water. That is a real answer, not a
failure; a lookup that actually broke returns `502`.

## Error contract

| Status | Meaning |
|---|---|
| `400` | Unknown or unrouted advisory audience |
| `404` | Proposal, alert, replay dataset, or configured Sentinel-2 site does not exist |
| `409` | Proposal state or mapping is incompatible with the requested decision |
| `422` | Request body failed validation (including a reading with both or neither of `value` and `coded_value`), or the decision cannot be published: unknown code, a unit the rule does not accept, a value outside the plausible range, a coded value outside the reviewed value set, a value of the wrong kind for the indicator, or a half-specified expert correction |
| `502` | Gemini, UMLS, GBIF, Hub'Eau or Copernicus was reachable but returned an error, a block, or unparseable content (`error_code` names the source) |
| `503` | An AI-only endpoint was called without `GEMINI_API_KEY`; the crosswalk has no source at all (no LOINC table *and* no `UMLS_API_KEY`); a connector is disabled; an unknown Hub'Eau station was requested; or NDCI was requested without a CDSE OAuth client |

FHIR upstream errors currently propagate as `500`; map them to a stable `502` problem
document before production.

## Webhook authentication

The example Subscription supplies `X-AquaFHIR-Secret`. The receiver compares it with
`WEBHOOK_SHARED_SECRET`. This is demo authentication only: use TLS, a secret manager,
rotation, constant-time comparison, replay protection, ingress restrictions, and preferably
mutual TLS or signed messages in deployment.
