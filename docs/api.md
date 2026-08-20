# API contract

Interactive documentation is available at `/docs`; the OpenAPI document is `/openapi.json`.

## Endpoints

| Method | Path | Purpose | Needs Gemini | Needs UMLS |
|---|---|---|---|---|
| `GET` | `/api/v1/health` | Process, policy, FHIR write mode, AI mode, and terminology-crosswalk mode | no | no |
| `GET` | `/api/v1/ai/status` | Which AI features are wired and what bounds them | no | no |
| `GET` | `/api/v1/terminology/status` | Whether the UMLS crosswalk is enabled and which vocabularies it searches | no | no |
| `POST` | `/api/v1/proposals` | Validate a raw reading and create a pending mapping | optional | no |
| `GET` | `/api/v1/proposals` | List recent proposals | no | no |
| `GET` | `/api/v1/proposals/{id}` | Read one proposal | no | no |
| `GET` | `/api/v1/proposals/{id}/terminology-suggestions` | Suggest real LOINC/SNOMED CT candidates for the proposal's OAH code | no | **yes** |
| `POST` | `/api/v1/replay` | Load `data/oder-replay.csv` as pending proposals | optional | no |
| `POST` | `/api/v1/intake` | Extract readings from an unstructured note | **yes** | no |
| `POST` | `/api/v1/proposals/{id}/approve` | Publish reviewed resources and evaluate policy; accepts an optional `secondary_coding` | no | no |
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
proposal instead of a Gemini-assisted one. The same idea applies to the "Needs UMLS" column:
without `UMLS_API_KEY`, `/api/v1/terminology/*` returns `503` and every other endpoint is
unaffected.

## Review rules

- All new proposals are `pending` and `requires_review=true`, whether a model was consulted or not.
- Approval needs a non-empty reviewer, coding, numeric normalized value, and UCUM unit.
- A reviewer can replace the proposed `Coding`. Quantity corrections require both
  `normalized_value` and `normalized_unit`, so a unit cannot be changed without an explicit value.
- A reviewer may also supply `secondary_coding` (typically a UMLS-suggested LOINC/SNOMED CT
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
    "model": "gemini-2.5-flash",
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
    "code": "11556-8",
    "display": "Dissolved oxygen",
    "vocabulary": "LNC",
    "score": 1.0
  }
]
```

`system` is the canonical FHIR coding system URI for the UMLS root source (`LNC` →
`http://loinc.org`, `SNOMEDCT_US` → `http://snomed.info/sct`); `code` is the source
vocabulary's own code, not a UMLS CUI. Pass any one candidate back verbatim as
`secondary_coding` on approval to publish it as a second `Coding`.

## Error contract

| Status | Meaning |
|---|---|
| `400` | Unknown or unrouted advisory audience |
| `404` | Proposal, alert, or replay dataset does not exist |
| `409` | Proposal state or mapping is incompatible with the requested decision |
| `422` | Request body failed validation (for example a half-specified quantity override) |
| `502` | Gemini or UMLS was reachable but returned an error, a block, or unparseable content |
| `503` | An AI-only or UMLS-only endpoint was called without `GEMINI_API_KEY` / `UMLS_API_KEY` configured |

FHIR upstream errors currently propagate as `500`; map them to a stable `502` problem
document before production.

## Webhook authentication

The example Subscription supplies `X-AquaFHIR-Secret`. The receiver compares it with
`WEBHOOK_SHARED_SECRET`. This is demo authentication only: use TLS, a secret manager,
rotation, constant-time comparison, replay protection, ingress restrictions, and preferably
mutual TLS or signed messages in deployment.
