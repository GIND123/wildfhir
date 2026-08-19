# API contract

Interactive documentation is available at `/docs`; the OpenAPI document is `/openapi.json`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Process, policy, and FHIR write-mode status |
| `POST` | `/api/v1/proposals` | Validate a raw reading and create a pending mapping |
| `GET` | `/api/v1/proposals` | List recent proposals |
| `GET` | `/api/v1/proposals/{id}` | Read one proposal |
| `POST` | `/api/v1/proposals/{id}/approve` | Publish reviewed resources and evaluate policy |
| `POST` | `/api/v1/proposals/{id}/reject` | Reject a proposal with a reason |
| `GET` | `/api/v1/alerts` | List generated alert intents |
| `GET` | `/api/v1/provenance` | List newest hash-chain entries |
| `GET` | `/api/v1/provenance/verify` | Recompute and verify the complete chain |
| `POST` | `/api/v1/subscriptions?callback_url=...` | Install or preview the R4 rest-hook Subscription |
| `POST` | `/api/v1/webhooks/fhir` | Receive an empty R4 rest-hook notification, query HAPI, and evaluate updates |

## Review rules

- All new proposals are `pending` and `requires_review=true`.
- Approval needs a non-empty reviewer, coding, numeric normalized value, and UCUM unit.
- A reviewer can replace the proposed `Coding`. Quantity corrections require both `normalized_value` and `normalized_unit`, so a unit cannot be changed without an explicit value.
- Approved and rejected decisions are immutable through the API.
- `404` means the proposal does not exist. `409` means its state or mapping is incompatible with the requested decision. FHIR upstream errors currently propagate as `500`; map them to a stable `502` problem document before production.

## Webhook authentication

The example Subscription supplies `X-AquaFHIR-Secret`. The receiver compares it with `WEBHOOK_SHARED_SECRET`. This is demo authentication only: use TLS, a secret manager, rotation, constant-time comparison, replay protection, ingress restrictions, and preferably mutual TLS or signed messages in deployment.
