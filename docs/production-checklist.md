# Production readiness checklist

## Standards and policy

- Freeze the OAH NPM package artifact and checksum; do not deploy against a moving CI URL.
- Run the official HL7 validator against every resource type in CI.
- Confirm terminology licensing and validate OAH, SNOMED CT, LOINC, and UCUM codes with an approved service.
- Replace all demo thresholds with signed, jurisdiction- and site-specific policy approved by accountable experts.
- Version policy effective dates and record the evaluated version on every alert.

## Safety and governance

- Define reviewer qualifications, separation of duties, escalation, correction, and recall workflows.
- Establish false-positive/false-negative monitoring and a mechanism to suppress faulty sources.
- Label satellite proxies as derived evidence and retain algorithms, cloud masks, scene IDs, resolution, and uncertainty.
- Never describe an alert as diagnosis or guaranteed prevention.
- Complete data-protection, equity, accessibility, and cross-border governance reviews.

## AI co-pilot (Gemini)

The model layer is a proposer only. These gates keep it that way.

- Keep `requires_review = true` unconditional. No confidence value, model version, or
  operator setting may auto-approve a mapping, and no model output may reach the FHIR
  publisher or the threshold engine directly.
- Pin the model version explicitly (`GEMINI_MODEL`) and record it with every proposal.
  Re-run the evaluation set before changing it; a silent model upgrade is a change to
  clinical-adjacent behaviour.
- Version every prompt template (`prompts.py` ids) and treat a wording change as a
  reviewable change. The rendered prompt hash is already chained; add template-diff
  review to the release process.
- Build a labelled evaluation set of real multilingual source labels with expert-assigned
  OAH codes. Track precision, recall, refusal rate (`NO_MATCH`), and the rate at which
  reviewers override the model. Publish the numbers alongside the release.
- Measure reviewer over-trust directly: sample approvals and re-check them blind. A
  co-pilot that raises throughput while lowering review quality is a net safety loss.
- Constrain the vocabulary at the API boundary (`responseSchema` enums) *and* re-check it
  in code after the response, as `coding_llm.py` does. Never trust the schema alone.
- Keep all unit arithmetic in `coding.py`. A model may name a unit; it must never compute
  a published quantity.
- Treat unstructured intake text as untrusted input. Add prompt-injection tests, cap input
  size, and remember that extraction output is still gated by human review.
- Route advisory drafts through an accountable authority before any external send. The
  `draft` status and the stored disclaimer are the current, deliberately weak, control.
- Set a per-tenant quota and a circuit breaker. Confirm the pipeline still functions with
  the key removed — that path is tested, keep it tested.
- Review the provider's data-handling terms against your data-protection assessment before
  sending any real monitoring data, and record the legal basis for the transfer.


## Terminology crosswalk (UMLS)

The crosswalk is a suggester only, same posture as the Gemini co-pilot. These gates keep it
that way.

- Complete the UMLS Terminology Services (UTS) license before any real query — a
  request was submitted 2026-08-19 and is pending NLM's review. Confirm the license terms
  cover the intended redistribution of any LOINC/SNOMED CT display text surfaced to
  reviewers before going beyond a demo.
- Never attach a `secondary_coding` automatically. `ReviewDecision.secondary_coding` must
  stay an explicit, reviewer-supplied field, never a default or a score threshold.
- Hash-chain the full UMLS query and response the same way `AiAttribution` already does for
  Gemini (prompt hash, response hash, latency), not just the current
  `reviewer_attached_secondary_coding` boolean.
- Re-check the returned vocabulary against `UMLS_VOCABULARIES` in code, not only via the
  `sabs` search parameter — `terminology.py` already does this; keep it that way if the
  vocabulary list grows.
- Set a per-tenant quota, cache repeat lookups for the same display text, and add a circuit
  breaker; UTS is a shared, rate-limited public service.
- Confirm the pipeline still functions with `UMLS_API_KEY` removed — that path is tested,
  keep it tested.

## Security

- Put both APIs behind TLS and an API gateway; remove direct public HAPI access.
- Add OIDC/SMART-compatible authentication and least-privilege RBAC.
- Keep secrets in a managed secret store and rotate webhook credentials.
- Sign or mutually authenticate callbacks, validate content types and sizes, and prevent replay.
- Add dependency/container scanning, SBOMs, image signatures, network policies, and egress allowlists.
- Export immutable audit checkpoints to WORM storage and sign them with managed keys.

## Reliability and operations

- Use PostgreSQL for workflow state and an atomic outbox for FHIR publication.
- Add connector idempotency keys, retries with backoff, dead-letter handling, and operator replay tools.
- Add OpenTelemetry traces, structured logs without sensitive payloads, metrics, alerts, and SLOs.
- Test backups, point-in-time recovery, FHIR export, multi-region recovery, and degraded read-only operation.
- Load-test transaction, subscription, and terminology behavior at expected burst rates.

