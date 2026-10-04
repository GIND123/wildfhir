# Incident API run log

**Run (UTC):** 2026-09-22T21:12:18+00:00 → 2026-09-22T23:21:54+00:00  
**Bridge:** uvicorn on 127.0.0.1:8765, clean SQLite database · FHIR `dry-run` · policy `oder-replay-demo-v1` (demo-not-for-operational-use) · AI `gemini-3.1-flash-lite` (auto) · crosswalk `loinc-table+umls+gbif`  
**API calls:** 322 / 322 succeeded, 0 failed  
**Audit chain:** valid over 328 entries before the tamper drill; after rewriting one Flint payload in SQLite: valid=False, first invalid sequence 141  
**Provenance events:** ai-call×40, alert-created×52, mapping-approved×76, mapping-proposed×116, mapping-rejected×40, unstructured-intake×4

Driver: a variant of `scripts/simulate.py` that keeps every response (`docs/media/incident-api-run.json`). Every fixture row is posted to `POST /api/v1/proposals`; coded rows are approved by `incident-run@aquafhir.example`, the rest rejected with a written reason; bulletins go through `POST /api/v1/intake`; the first three coded rows per scenario ask `GET .../terminology-suggestions`. The page built from this log is `docs/media/incident-atlas.html`.

## Per scenario

| Scenario | Rows | Coded | Withheld | Refused | Alerts | Audiences | Model consulted | Matches catalogue |
|---|---:|---:|---:|---:|---:|---|---:|---|
| oder-2022 | 11 | 10 | 0 | 1 | 6 | public-health, veterinary, water-authority | 3 | no (AI key present: Leitfaehigkeit coded; alert set identical) |
| milwaukee-1993 | 6 | 4 | 0 | 2 | 2 | public-health, water-authority | 2 | yes |
| walkerton-2000 | 5 | 4 | 0 | 1 | 4 | public-health, veterinary, water-authority | 1 | yes |
| toledo-2014 | 7 | 6 | 0 | 1 | 4 | public-health, veterinary, water-authority | 1 | yes |
| havelock-north-2016 | 10 | 8 | 1 | 1 | 8 | public-health, veterinary, water-authority | 2 | yes |
| flint-2014 | 6 | 5 | 0 | 1 | 4 | public-health, water-authority | 1 | yes |
| baia-mare-2000 | 8 | 5 | 0 | 3 | 4 | veterinary, water-authority | 3 | yes |
| ajka-2010 | 7 | 6 | 1 | 0 | 5 | public-health, veterinary, water-authority | 1 | yes |
| mar-menor-2021 | 6 | 6 | 0 | 0 | 6 | public-health, veterinary, water-authority | 0 | yes |
| akerselva-2011 | 6 | 5 | 0 | 1 | 1 | veterinary, water-authority | 1 | yes |
| seine-2024 | 6 | 4 | 1 | 1 | 2 | public-health, veterinary, water-authority | 2 | yes |
| brixham-2024 | 5 | 4 | 0 | 1 | 2 | public-health, veterinary, water-authority | 1 | yes |
| coimbra-citizen-2026 | 7 | 5 | 2 | 0 | 2 | veterinary, water-authority | 2 | yes |
| edge-cases | 10 | 4 | 5 | 1 | 2 | public-health, veterinary, water-authority | 6 | yes |

## Every reading

