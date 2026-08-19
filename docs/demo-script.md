# Five-minute demo

## Setup

1. Run `docker compose up --build` and wait for all three services to become healthy.
2. Open the dashboard and HAPI UI in separate tabs.
3. Confirm the dashboard mode badge says `enabled` and the audit chain says `VALID`.

## Narrative

**0:00–0:40 — Problem.** Cross-border water evidence arrives with different field names, units, and systems. A public-health or veterinary consumer cannot act on a spreadsheet it cannot interpret.

**0:40–1:20 — Ingest.** Choose **Replay Oder demo**. Explain that this is transparent synthetic replay data, not a historical reconstruction. Five raw readings appear in the queue.

**1:20–2:20 — Review.** Open the first `EC` proposal. Point out the mapping to the OAH `electrical-conductivity` code, conversion from source vocabulary, UCUM unit, confidence, and rationale. Emphasize that even a high-confidence proposal is pending until approval.

**2:20–3:20 — Standards.** Approve a proposal. Show the returned or HAPI-stored Observation with the OAH profile, Location subject, Organization performer, effective time, and UCUM quantity. This is the standards proof, not merely a chart.

**3:20–4:15 — Alert.** Approve the high-conductivity, high-NDCI, and low-oxygen readings. Show the alert cards and distinct public-health, veterinary, and water-authority audience tags. State that the checked-in thresholds are demonstration policy, not regulatory limits.

**4:15–5:00 — Trust.** Show the hash-chain timeline and `VALID` result. Close with the system boundary: the bridge provides earlier machine-readable decision support, while accountable authorities review and communicate the warning.

## Evidence to capture

- Count of records ingested, mapped, approved, rejected, and alerted.
- FHIR transaction response and profile URL.
- Median raw-to-proposal and approval-to-publication latency.
- Validator output against the frozen OAH package.
- Exact demo policy ID and source-data checksum.

