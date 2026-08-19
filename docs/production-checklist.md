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