| Scenario | Observed | Reading as received | HTTP | ms | Outcome | Code | Published value | Proposer | Alerts |
|---|---|---|---:|---:|---|---|---|---|---|
| oder-2022 | 2022-07-24 | EC 1.2 mS/cm | 201 | 3.0 | coded | electrical-conductivity | 1.2 mS/cm | curated-rules |  |
| oder-2022 | 2022-07-24 | chlorki 340.0 mg/L | 201 | 5103.0 | coded | chloride | 340.0 mg/L | gemini-assisted |  |
| oder-2022 | 2022-07-25 | NDCI 0.18 1 | 201 | 4.9 | coded | ndci | 0.18 1 | curated-rules |  |
| oder-2022 | 2022-07-27 | Leitfaehigkeit 2350.0 uS/cm | 201 | 4553.4 | coded | electrical-conductivity | 2.35 mS/cm | gemini-assisted | high electrical-conductivity → public-health/veterinary/water-authority |
| oder-2022 | 2022-07-27 | chloride dissolved 1180.0 mg/L | 201 | 12.9 | coded | chloride | 1180.0 mg/L | curated-rules | high chloride → water-authority/veterinary |
| oder-2022 | 2022-07-27 | temp water 26.4 Cel | 201 | 7.5 | coded | waterTemperature | 26.4 Cel | curated-rules | moderate waterTemperature → water-authority |
| oder-2022 | 2022-07-28 | normalized difference chlorophyll index 0.43 1 | 201 | 10.2 | coded | ndci | 0.43 1 | curated-rules | high ndci → public-health/veterinary/water-authority |
| oder-2022 | 2022-07-29 | dissolved O2 3.6 mg/L | 201 | 5.3 | coded | dissolved-oxygen | 3.6 mg/L | curated-rules | critical dissolved-oxygen → veterinary/water-authority |
| oder-2022 | 2022-08-06 | electrical conductivity 2.41 mS/cm | 201 | 6.3 | coded | electrical-conductivity | 2.41 mS/cm | curated-rules | high electrical-conductivity → public-health/veterinary/water-authority |
| oder-2022 | 2022-08-09 | mercury 0.35 ug/L | 201 | 3.8 | coded | mercury-dissolved | 0.35 ug/L | curated-rules |  |
| oder-2022 | 2022-08-10 | Prymnesium parvum cell count 98000.0 {cells}/mL | 201 | 6068.4 | no_code |  |  | gemini-assisted |  |
| milwaukee-1993 | 1993-03-20 | turbidity 0.3 [NTU] | 201 | 4934.6 | no_code |  |  | gemini-assisted |  |
| milwaukee-1993 | 1993-03-28 | turbidity 1.7 [NTU] | 201 | 8157.1 | no_code |  |  | gemini-assisted |  |
| milwaukee-1993 | 1993-03-20 | total suspended solids 4.2 mg/L | 201 | 14.0 | coded | tss | 4.2 mg/L | curated-rules |  |
| milwaukee-1993 | 1993-03-28 | total suspended solids 31.5 mg/L | 201 | 10.3 | coded | tss | 31.5 mg/L | curated-rules | high tss → public-health/water-authority |
| milwaukee-1993 | 1993-04-01 | suspended solids 48.0 mg/L | 201 | 6.9 | coded | tss | 48.0 mg/L | curated-rules | high tss → public-health/water-authority |
| milwaukee-1993 | 1993-03-28 | water temperature 3.8 Cel | 201 | 6.0 | coded | waterTemperature | 3.8 Cel | curated-rules |  |
| walkerton-2000 | 2000-05-15 | free chlorine residual 0.0 mg/L | 201 | 4466.1 | no_code |  |  | gemini-assisted |  |
| walkerton-2000 | 2000-05-15 | total coliforms 2400.0 {cfu}/100mL | 201 | 12.9 | coded | coliforms | 2400.0 {cfu}/dL | curated-rules | critical coliforms → public-health/veterinary/water-authority |
| walkerton-2000 | 2000-05-17 | faecal coliforms 1600.0 CFU/100mL | 201 | 9.5 | coded | coliforms | 1600.0 {cfu}/dL | curated-rules | critical coliforms → public-health/veterinary/water-authority |
| walkerton-2000 | 2000-05-17 | ammonium 1.8 mg/L | 201 | 5.8 | coded | ammonium | 1.8 mg/L | curated-rules | high ammonium → public-health/water-authority |
| walkerton-2000 | 2000-05-13 | total suspended solids 42.0 mg/L | 201 | 7.3 | coded | tss | 42.0 mg/L | curated-rules | high tss → public-health/water-authority |
| toledo-2014 | 2014-07-27 | NDCI 0.22 1 | 201 | 3.7 | coded | ndci | 0.22 1 | curated-rules |  |
| toledo-2014 | 2014-07-27 | maximum chlorophyll index 0.14 1 | 201 | 6.3 | coded | mci | 0.14 1 | curated-rules |  |
| toledo-2014 | 2014-08-01 | NDCI 0.51 1 | 201 | 3.3 | coded | ndci | 0.51 1 | curated-rules | high ndci → public-health/veterinary/water-authority |
| toledo-2014 | 2014-08-01 | maximum chlorophyll index 0.38 1 | 201 | 5.4 | coded | mci | 0.38 1 | curated-rules | high mci → public-health/veterinary/water-authority |
| toledo-2014 | 2014-08-02 | microcystin-LR 2.5 ug/L | 201 | 1530.5 | no_code |  |  | gemini-assisted |  |
| toledo-2014 | 2014-08-02 | water temperature 26.8 Cel | 201 | 10.5 | coded | waterTemperature | 26.8 Cel | curated-rules | moderate waterTemperature → water-authority |
| toledo-2014 | 2014-08-01 | total phosphates 0.94 mg/L | 201 | 7.6 | coded | total-phosphates | 0.94 mg/L | curated-rules | moderate total-phosphates → water-authority |
| havelock-north-2016 | 2016-08-08 | total coliforms 1900.0 {cfu}/100mL | 201 | 5.1 | coded | coliforms | 1900.0 {cfu}/dL | curated-rules | critical coliforms → public-health/veterinary/water-authority |
| havelock-north-2016 | 2016-08-10 | faecal coliforms 940.0 CFU/100mL | 201 | 4.9 | coded | coliforms | 940.0 {cfu}/dL | curated-rules | critical coliforms → public-health/veterinary/water-authority |
| havelock-north-2016 | 2016-08-08 | ammonium 2.4 mg/L | 201 | 3.6 | coded | ammonium | 2.4 mg/L | curated-rules | high ammonium → public-health/water-authority |
| havelock-north-2016 | 2016-08-08 | nitrate 58.0 mg/L | 201 | 3.4 | coded | nitrate | 58.0 mg/L | curated-rules | high nitrate → public-health/water-authority |
| havelock-north-2016 | 2016-08-07 | total suspended solids 66.0 mg/L | 201 | 5.2 | coded | tss | 66.0 mg/L | curated-rules | high tss → public-health/water-authority |
| havelock-north-2016 | 2016-08-08 | free chlorine residual 0.0 mg/L | 201 | 3058.5 | no_code |  |  | gemini-assisted |  |
| havelock-north-2016 | 2016-08-12 | campylobacter notifications per 100000 714.0 {cases}/100000 | 201 | 16.4 | coded | campylobacter | 714.0 {cases}/100000 | curated-rules | critical campylobacter → public-health/veterinary/water-authority |
| havelock-north-2016 | 2016-08-15 | campylobacteriosis 7143.0 {cases}/100000 | 201 | 8.3 | coded | campylobacter | 7143.0 {cases}/100000 | curated-rules | critical campylobacter → public-health/veterinary/water-authority |
| havelock-north-2016 | 2016-08-19 | acute gastrointestinal illness 39.3 % | 201 | 8.5 | coded | gastrointestinal | 39300.0 {cases}/100000 | curated-rules | high gastrointestinal → public-health/water-authority |
| havelock-north-2016 | 2016-08-15 | campylobacter notified cases 1000.0 cases | 201 | 6797.4 | blocked_qty | campylobacter |  | gemini-assisted |  |
| flint-2014 | 2015-06-25 | lead 0.004 mg/L | 201 | 3.7 | coded | lead-dissolved | 4.0 ug/L | curated-rules |  |
| flint-2014 | 2015-06-26 | lead 0.011 mg/L | 201 | 3.8 | coded | lead-dissolved | 11.0 ug/L | curated-rules | critical lead-dissolved → public-health/water-authority |
| flint-2014 | 2015-06-29 | lead 0.104 mg/L | 201 | 3.7 | coded | lead-dissolved | 104.0 ug/L | curated-rules | critical lead-dissolved → public-health/water-authority |
| flint-2014 | 2015-07-01 | lead 0.02 mg/L | 201 | 3.4 | coded | lead-dissolved | 20.0 ug/L | curated-rules | critical lead-dissolved → public-health/water-authority |
| flint-2014 | 2015-08-17 | lead 0.158 mg/L | 201 | 3.1 | coded | lead-dissolved | 158.0 ug/L | curated-rules | critical lead-dissolved → public-health/water-authority |
| flint-2014 | 2015-01-12 | free chlorine residual 0.02 mg/L | 201 | 16662.2 | no_code |  |  | gemini-assisted |  |
| baia-mare-2000 | 2000-01-30 | total cyanide 32.0 mg/L | 201 | 4266.0 | no_code |  |  | gemini-assisted |  |
| baia-mare-2000 | 2000-01-30 | copper 2100.0 ug/L | 201 | 10.3 | coded | copper-dissolved | 2100.0 ug/L | curated-rules | high copper-dissolved → veterinary/water-authority |
| baia-mare-2000 | 2000-01-30 | zinc 4800.0 ug/L | 201 | 7.5 | coded | zinc-dissolved | 4800.0 ug/L | curated-rules | high zinc-dissolved → veterinary/water-authority |
| baia-mare-2000 | 2000-02-04 | total cyanide 7.8 mg/L | 201 | 5217.5 | no_code |  |  | gemini-assisted |  |
| baia-mare-2000 | 2000-02-04 | dissolved O2 3.1 mg/L | 201 | 7.4 | coded | dissolved-oxygen | 3.1 mg/L | curated-rules | critical dissolved-oxygen → veterinary/water-authority |
| baia-mare-2000 | 2000-02-04 | pH 7.9 [pH] | 201 | 4.2 | coded | ph | 7.9 [pH] | curated-rules |  |
| baia-mare-2000 | 2000-02-11 | total cyanide 0.42 mg/L | 201 | 5805.0 | no_code |  |  | gemini-assisted |  |
| baia-mare-2000 | 2000-02-11 | copper 180.0 ug/L | 201 | 10.8 | coded | copper-dissolved | 180.0 ug/L | curated-rules | high copper-dissolved → veterinary/water-authority |
| ajka-2010 | 2010-10-04 | pH 13.0 [pH] | 201 | 3.8 | coded | ph | 13.0 [pH] | curated-rules | critical ph → public-health/veterinary/water-authority |
| ajka-2010 | 2010-10-04 | aluminium 42000.0 ug/L | 201 | 4.5 | coded | aluminium-dissolved | 42000.0 ug/L | curated-rules | high aluminium-dissolved → public-health/water-authority |
| ajka-2010 | 2010-10-05 | pH 130.0 [pH] | 201 | 4463.3 | blocked_qty | ph |  | gemini-assisted |  |
| ajka-2010 | 2010-10-06 | pH 9.6 [pH] | 201 | 8.2 | coded | ph | 9.6 [pH] | curated-rules | critical ph → public-health/veterinary/water-authority |
| ajka-2010 | 2010-10-06 | dissolved O2 2.1 mg/L | 201 | 8.1 | coded | dissolved-oxygen | 2.1 mg/L | curated-rules | critical dissolved-oxygen → veterinary/water-authority |
| ajka-2010 | 2010-10-09 | pH 8.4 [pH] | 201 | 4.6 | coded | ph | 8.4 [pH] | curated-rules |  |
| ajka-2010 | 2010-10-09 | aluminium 310.0 ug/L | 201 | 5.6 | coded | aluminium-dissolved | 310.0 ug/L | curated-rules | high aluminium-dissolved → public-health/water-authority |
| mar-menor-2021 | 2021-08-10 | nitrate 72.0 mg/L | 201 | 4.6 | coded | nitrate | 72.0 mg/L | curated-rules | high nitrate → public-health/water-authority |
| mar-menor-2021 | 2021-08-10 | total phosphates 0.88 mg/L | 201 | 5.4 | coded | total-phosphates | 0.88 mg/L | curated-rules | moderate total-phosphates → water-authority |
| mar-menor-2021 | 2021-08-12 | temp water 30.6 Cel | 201 | 4.3 | coded | waterTemperature | 30.6 Cel | curated-rules | moderate waterTemperature → water-authority |
| mar-menor-2021 | 2021-08-13 | NDCI 0.47 1 | 201 | 3.4 | coded | ndci | 0.47 1 | curated-rules | high ndci → public-health/veterinary/water-authority |
| mar-menor-2021 | 2021-08-16 | dissolved oxygen 1.4 mg/L | 201 | 4.5 | coded | dissolved-oxygen | 1.4 mg/L | curated-rules | critical dissolved-oxygen → veterinary/water-authority |
| mar-menor-2021 | 2021-08-16 | electrical conductivity 68.0 mS/cm | 201 | 5.4 | coded | electrical-conductivity | 68.0 mS/cm | curated-rules | high electrical-conductivity → public-health/veterinary/water-authority |
| akerselva-2011 | 2011-03-08 | free chlorine residual 4.1 mg/L | 201 | 4038.1 | no_code |  |  | gemini-assisted |  |
| akerselva-2011 | 2011-03-08 | dissolved oxygen 9.8 mg/L | 201 | 12.9 | coded | dissolved-oxygen | 9.8 mg/L | curated-rules |  |
| akerselva-2011 | 2011-03-08 | pH 7.2 [pH] | 201 | 6.0 | coded | ph | 7.2 [pH] | curated-rules |  |
| akerselva-2011 | 2011-03-09 | dissolved oxygen 3.1 mg/L | 201 | 7.4 | coded | dissolved-oxygen | 3.1 mg/L | curated-rules | critical dissolved-oxygen → veterinary/water-authority |
| akerselva-2011 | 2011-03-09 | electrical conductivity 0.86 mS/cm | 201 | 7.6 | coded | electrical-conductivity | 0.86 mS/cm | curated-rules |  |
| akerselva-2011 | 2011-03-09 | water temperature 3.1 Cel | 201 | 5.8 | coded | waterTemperature | 3.1 Cel | curated-rules |  |
| seine-2024 | 2024-07-30 | E. coli 980.0 CFU/100mL | 201 | 5.6 | coded | coliforms | 980.0 {cfu}/dL | curated-rules | critical coliforms → public-health/veterinary/water-authority |
| seine-2024 | 2024-07-30 | E. coli 3400.0 MPN/100mL | 201 | 7398.2 | blocked_qty | coliforms |  | gemini-assisted |  |
| seine-2024 | 2024-07-30 | enterococci 410.0 {cfu}/100mL | 201 | 4182.0 | no_code |  |  | gemini-assisted |  |
| seine-2024 | 2024-08-01 | E. coli 220.0 CFU/100mL | 201 | 9.5 | coded | coliforms | 220.0 {cfu}/dL | curated-rules |  |
| seine-2024 | 2024-07-30 | ammonium 0.42 mg/L | 201 | 8.2 | coded | ammonium | 0.42 mg/L | curated-rules |  |
| seine-2024 | 2024-07-30 | E. coli 1450.0 CFU/100mL | 201 | 6.7 | coded | coliforms | 1450.0 {cfu}/dL | curated-rules | critical coliforms → public-health/veterinary/water-authority |
| brixham-2024 | 2024-05-14 | total suspended solids 38.0 mg/L | 201 | 7.4 | coded | tss | 38.0 mg/L | curated-rules | high tss → public-health/water-authority |
| brixham-2024 | 2024-05-15 | total coliforms 1250.0 {cfu}/100mL | 201 | 5.7 | coded | coliforms | 1250.0 {cfu}/dL | curated-rules | critical coliforms → public-health/veterinary/water-authority |
| brixham-2024 | 2024-05-15 | free chlorine residual 0.06 mg/L | 201 | 5714.9 | no_code |  |  | gemini-assisted |  |
| brixham-2024 | 2024-05-16 | total coliforms 640.0 CFU/100mL | 201 | 12.5 | coded | coliforms | 640.0 {cfu}/dL | curated-rules |  |
| brixham-2024 | 2024-05-20 | total suspended solids 12.0 mg/L | 201 | 9.0 | coded | tss | 12.0 mg/L | curated-rules |  |
| coimbra-citizen-2026 | 2026-05-04 | foam “present” | 201 | 5.7 | coded | foam | present | curated-rules | moderate foam → water-authority |
| coimbra-citizen-2026 | 2026-05-04 | macrophytes “extensive” | 201 | 7.6 | coded | macrophytes | extensive | curated-rules |  |
| coimbra-citizen-2026 | 2026-05-04 | macroinvertebrates “none” | 201 | 7.2 | coded | macroinvertebreates | absent | curated-rules | moderate macroinvertebreates → veterinary/water-authority |
| coimbra-citizen-2026 | 2026-05-04 | fish 0.0 {count} | 201 | 4.0 | coded | fishes | 0.0 {count} | curated-rules |  |
| coimbra-citizen-2026 | 2026-05-11 | foam “kinda foamy” | 201 | 6396.2 | blocked_qty | foam |  | gemini-assisted |  |
| coimbra-citizen-2026 | 2026-05-11 | foam 2.0 mg/L | 201 | 6970.1 | blocked_qty | foam |  | gemini-assisted |  |
| coimbra-citizen-2026 | 2026-05-11 | water temperature 17.5 degC | 201 | 14.3 | coded | waterTemperature | 17.5 Cel | curated-rules |  |
| edge-cases | 2026-06-01 | dissolved oxygen -5.0 mg/L | 201 | 5236.6 | blocked_qty | dissolved-oxygen |  | gemini-assisted |  |
| edge-cases | 2026-06-01 | pH 130.0 [pH] | 201 | 1892.2 | blocked_qty | ph |  | gemini-assisted |  |
| edge-cases | 2026-06-01 | water temperature -400.0 Cel | 201 | 2314.5 | blocked_qty | waterTemperature |  | gemini-assisted |  |
| edge-cases | 2026-06-01 | electrical conductivity 999999.0 mS/cm | 201 | 3210.9 | blocked_qty | electrical-conductivity |  | gemini-assisted |  |
| edge-cases | 2026-06-01 | dissolved oxygen 4.0 mg/L | 201 | 7.8 | coded | dissolved-oxygen | 4.0 mg/L | curated-rules | critical dissolved-oxygen → veterinary/water-authority |
| edge-cases | 2026-06-01 | electrical conductivity 2.0 mS/cm | 201 | 7.5 | coded | electrical-conductivity | 2.0 mS/cm | curated-rules | high electrical-conductivity → public-health/veterinary/water-authority |
| edge-cases | 2026-06-01 | dissolved oxygen 4.01 mg/L | 201 | 6.0 | coded | dissolved-oxygen | 4.01 mg/L | curated-rules |  |
| edge-cases | 2026-06-01 | electrical conductivity 1.99 mS/cm | 201 | 6.6 | coded | electrical-conductivity | 1.99 mS/cm | curated-rules |  |
| edge-cases | 2026-06-01 | radon activity concentration 42.0 Bq/L | 201 | 5568.5 | no_code |  |  | gemini-assisted |  |
| edge-cases | 2026-06-01 | dissolved oxygen 6.2 quarts per fortnight | 201 | 3679.2 | blocked_qty | dissolved-oxygen |  | gemini-assisted |  |

