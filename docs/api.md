# API contract

Interactive documentation is available at `/docs`; the OpenAPI document is `/openapi.json`.

## Endpoints

| Method | Path | Purpose | Needs Gemini |
|---|---|---|---|
| `GET` | `/api/v1/health` | Process, policy, FHIR write mode, and AI mode | no |
| `GET` | `/api/v1/ai/status` | Which AI features are wired and what bounds them | no |
| `POST` | `/api/v1/proposals` | Validate a raw reading and create a pending mapping | optional |
| `GET` | `/api/v1/proposals` | List recent proposals | no |
| `GET` | `/api/v1/proposals/{id}` | Read one proposal | no |
| `POST` | `/api/v1/replay` | Load `data/oder-replay.csv` as pending proposals | optional |
| `POST` | `/api/v1/intake` | Extract readings from an unstructured note | **yes** |
| `POST` | `/api/v1/proposals/{id}/approve` | Publish reviewed resources and evaluate policy | no |
| `POST` | `/api/v1/proposals/{id}/reject` | Reject a proposal with a reason | no |
| `POST` | `/api/v1/proposals/approve-batch` | Sign off several inspected proposals at once | no |
| `GET` | `/api/v1/alerts` | List generated alert intents | no |
| `POST` | `/api/v1/alerts/{id}/briefings?audience=` | Draft an audience-specific advisory | **yes** |
| `GET` | `/api/v1/alerts/{id}/briefings` | List drafts for one alert | no |
| `GET` | `/api/v1/briefings` | List all advisory drafts | no |
| `POST` | `/api/v1/ai/situation-report` | Summarise stored observations and alerts | **yes** |
| `GET` | `/api/v1/provenance` | List newest hash-chain entries | no |
| `GET` | `/api/v1/provenance/verify` | Recompute and verify the complete chain | no |
| `POST` | `/api/v1/subscriptions?callback_url=...` | Install or preview the R4 rest-hook Subscription | no |
| `POST` | `/api/v1/webhooks/fhir` | Receive an R4 rest-hook notification and evaluate updates | no |

"Optional" means the endpoint works without a key and simply produces a curated-rules
proposal instead of a Gemini-assisted one.

## Review rules

- All new proposals are `pending` and `requires_review=true`, whether a model was consulted or not.
- Approval needs a non-empty reviewer, coding, numeric normalized value, and UCUM unit.
- A reviewer can replace the proposed `Coding`. Quantity corrections require both
  `normalized_value` and `normalized_unit`, so a unit cannot be changed without an explicit value.
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

## Error contract

| Status | Meaning |
|---|---|
| `400` | Unknown or unrouted advisory audience |
| `404` | Proposal, alert, or replay dataset does not exist |
| `409` | Proposal state or mapping is incompatible with the requested decision |
| `422` | Request body failed validation (for example a half-specified quantity override) |
| `502` | Gemini was reachable but returned an error, a block, or unparseable content |
| `503` | An AI-only endpoint was called without `GEMINI_API_KEY` configured |

FHIR upstream errors currently propagate as `500`; map them to a stable `502` problem
document before production.

## Webhook authentication

The example Subscription supplies `X-AquaFHIR-Secret`. The receiver compares it with
`WEBHOOK_SHARED_SECRET`. This is demo authentication only: use TLS, a secret manager,
rotation, constant-time comparison, replay protection, ingress restrictions, and preferably
mutual TLS or signed messages in deployment.
