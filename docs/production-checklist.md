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


## Terminology crosswalk (local LOINC + UMLS)

The crosswalk is a suggester only, same posture as the Gemini co-pilot. These gates keep it
that way.

- The UMLS Terminology Services (UTS) license was approved 2026-08-20. Confirm the license
  terms cover the intended redistribution of any LOINC/SNOMED CT display text surfaced to
  reviewers, and keep the committed LOINC artifact unaltered as its license requires.
- Submit the environmental gaps to LOINC. Dissolved oxygen and water temperature in water,
  and satellite-derived indices such as NDCI, have no LOINC term today; a crosswalk cannot
  invent one, and the OAH temporary code system is the correct interim answer.
- Re-validate the LOINC table on every LOINC release. Codes are added and deprecated; a
  pinned artifact silently ages.
- Never attach a `secondary_coding` automatically. `ReviewDecision.secondary_coding` must
  stay an explicit, reviewer-supplied field, never a default or a score threshold.
- Hash-chain the full UMLS query and response the same way `AiAttribution` already does for
  Gemini (prompt hash, response hash, latency), not just the current
  `reviewer_attached_secondary_coding` boolean.
- Re-check the returned vocabulary against `UMLS_VOCABULARIES` in code, not only via the
  `sabs` search parameter — `terminology.py` already does this; keep it that way if the
  vocabulary list grows.
- Keep validating every LOINC candidate against the published term table. UMLS returns LOINC
  Parts (`LP...`) and Metathesaurus ids (`MTHU...`) that are not publishable LOINC codes, and
  a reviewer cannot be expected to spot the difference.
- Validate SNOMED CT candidates too. They are passed through unchecked today because this
  repository does not vendor the SNOMED release; a deployment should check them against a
  terminology server.
- Set a per-tenant quota, cache repeat lookups for the same display text, and add a circuit
  breaker; UTS is a shared, rate-limited public service.
- Confirm the pipeline still functions with `UMLS_API_KEY` removed *and* with the LOINC table
  absent — both paths are tested, keep them tested.

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



## Live connectors (Hub'Eau, Copernicus Sentinel-2)

Both connectors are read-only and produce pending proposals only. These gates keep the
live path honest before it is scheduled rather than pressed.

- Keep every live reading on the same review gate as a fixture row. No connector may
  approve, publish, or raise an alert on its own.
- Schedule pulls with a per-station cursor so a routine monthly sample is not re-queued as
  a duplicate; today the duplicate flag on the proposal is the only guard.
- Keep the below-quantification-limit skip (`code_remarque != 1`) and extend it to the
  other Sandre remark codes (trace, saturation) with the laboratory's own definitions.
- Decide, with a laboratory, whether Hub'Eau's `n/(100mL)` E. coli counts are MPN or CFU
  per method code before adding any conversion; the bridge currently withholds them
  deliberately and records the Sandre method (`code_methode_analyse`, on the reading as
  `analysis_method`) so the decision can be made per result. On the national feed the
  unit is reported almost only under NF EN ISO 9308-3 (Sandre 334, an MPN method) or with
  no method at all (Sandre 0), so a blanket CFU conversion would be wrong.
- Record the Hub'Eau `api_version` and the Sandre parameter/unit release with each pull.
- Copernicus: register a project OAuth client, rotate its secret, and pin the evalscript
  by hash (already recorded on every NDCI reading). Store the scene id, cloud cover,
  water-pixel count and resolution with the reading, and label the index as derived
  evidence, never as a concentration.
- Verify the NDCI request against a known-bloom scene before trusting the threshold; the
  Statistical API call is implemented to the documented shape and offline-tested but has
  not been run live in this repository.
- Respect both services' rate limits and terms; add a circuit breaker so a slow upstream
  cannot stall the review console.