## Bulletins through intake

- **oder-2022**: HTTP 201, 4 readings extracted in 24.6 s: Leitfähigkeit 2350.0 uS/cm → `electrical-conductivity`; Chlorki 1180.0 mg/l → `chloride`; Gelöster Sauerstoff 3.6 mg/l → `dissolved-oxygen`; Wassertemperatur 26.4 °C → `waterTemperature`. Declined: The note mentions a previous day conductivity value of 1200 uS/cm, which was excluded as it is historical context rather than a current measurement. / Angler report of dead fish over 12 km was excluded as it contains no quantitative environmental measurement.
- **walkerton-2000**: HTTP 201, 5 readings extracted in 9.4 s: free chlorine residual 0.0 mg/L → `no code`; Total coliforms 2400.0 CFU/100 mL → `coliforms`; Faecal coliforms 1600.0 CFU/100 mL → `coliforms`; Ammonium 1.8 mg/L → `ammonium`; Total suspended solids 42.0 mg/L → `tss`. Declined: Ammonium and Total suspended solids lack specific observation dates and site identifiers. / The note mentions heavy rain on 12 May, but no quantitative precipitation measurement is provided. / 'Ammonium' carried no usable timestamp; ingestion time recorded and flagged for reviewer correction. / 'Total suspended solids' carried no usable timestamp; ingestion time recorded and flagged for reviewer correction.
- **akerselva-2011**: HTTP 201, 4 readings extracted in 53.5 s: Fritt klor 4.1 mg/l → `no code`; oksygen 3.1 mg/l → `dissolved-oxygen`; ledningsevne 0.86 mS/cm → `electrical-conductivity`; vanntemperatur 3.1 °C → `waterTemperature`. Declined: The exact time of the chlorine measurement was not specified beyond 'kvelden 8. mars', so 21:00:00Z was used as a placeholder for the evening. / Site codes were assigned based on location names as none were provided in the text.
- **brixham-2024**: HTTP 201, 3 readings extracted in 10.6 s: Total coliforms 1250.0 CFU/100 mL → `coliforms`; Free chlorine residual 0.06 mg/L → `no code`; Total suspended solids 38.0 mg/L → `tss`. Declined: Cryptosporidium oocysts confirmed but no numerical value provided. / Timestamp for total suspended solids is date-only; converted to 00:00:00 UTC.

## Crosswalk suggestions (first three coded rows per scenario)

- oder-2022 `electrical-conductivity` → 87444-6 Electron [Electrical Conductivity] of Water (http://loinc.org), 468605001 Electrical conductivity meter (http://snomed.info/sct)
- oder-2022 `chloride` → 12530-2 Chloride [Moles/volume] in Water (http://loinc.org), 54494-0 Chloride [Mass/volume] in Water (http://loinc.org)
- oder-2022 `ndci` → no publishable candidate (an honest empty answer)
- milwaukee-1993 `tss` → no publishable candidate (an honest empty answer)
- milwaukee-1993 `tss` → no publishable candidate (an honest empty answer)
- milwaukee-1993 `tss` → no publishable candidate (an honest empty answer)
- walkerton-2000 `coliforms` → 23710009 Coliform mastitis (http://snomed.info/sct), 77309002 Coliform bacteria (http://snomed.info/sct)
- walkerton-2000 `coliforms` → 23710009 Coliform mastitis (http://snomed.info/sct), 77309002 Coliform bacteria (http://snomed.info/sct)
- walkerton-2000 `ammonium` → 38589-8 Ammonia [Mass/volume] in Air (http://loinc.org), 53500-5 Ammonia [Moles/volume] in Water (http://loinc.org)
- toledo-2014 `ndci` → no publishable candidate (an honest empty answer)
- toledo-2014 `mci` → no publishable candidate (an honest empty answer)
- toledo-2014 `ndci` → no publishable candidate (an honest empty answer)
- havelock-north-2016 `coliforms` → 23710009 Coliform mastitis (http://snomed.info/sct), 77309002 Coliform bacteria (http://snomed.info/sct)
- havelock-north-2016 `coliforms` → 23710009 Coliform mastitis (http://snomed.info/sct), 77309002 Coliform bacteria (http://snomed.info/sct)
- havelock-north-2016 `ammonium` → 38589-8 Ammonia [Mass/volume] in Air (http://loinc.org), 53500-5 Ammonia [Moles/volume] in Water (http://loinc.org)
- flint-2014 `lead-dissolved` → no publishable candidate (an honest empty answer)
- flint-2014 `lead-dissolved` → no publishable candidate (an honest empty answer)
- flint-2014 `lead-dissolved` → no publishable candidate (an honest empty answer)
- baia-mare-2000 `copper-dissolved` → no publishable candidate (an honest empty answer)
- baia-mare-2000 `zinc-dissolved` → no publishable candidate (an honest empty answer)
- baia-mare-2000 `dissolved-oxygen` → 469130006 Dissolved oxygen meter, line-powered (http://snomed.info/sct), 468651000 Dissolved oxygen meter, battery-powered (http://snomed.info/sct)
- ajka-2010 `ph` → 9481-3 pH of Water (http://loinc.org), 702230000 pH meter (http://snomed.info/sct)
- ajka-2010 `aluminium-dissolved` → no publishable candidate (an honest empty answer)
- ajka-2010 `ph` → 9481-3 pH of Water (http://loinc.org), 702230000 pH meter (http://snomed.info/sct)
- mar-menor-2021 `nitrate` → 9480-5 Nitrate [Mass/volume] in Water (http://loinc.org), 13616-8 Nitrite [Mass/volume] in Water (http://loinc.org)
- mar-menor-2021 `total-phosphates` → 38717-5 Phosphate [Mass/volume] in Air (http://loinc.org), 104868000 Phosphate, total measurement (http://snomed.info/sct)
- mar-menor-2021 `waterTemperature` → 438631006 Checking bath water temperature (http://snomed.info/sct), 285974007 Does control domestic water temperature (http://snomed.info/sct)
- akerselva-2011 `dissolved-oxygen` → 469130006 Dissolved oxygen meter, line-powered (http://snomed.info/sct), 468651000 Dissolved oxygen meter, battery-powered (http://snomed.info/sct)
- akerselva-2011 `ph` → 9481-3 pH of Water (http://loinc.org), 702230000 pH meter (http://snomed.info/sct)
- akerselva-2011 `dissolved-oxygen` → 469130006 Dissolved oxygen meter, line-powered (http://snomed.info/sct), 468651000 Dissolved oxygen meter, battery-powered (http://snomed.info/sct)
- seine-2024 `coliforms` → 23710009 Coliform mastitis (http://snomed.info/sct), 77309002 Coliform bacteria (http://snomed.info/sct)
- seine-2024 `coliforms` → 23710009 Coliform mastitis (http://snomed.info/sct), 77309002 Coliform bacteria (http://snomed.info/sct)
- seine-2024 `ammonium` → 38589-8 Ammonia [Mass/volume] in Air (http://loinc.org), 53500-5 Ammonia [Moles/volume] in Water (http://loinc.org)
- brixham-2024 `tss` → no publishable candidate (an honest empty answer)
- brixham-2024 `coliforms` → 23710009 Coliform mastitis (http://snomed.info/sct), 77309002 Coliform bacteria (http://snomed.info/sct)
- brixham-2024 `coliforms` → 23710009 Coliform mastitis (http://snomed.info/sct), 77309002 Coliform bacteria (http://snomed.info/sct)
- coimbra-citizen-2026 `foam` → no publishable candidate (an honest empty answer)
- coimbra-citizen-2026 `macrophytes` → no publishable candidate (an honest empty answer)
- coimbra-citizen-2026 `macroinvertebreates` → no publishable candidate (an honest empty answer)
- edge-cases `dissolved-oxygen` → 469130006 Dissolved oxygen meter, line-powered (http://snomed.info/sct), 468651000 Dissolved oxygen meter, battery-powered (http://snomed.info/sct)
- edge-cases `electrical-conductivity` → 87444-6 Electron [Electrical Conductivity] of Water (http://loinc.org), 468605001 Electrical conductivity meter (http://snomed.info/sct)
- edge-cases `dissolved-oxygen` → 469130006 Dissolved oxygen meter, line-powered (http://snomed.info/sct), 468651000 Dissolved oxygen meter, battery-powered (http://snomed.info/sct)

## Honesty

Every fixture value is synthetic and shaped around the published narrative in `docs/incidents.md`. The thresholds are a demonstration policy. Gemini output is non-deterministic; the deterministic pipeline is what `tests/test_incidents.py` gates.
