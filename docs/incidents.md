# Incident catalogue

Twelve real water-and-health incidents, reconstructed as runnable simulations, plus one
synthetic abuse-case fixture. Each one asks the same question:

> The evidence existed. Why did it not reach the people who could act on it in time —
> and which part of that is a data-and-standards problem a bridge like this can actually fix?

Every scenario in this document is **executed by CI**. `tests/test_incidents.py` drives all
thirteen fixtures through the real pipeline offline, so if a claim below stops being true,
a test fails with the scenario's name on it.

```bash
pytest tests/test_incidents.py -q          # 84 assertions, offline, no keys
python scripts/simulate.py --list          # what is available
python scripts/simulate.py                 # every scenario against a live bridge
```

## Contents

- [How to read a scenario](#how-to-read-a-scenario)
- [The output workflow](#the-output-workflow)
- [What the catalogue found](#what-the-catalogue-found)
- The incidents
  - [1. Oder River fish kill (2022)](#1-oder-river-fish-kill--poland--germany-julyaugust-2022)
  - [2. Milwaukee cryptosporidiosis (1993)](#2-milwaukee-cryptosporidiosis-outbreak--usa-marchapril-1993)
  - [3. Walkerton *E. coli* O157:H7 (2000)](#3-walkerton-e-coli-o157h7-outbreak--ontario-canada-may-2000)
  - [4. Toledo "do not drink" (2014)](#4-toledo-do-not-drink-advisory--ohio-usa-august-2014)
  - [5. Havelock North campylobacteriosis (2016)](#5-havelock-north-campylobacteriosis-outbreak--new-zealand-august-2016)
  - [6. Flint drinking-water crisis (2014–15)](#6-flint-drinking-water-crisis--michigan-usa-20142015)
  - [7. Baia Mare cyanide spill (2000)](#7-baia-mare-cyanide-spill-someştiszadanube--romania--hungary--serbia-2000)
  - [8. Ajka red-mud spill (2010)](#8-ajka-alumina-plant-red-mud-spill--hungary-october-2010)
  - [9. Mar Menor anoxic fish kill (2021)](#9-mar-menor-lagoon-anoxic-fish-kill--spain-august-2021)
  - [10. Akerselva chlorine release (2011)](#10-akerselva-chlorine-release--oslo-norway-march-2011)
  - [11. Seine bathing-water exceedances (2024)](#11-seine-bathing-water-exceedances--paris-france-julyaugust-2024)
  - [12. Brixham cryptosporidiosis (2024)](#12-brixham-cryptosporidiosis-outbreak--devon-uk-may-2024)
  - [13. Synthetic abuse cases](#13-synthetic-abuse-cases--sensor-faults-boundaries-and-unknown-inputs)
- [Precedents without fixtures](#precedents-without-fixtures)
- [Edge-case coverage matrix](#edge-case-coverage-matrix)
- [Terminology gaps this catalogue found](#terminology-gaps-this-catalogue-found)
- [Honesty statement](#honesty-statement)

---

## How to read a scenario

Every incident section has the same five parts.

| Part | What it is for |
|---|---|
| **What happened** | The published record, with sources. No claim here is ours. |
| **The signal that existed** | The measurement that was already being taken, and where it sat. |
| **The failure mode** | Which of fragmentation, latency, standards, or record integrity broke. |
| **What this bridge would and would not have changed** | Stated in both directions, deliberately. |
| **The simulation** | The fixture, the command, and the exact outcome CI enforces. |

The pipeline classifies every source row into exactly one of three outcomes, and the
distinction matters more than the counts:

| Outcome | Meaning |
|---|---|
| `coded` | An OAH coding **and** a normalised UCUM quantity. A reviewer may approve it. |
| `blocked_qty` | The concept is recognised, but the number is withheld — the unit does not resolve, or the value is outside its reviewed plausible range. **Approval is refused until a person corrects it.** |
| `no_code` | No curated match. Usually because the concept is absent from the OAH IG's temporary code system. The bridge refuses to guess. |

`blocked_qty` and `no_code` are not failures of the simulation. They are the product
working. A bridge that codes everything is a bridge that is lying about something.

---

## The output workflow

This is the sequence to run for a demo, a judging session, or a regression check.

### 1. Prove the logic offline — no keys, no network, ~2 seconds

```bash
pytest -q                              # 286 tests
pytest tests/test_incidents.py -q      # the 84 that are this catalogue
```

### 2. Prove the deployed system

```bash
uvicorn aquafhir.main:app --reload     # terminal 1
python scripts/simulate.py             # terminal 2
```

The harness ingests every fixture over real HTTP, approves what is approvable, **rejects
what is not with a written reason**, collects the alerts, and verifies the hash chain.
It exits non-zero if any scenario stops matching this document, so it works as a release
gate. On a clean database the full run reports:

```
Summary
  scenarios      13/13 matched the documented outcome
  alerts raised  46
  approved       67
  refused        22
  audit chain    VALID over 224 entries
  chain events   alert-created×46, mapping-approved×67, mapping-proposed×89, mapping-rejected×22
```

Useful variants:

```bash
python scripts/simulate.py oder-2022 -v      # one scenario, every row printed
python scripts/simulate.py --propose-only    # fill the queue, then decide by hand in the console
python scripts/simulate.py --brief           # also draft an advisory per alert (needs GEMINI_API_KEY)
```

### 3. Prove the review gate holds

`--propose-only` leaves everything `pending`. Open <http://localhost:8000>, and note that
nothing has been published: 89 proposals, zero Observations. There is no confidence value,
and no model, that changes this.

### 4. Prove the AI layer is bounded

With `GEMINI_API_KEY` set and `GEMINI_ASSIST_MODE=always`, re-run `oder-2022`. The German
label `Leitfähigkeit` moves from `no_code` to `coded`, carrying a `gemini-assisted`
proposer, a prompt hash, and the model's quoted evidence — and the published number
`2.35 mS/cm` is still computed by `coding-rules.yaml`, not by the model. Then delete the
key and re-run: everything except that one row behaves identically.

### 5. Prove the record is tamper-evident

Run the [Flint drill](#6-flint-drinking-water-crisis--michigan-usa-20142015). Editing one
stored reading turns `/api/v1/provenance/verify` from `valid: true` to
`first_invalid_sequence: 93` — it names the record, not just the fact of a change.

### 6. Capture the evidence

Numbers worth putting in the submission: readings ingested, coded, refused and why,
alerts by severity and audience, chain length and verification status, reviewer override
rate, and the list of concepts the OAH IG could not express.

---

## What the catalogue found

Building this catalogue surfaced four things that were not visible from the code alone.

**1. A sensor fault could raise a critical alert.** A dissolved-oxygen probe reporting
`-5.0 mg/L` — physically impossible — was coded at `0.99` confidence and raised a
**critical** alert routed to the veterinary and water-authority audiences. So did a `pH` of
`130.0` (a decimal typo for `13.0`) and a water temperature below absolute zero. Real
incident data is full of failed instruments, and an early-warning system that cries wolf on
them is worse than none. `coding-rules.yaml` now carries a reviewed `plausible_range` per
indicator, enforced in `ReviewedCodingAgent.normalize_unit` — the single point both the
curated and the Gemini-assisted paths route their arithmetic through. An implausible value
is withheld exactly like an unresolvable unit: no number, no publication, no alert, and
approval blocked until a person corrects it.

**2. The OAH IG is far larger than this repository was using.** The temporary code system
publishes **286 concepts**, not the handful this project started with — including
`nitrate`, `ammonium`, `tss`, `coliforms`, `lead-dissolved`, `mci`, and the full dissolved-
metals series. The curated catalog now covers 19 of them, every one verified against the
published code system and guarded by a test that fails if an unpublished code is ever
introduced.

**3. It also carries the human and animal legs of One Health.** `gastrointestinal`,
`campylobacter`, `cryptosporidium`, `hospitalization-*` and `causes-of-death` are human-health
indicators in the same code system; `fish`, `amphibians`, `birds`, `ticks` and `diptera` are
the animal leg. This bridge currently publishes only the environmental leg, through
`observation-indicators-oah`. Closing the loop needs the IG's second profile,
`observation-health-measure-oah` — see [Terminology gaps](#terminology-gaps-this-catalogue-found).

**4. Every incident here turned on at least one indicator no standard can express.**
Turbidity, free chlorine residual, cyanide, microcystin and enterococci are absent from the
OAH temporary code system; dissolved oxygen and water temperature in water are absent from
environmental LOINC. The bridge refuses all of them rather than mapping to a neighbour. That
refusal is a **findable, exportable list of gaps to submit to the IG and to LOINC**, which is
a more useful Track 7 output than a dashboard.

---

## 1. Oder River fish kill — Poland / Germany, July–August 2022

**What happened.** A *Prymnesium parvum* ("golden algae") bloom, triggered by elevated
salinity combined with heat and low flow, killed fish and molluscs along the Polish–German
border stretch of the Oder. Reported tolls vary by method: IGB put it at up to 1,000 tonnes
of fish, mussels and snails; the German environment ministry reported at least 300 tonnes of
dead fish recovered; Poland recorded 249 tonnes physically collected in its own territory.
Polish authorities confirmed toxic algae as the cause on 29 September 2022.

**The signal that existed.** Polish water authorities knew of dead fish by late July and had
unusual test results between 26 and 28 July. German authorities sampled near Frankfurt (Oder)
on 6 August and found extremely elevated salt levels. Copernicus Sentinel-2 already showed the
bloom.

**The failure mode — latency and fragmentation, across a border.** Polish authorities
reportedly did not inform the prime minister until 9–10 August, roughly two weeks after the
first anomalous readings. German officials said they were not notified and learned of it from
anglers and residents on 9 August. Two national monitoring systems, two languages, two
schemas, and no shared machine-readable representation of "this reading crossed a threshold
that matters to you."

**What this bridge would and would not have changed.** It would have compressed the
notification path: the 27 July conductivity reading is a threshold crossing that routes to
public-health, veterinary **and** water-authority audiences in one step, in a FHIR resource a
German consumer can read without a bilateral agreement about CSV columns. It would **not**
have prevented the fish kill. The industrial discharge and the ecological trigger are an
enforcement and policy problem; earlier evidence buys response time, not immunity.

**The simulation.**

```bash
python scripts/simulate.py oder-2022 -v
```

11 rows → 9 `coded`, 2 `no_code`. Five alerts: `electrical-conductivity` (high),
`chloride` (high), `ndci` (high), `dissolved-oxygen` (critical), `waterTemperature`
(moderate), routed to all three audiences.

- `Leitfähigkeit` at `2350 uS/cm` scores **0.31** against every curated alias and is refused
  by the deterministic path. This is the row the Gemini co-pilot exists for — set
  `GEMINI_API_KEY` and it becomes `coded` at `2.35 mS/cm`, computed from the reviewed
  conversion factor, never by the model.
- `chlorki` — the Polish label — matches `chloride` on string similarity alone. No model needed.
- `Prymnesium parvum cell count` is refused on the indicator axis: the OAH IG has
  no code for a species cell count. The biodiversity crosswalk still identifies
  the organism as GBIF `7513065` *Prymnesium parvum* N.Carter at 99% confidence,
  so the console reports the identification and the standards gap together
  rather than losing both.
- The 9 August mercury reading is the false lead that early reporting chased. It codes
  cleanly at `0.35 ug/L` and does **not** cross the demonstration threshold — the system
  neither hides it nor amplifies it.

Run the free-text path with `data/incidents/oder-2022.bulletin.txt` against
`POST /api/v1/intake`: the anglers' dead-fish report carries no measurement and is returned
as a warning, never as an extraction.

**Sources.**
[IGB Leibniz Institute](https://www.igb-berlin.de/en/news/oder-disaster) ·
[Umweltbundesamt — the Oder under stress](https://www.umweltbundesamt.de/en/topics/water/rivers/the-river-under-stress) ·
[France 24, 15 Aug 2022](https://www.france24.com/en/europe/20220815-mass-fish-deaths-in-german-polish-river-probably-caused-by-chemical-waste) ·
[Balkan Insight, 15 Aug 2022](https://balkaninsight.com/2022/08/15/poland-struggles-to-contain-oder-river-environmental-catastrophe/) ·
[Völkerrechtsblog — the cross-border notification duty](https://voelkerrechtsblog.org/dead-fish-in-the-river-oder/) ·
[Washington Post, 13 Aug 2022](https://www.washingtonpost.com/world/2022/08/13/poland-oder-river-mercury-fish/)

---

## 2. Milwaukee cryptosporidiosis outbreak — USA, March–April 1993

**What happened.** The largest documented waterborne disease outbreak in United States
history: an estimated 403,000 people ill and around 69 deaths, traced to *Cryptosporidium*
passing through the Howard Avenue water purification plant.

**The signal that existed.** Treated-water turbidity at the southern plant had not exceeded
0.4 NTU in the ten years to January 1993. From 23 March to 1 April it was consistently at or
above 0.45 NTU, peaking at 1.7 NTU on 28 and 30 March. Investigators later found the
turbidity series tracked gastroenteritis emergency-room visits at a lag of 5–6 days —
exactly the *Cryptosporidium* incubation period.

**The failure mode — the data was collected and not acted on.** This is the purest case in
the catalogue. Nothing was missing. A ten-year baseline and a tenfold excursion sat in an
operations log while the outbreak ran.

**What this bridge would and would not have changed.** It would have made the excursion a
routed, machine-readable event with a public-health audience attached, rather than a number
in a plant log. It would **not** have detected *Cryptosporidium* — turbidity is a proxy for
filtration performance, and reading it as a pathogen signal is a judgement a person makes.

**The simulation.**

```bash
python scripts/simulate.py milwaukee-1993 -v
```

6 rows → 4 `coded`, **2 `no_code`**. One alert: `tss` (high) → public-health,
water-authority.

The two refusals are the finding. **Turbidity, the indicator this outbreak actually turned
on, has no code in the OAH temporary code system.** The bridge will not map it to a
neighbouring concept. Total suspended solids is a defensible proxy the IG *does* define, and
the fixture carries both so a reviewer can see the substitution being made rather than
inheriting it silently.

**Sources.**
[MacKenzie et al., *NEJM* 331:161 (1994)](https://www.nejm.org/doi/full/10.1056/NEJM199407213310304) ·
[Corso et al., *Emerg Infect Dis* — cost of illness](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2957981/) ·
[Milwaukee's crypto outbreak: investigation and recommendations, *JAWWA*](https://awwa.onlinelibrary.wiley.com/doi/10.1002/j.1551-8833.1996.tb06615.x) ·
[NCBI — Lessons from Waterborne Disease Outbreaks](https://www.ncbi.nlm.nih.gov/books/NBK28459/)

---

## 3. Walkerton *E. coli* O157:H7 outbreak — Ontario, Canada, May 2000

**What happened.** Cattle manure washed into the shallow aquifer feeding Well 5 after heavy
rain in late April and early May. Contamination entered the system on or shortly after
12 May 2000. Over 2,000 people fell ill and seven died. The 2002 O'Connor inquiry concluded
the outbreak could have been prevented by proper chlorination.

**The signal that existed.** The laboratory result reached the utility. Chlorine residual
was not being monitored daily.

**The failure mode — record integrity and notification, together.** The inquiry found
improper operating practices at the Public Utilities Commission: wells operated without
chlorination, daily residuals not monitored, and **false annual reports submitted**. The
inquiry found the outbreak would have been prevented by continuous chlorine residual and
turbidity monitoring, and that up to 400 illnesses could have been avoided had residuals
been monitored daily and the authorities notified.

**What this bridge would and would not have changed.** Two things, precisely. Every reading
is hash-chained on ingestion, so a later alteration of the record is detectable and points
at the altered entry. And a coliform exceedance routes to the health unit as a standards-based
event rather than depending on one operator choosing to place a call. It would **not** have
chlorinated the well, and it cannot compel an operator to take a sample that was never taken.

**The simulation.**

```bash
python scripts/simulate.py walkerton-2000 -v
```

5 rows → 4 `coded`, 1 `no_code`. Three alerts: `coliforms` (critical), `ammonium` (high),
`tss` (high) → all three audiences.

Free chlorine residual is refused: **no OAH code exists for it**, which is a striking gap
given it is the single most important operational indicator in drinking-water treatment.
The fixture also carries the two customary spellings of the same unit — `{cfu}/100mL` and
`CFU/100mL` — both normalising to the UCUM `{cfu}/dL`, because 100 mL is exactly one
decilitre.

**Tamper drill.** After running this scenario, edit one stored proposal payload directly in
SQLite and re-check `/api/v1/provenance/verify`. See the [Flint
drill](#6-flint-drinking-water-crisis--michigan-usa-20142015) for the exact commands.

**Sources.**
[Report of the Walkerton Inquiry (O'Connor, 2002)](https://www.ontario.ca/page/walkerton-inquiry-reports) ·
[CBC — highlights of the Walkerton inquiry report](https://www.cbc.ca/news/canada/highlights-of-the-walkerton-inquiry-report-1.867604) ·
[Hrudey et al., *Can J Civ Eng* — lessons compared with other outbreaks](https://cdnsciencepub.com/doi/10.1139/s02-031) ·
[Drinking water contamination in Walkerton, Ontario (PubMed 12638997)](https://pubmed.ncbi.nlm.nih.gov/12638997/)

---

## 4. Toledo "do not drink" advisory — Ohio, USA, August 2014

**What happened.** On 2 August 2014 Toledo issued a "do not drink" advisory and declared a
state of emergency after microcystin was detected in finished water above the WHO guideline
of 1 µg/L. More than 400,000 residents were without potable water for over two days; the
advisory lifted on 4 August. A *Microcystis* bloom in western Lake Erie had overwhelmed the
treatment plant, and operators could not adjust the treatment regime proactively.

**The signal that existed.** The bloom was visible in satellite imagery days ahead. NOAA had
been publishing Lake Erie HAB bulletins. The gap was between "a bloom is visible from orbit"
and "this specific intake has a toxin problem tonight."

**The failure mode — standards and coupling.** Earth-observation products and drinking-water
operations live in different systems with different vocabularies. Nothing turned a satellite
index into an event a plant operator's system could subscribe to.

**What this bridge would and would not have changed.** Both satellite indices in the fixture
cross their thresholds on 1 August, one day before the advisory, and route to public-health,
veterinary and water-authority audiences as OAH-coded FHIR Observations against the same
`Location` as the plant's own samples. It would **not** have replaced the toxin assay. A
chlorophyll index says "investigate", never "the water is unsafe" — which is exactly why
the advisory drafting step is marked `draft` and disclaimed.

**The simulation.**

```bash
python scripts/simulate.py toledo-2014 -v
```

7 rows → 6 `coded`, 1 `no_code`. Four alerts: `ndci` (high), `mci` (high),
`total-phosphates` (moderate), `waterTemperature` (moderate).

Microcystin-LR — the substance the advisory was actually issued on — is refused. **No OAH
code exists for it.** Two independent bloom indices, NDCI and MCI, both cross on the same
date from the same satellite source, which is the corroboration case: one index crossing is
a candidate, two agreeing is a finding.

**Sources.**
[Steffen et al. — ecophysiological examination of the 2014 Lake Erie *Microcystis* bloom](https://ciglr.seas.umich.edu/wp-content/uploads/2017/09/Steffen_etal.pdf.pdf) ·
[Ohio EPA / Great Lakes Commission — Toledo advisory and response](https://www.glc.org/wp-content/uploads/2016/10/2014-glc-annmtg-Gebhardt-HABDrinkingWaterLakeErie.pdf) ·
[Circle of Blue, 3 Aug 2014](https://www.circleofblue.org/2014/world/toledo-issues-emergency-warning-residents-drink-water/) ·
[NRDC — Toledo's blooming algae crisis](https://www.nrdc.org/stories/toledos-blooming-algae-crisis)

---

## 5. Havelock North campylobacteriosis outbreak — New Zealand, August 2016

**What happened.** Recognised on 12 August 2016. An estimated 5,500 of the town's residents
fell ill, 45 were hospitalised, and the Government Inquiry found a possible contribution to
four deaths. Sheep faeces were the likely source of the *Campylobacter*: heavy rain carried
contaminated water into a pond about 90 metres from the bore head, and it entered the
groundwater and was pumped, untreated, into the network.

**The failure mode — a One Health pathway nobody was watching as one thing.** Animal health,
rainfall, aquifer vulnerability and human illness were each somebody's responsibility and
nobody's single view. The Stage 2 inquiry made 51 recommendations, including universal
treatment of drinking water.

**What this bridge would and would not have changed.** This is the catalogue's clearest
demonstration of the routing claim: a single coliform exceedance at the bore field routes to
**veterinary and public-health audiences simultaneously**, because the policy says the
pathway crosses both — not because someone remembered to forward an email. It would **not**
have chlorinated the bore, and it does not predict rainfall-driven ingress.

**The simulation.**

```bash
python scripts/simulate.py havelock-north-2016 -v
```

6 rows → 5 `coded`, 1 `no_code`. Four alerts: `coliforms` (critical), `ammonium` (high),
`nitrate` (high), `tss` (high) → all three audiences.

The fixture deliberately samples the pond 90 m from the bore head as a distinct
`Location`, so the alert carries the spatial relationship rather than flattening two places
into one site. Free chlorine residual is refused again — the same OAH gap as Walkerton, in
an incident where the absence of chlorination was the finding.

**Sources.**
[Government Inquiry into Havelock North Drinking Water — Stage 1 report](https://www.dia.govt.nz/government-inquiry-into-havelock-north-drinking-water-report---part-1---overview) ·
[Stage 2 report](https://www.dia.govt.nz/Report-of-the-Havelock-North-Drinking-water-Inquiry---Stage-2) ·
[Public Health Communication Centre — a wake-up call](https://www.phcc.org.nz/briefing/havelock-north-drinking-water-inquiry-wake-call-rebuild-public-health-new-zealand) ·
[Australian Water Association — lessons from the outbreak](https://www.awa.asn.au/resources/latest-news/community/public-health/lessons-from-nzs-2016-havelock-north-water-supply-outbreak)

---

## 6. Flint drinking-water crisis — Michigan, USA, 2014–2015

**What happened.** Flint switched its drinking-water source to the Flint River on 25 April
2014 without adequate corrosion control. Lead leached from service lines. The switch also
coincided with a Legionnaires' disease outbreak that killed 12 and sickened at least 87
between June 2014 and October 2015; the outbreak subsided within weeks of the city
switching back to Detroit water on 16 October 2015.

**The failure mode — the record itself was altered.** In the regulatory Lead and Copper Rule
round, 71 samples were collected where 100 were required, and the final report accounted for
only 69 of the 71. The two discarded samples were high-lead. With them, the city was over
the federal 15 ppb action level; without them, under it. The state said the samples were
invalidated per federal regulation; the then-assistant supervisor of the Flint water plant
disputed the official account.

**What this bridge would and would not have changed.** This is the tamper-evidence case, and
it is worth being precise about what a hash chain does. It cannot stop anyone from excluding
a sample. What it does is make the exclusion **visible and attributable**: the reading is
hash-chained the moment it is ingested, before any decision, and a later deletion or edit
breaks verification at a named sequence number. The argument moves from "were these samples
valid?" to "here is the record of what was received and who decided what about it." It would
**not** have replaced the lead service lines.

**The simulation.**

```bash
python scripts/simulate.py flint-2014 -v
```

6 rows → 5 `coded`, 1 `no_code`. One alert type, four times: `lead-dissolved` (critical) →
public-health, water-authority.

Lead arrives in `mg/L` and normalises to `ug/L` through a reviewed factor of 1000 — the
`0.104 mg/L` sample becomes `104 ug/L`. The citizen-collected Virginia Tech sample
(`0.158 mg/L`) enters through the identical path as the agency samples, carrying
`source_type=citizen`; the pipeline does not privilege one over the other, and the reviewer
can see which is which. Free chlorine residual is refused a third time.

**The tamper drill.** Run the scenario, then:

```bash
sqlite3 aquafhir.db \
  "UPDATE provenance
      SET payload = replace(payload, '\"value\":0.104', '\"value\":0.004')
    WHERE event_type = 'mapping-proposed' AND payload LIKE '%0.104%';"

curl -s http://localhost:8000/api/v1/provenance/verify
```

Before: `{"valid": true, "entries_checked": 224, "first_invalid_sequence": null}`
After: `{"valid": false, "entries_checked": 93, "first_invalid_sequence": 93}`

It names the record. Restore it by re-running the simulation on a fresh database.

**Sources.**
[Pauli, *WIREs Water* — the Flint water crisis](https://wires.onlinelibrary.wiley.com/doi/abs/10.1002/wat2.1420) ·
[Zahran et al., *PNAS* — assessment of the Legionnaires' outbreak](https://www.pnas.org/doi/10.1073/pnas.1718679115) ·
[Goovaerts, *Environ Sci Technol* — evaluating water lead levels](https://pubs.acs.org/doi/10.1021/acs.est.8b00791) ·
[CNN, 14 Jan 2016 — the two discarded samples](https://www.cnn.com/2016/01/14/us/flint-water-investigation/index.html) ·
[Michigan Radio — an expert on the changed report](https://michiganradio.org/post/expert-says-michigan-officials-changed-flint-lead-report-avoid-federal-action) ·
[NRDC — everything you need to know](https://www.nrdc.org/stories/flint-water-crisis-everything-you-need-know)

---

## 7. Baia Mare cyanide spill, Someş–Tisza–Danube — Romania / Hungary / Serbia, 2000

**What happened.** On 30 January 2000 a retaining wall failed at the Aurul gold processing
plant near Baia Mare after heavy rain and snowmelt, releasing about 100,000 m³ of
cyanide-contaminated water containing roughly 100 tonnes of cyanides. The plume travelled
the Someş into the Tisza and then the Danube. Cyanide in the Someş exceeded permitted levels
by over 700 times. Heavy metals — copper, zinc, lead — travelled with it. It has been called
Europe's worst environmental disaster since Chernobyl.

**The failure mode — a plume crossing three countries faster than the paperwork.** The
Danube basin does have an Accident Emergency Warning System. What it did not have was a
shared machine-readable representation in which a Romanian reading and a Hungarian one are
the same kind of object.

**What this bridge would and would not have changed.** It would have made every downstream
sample a resource against a shared `Location` and `Organization` model, so the plume's
progression is one queryable series rather than three national ones. It would **not** have
contained the spill, and — see below — it cannot currently express the contaminant at all.

**The simulation.**

```bash
python scripts/simulate.py baia-mare-2000 -v
```

8 rows → 5 `coded`, **3 `no_code`**. Three alerts: `copper-dissolved` (high),
`zinc-dissolved` (high), `dissolved-oxygen` (critical) → veterinary, water-authority.

**The bridge cannot code cyanide.** Total cyanide is refused three times, once at each
country's monitoring point, because the OAH temporary code system has no term for it. The
alert that does fire is carried entirely by the co-released metals and the oxygen collapse.
This is the most uncomfortable result in the catalogue and the most useful one: the system
tells you plainly that the standard cannot express the thing that mattered, instead of
mapping it to something adjacent and looking complete.

**Sources.**
[UNEP/OCHA Baia Mare assessment mission](https://reliefweb.int/report/romania/cyanide-spill-baia-mare-romania-unepocha-assessment-mission-advance-copy) ·
[Report of the International Task Force, Dec 2000](https://wwfint.awsassets.panda.org/downloads/baia_mare_task_force_report_2000.pdf) ·
[WWF — ecological effects of mining spills in the Tisza](https://wwfeu.awsassets.panda.org/downloads/Tisza_Cyanide_Report.pdf) ·
[French ARIA database record FD 17265](https://www.aria.developpement-durable.gouv.fr/wp-content/files_mf/FD_17265_baia_mare_2000_ang.pdf) ·
[ICPDR — Accident Emergency Warning System](https://www.icpdr.org/tasks-topics/tasks/accident-prevention-control/accident-emergency-warning-system)

---

## 8. Ajka alumina plant red-mud spill — Hungary, October 2010

**What happened.** On 4 October 2010 roughly one million cubic metres of highly alkaline red
sludge escaped from reservoir 10 at the MAL AG alumina plant at Ajka — the largest documented
release of alumina-industry by-products into the environment. Ten people died and at least
200 were injured. Forty square kilometres were made barren, life in the Marcal was
extinguished, and the sludge reached the Rába and eventually the Danube. The material was
around pH 12–13; gypsum dosing was used to bring the pH down.

**The failure mode — an acute, fast-moving excursion in a parameter with a hard physical
ceiling.** pH cannot exceed 14. It is exactly the kind of value where a transcription error
and a genuine emergency look similar in a spreadsheet.

**What this bridge would and would not have changed.** Downstream authorities on the Rába and
Danube would have had a routed critical alert on the pH excursion as it propagated. It would
**not** have prevented the reservoir failure or the deaths, which happened in minutes at the
source.

**The simulation.**

```bash
python scripts/simulate.py ajka-2010 -v
```

7 rows → 6 `coded`, **1 `blocked_qty`**. Three alerts: `ph` (critical),
`aluminium-dissolved` (high), `dissolved-oxygen` (critical) → all three audiences.

Three distinct behaviours worth watching:

- **The plausible-range guard.** Row 3 is `pH 130.0` — a deliberate decimal typo for `13.0`.
  It is *coded* (the concept is recognised) but its quantity is **withheld**, so it publishes
  nothing and raises nothing until a person fixes it. Before this guard existed it went
  through at `0.99` confidence.
- **Two rules on one code.** The policy carries `ph-alkaline` (≥ 9.0) and `ph-acidic`
  (≤ 5.5). They share the code `ph`, so they need distinct rule ids, or two rules that fire
  together would collide onto one alert id and the second would be silently dropped by the
  repository's `INSERT OR IGNORE`. `tests/test_incidents.py` asserts this.
- **Dilution.** By Győr on the Danube, pH is 8.4 and aluminium is 310 µg/L. The pH does not
  alert; the aluminium still does. The policy is doing spatial discrimination, not blanket
  escalation.

**Sources.**
[Ruyters et al., *Environ Sci Technol* — the red mud accident in Ajka](https://pubs.acs.org/doi/abs/10.1021/es104005r) ·
[Gelencsér et al. — characterization and potential health effects of fugitive dust](https://www.researchgate.net/publication/49797824_The_Red_Mud_Accident_in_Ajka_Hungary_Characterization_and_Potential_Health_Effects_of_Fugitive_Dust) ·
[ICPDR — accident at the Ajka alumina plant](https://www.icpdr.org/tasks-topics/tasks/accident-prevention-control/accident-emergency-warning-system/accident-ajka) ·
[UNECE conference report on the Ajka red sludge reservoir disaster](https://preparecenter.org/wp-content/uploads/2021/04/5-1Conference_UNECE_Hungary_red_mud_disaster_CD.pdf) ·
[Advances in understanding environmental risks of red mud, *J Sustain Metall*](https://link.springer.com/article/10.1007/s40831-016-0050-z)

---

## 9. Mar Menor lagoon anoxic fish kill — Spain, August 2021

**What happened.** In August 2021 around five tonnes of fish and crustaceans washed up on the
shores of La Manga in the Mar Menor, Europe's largest saltwater lagoon — 1.5 tonnes more than
the October 2019 event that had been the worst until then. The cause is decades of nitrate
runoff from a 60,000-hectare agricultural catchment driving extreme eutrophication, algal
blooms and oxygen depletion. Spain's environment ministry attributed 17% of the nitrogen in
the Mar Menor aquifer to pig farms in the drainage basin. The lagoon was granted legal
personhood in 2022.

**The failure mode — a slow-onset chain that only looks like an emergency at the end.**
Nutrients, heat, bloom, anoxia, fish kill. Each link was measurable years ahead. None of them
individually reads as an emergency.

**What this bridge would and would not have changed.** It is the one scenario where the OAH
vocabulary covers the entire causal chain, so the full sequence is expressible as one series
of comparable resources. It would **not** have stopped the nitrate. That is agricultural
policy, and the data layer has been telling that story for two decades already.

**The simulation.**

```bash
python scripts/simulate.py mar-menor-2021 -v
```

6 rows → **6 `coded`, 0 refused**. Six alerts — the full chain: `nitrate` (high),
`total-phosphates` (moderate), `waterTemperature` (moderate), `ndci` (high),
`dissolved-oxygen` (critical), `electrical-conductivity` (high).

This is also the scenario that exposes a **real weakness in the demonstration policy**, and
it is left in deliberately. The conductivity rule (≥ 2.0 mS/cm) was written for a freshwater
river. The Mar Menor is hypersaline at around 68 mS/cm *by nature*. The alert fires on a
normal condition. A production deployment needs site-specific policy, not one global
threshold — which is why `thresholds.yaml` is versioned, separate from the terminology, and
stamped `demo-not-for-operational-use`.

**Sources.**
[European Parliament PETI fact-finding visit to Mar Menor (briefing)](https://www.europarl.europa.eu/cmsdata/245205/BRIEFING.pdf) ·
[The Local ES — five stats on the 2021 fish kill](https://www.thelocal.es/20210824/five-stats-to-understand-why-spains-mar-menor-is-full-of-dead-fish/) ·
[Phys.org — how nutrients poisoned the lagoon](https://phys.org/news/2019-12-spain-nutrients-poisoned-europe-largest.html) ·
[Geographical — saving Mar Menor](https://geographical.co.uk/science-environment/saving-mar-menor-europes-largest-salt-lagoon) ·
[Chlorophyll-a mapping in the Mar Menor with Sentinel-2 (arXiv)](https://arxiv.org/pdf/2510.09736)

---

## 10. Akerselva chlorine release — Oslo, Norway, March 2011

**What happened.** In March 2011 roughly 6,000 litres of chlorine solution entered the
Akerselva from a water treatment facility, linked to an error in the lines connecting two
chlorine tanks. Dead fish appeared along the river's whole route through Oslo. Thirty years
of restoration work on the river was undone in a day; the river was described as effectively
dead, with experts estimating at least two years before it could sustain life again. Around
700,000 salmon and sea trout fry were subsequently released and the benthic community
gradually returned.

**Why this one matters most for OneAquaHealth.** Oslo is one of the five pilot cities in the
OneAquaHealth project (with Coimbra, Toulouse, Benevento and Gent), and the Akerselva is
precisely the kind of **urban stream running through a dense city** the project studies —
not a transboundary river. The OAH IG's own example instances include Oslo monitoring sites.
This is the scenario closest to the project's actual subject matter.

**The failure mode — an operator's own release, into their own river, detected by sight.**
The utility that caused it also ran the monitoring. Everyone downstream — anglers, dog
walkers, the city's ecologists — found out by looking at the water.

**What this bridge would and would not have changed.** The downstream oxygen collapse routes
to veterinary and water-authority audiences from a site-resolved reading, while the upstream
site stays quiet — the operator's own incident becomes an event other parties can subscribe
to rather than one they must be told about. It would **not** have prevented a plumbing error.

**The simulation.**

```bash
python scripts/simulate.py akerselva-2011 -v
```

6 rows → 5 `coded`, 1 `no_code`. One alert: `dissolved-oxygen` (critical) → veterinary,
water-authority.

- **Free chlorine residual — the actual cause — is refused.** Fourth appearance of the same
  OAH gap, and here it is not an operational nicety but the contaminant itself.
- Upstream at Nydalen: oxygen 9.8 mg/L, unremarkable. Downstream at Vaterland: 3.1 mg/L,
  critical. Same river, same day, different `Location`, different outcome.
- The Norwegian bulletin (`data/incidents/akerselva-2011.bulletin.txt`) reports dead trout
  and benthic invertebrates with **no count**. Through `POST /api/v1/intake` that becomes a
  warning, never an extraction. The bridge does not invent a number for an observation
  someone made with their eyes.

**Sources.**
[Views and News from Norway — "Catastrophe hits historic river" (9 Mar 2011)](https://www.newsinenglish.no/2011/03/09/catastrophe-hits-historic-river/) ·
[Norway Today — the river's recovery and restocking](https://norwaytoday.info/news/now-can-fish-akerselva/) ·
[OneAquaHealth — project overview and pilot cities](https://www.oneaquahealth.eu/) ·
[SYNYO — OneAquaHealth launch, five European cities](https://www.synyo.com/news/oneaquahealth-ambitious-project-launched-to-protect-urban-aquatic-ecosystems-for-advancing-one-health/) ·
[University of Oslo — OneAquaHealth project page](https://www.med.uio.no/helsam/english/research/projects/oneaquahealth/)

---

## 11. Seine bathing-water exceedances — Paris, France, July–August 2024

**What happened.** Water quality in the Seine repeatedly failed to meet World Triathlon's
thresholds during the run-up to and duration of the Paris 2024 Olympics. Pre-Olympic test
events were cancelled or converted to duathlons. Heavy rain on the night of the opening
ceremony pushed bacterial counts above acceptable levels and the men's triathlon was
postponed by a day. Belgium withdrew its triathlon team after a competitor was hospitalised.

**The failure mode — two sources measuring the same water with different methods and
disagreeing.** World Triathlon's inland thresholds are ≤ 500 CFU/100 mL *E. coli* for
"excellent" and ≤ 1000 for "sufficient". Independent testing by Fluidion reported values just
under 3400 MPN/100 mL between early April and late May — more than three times the level
needed for "good". MPN (most probable number) and CFU (colony forming units) are **different
estimators of different things**, and the public discussion frequently treated them as
interchangeable.

**What this bridge would and would not have changed.** It refuses to make that error. It
would **not** have cleaned the Seine, and it does not adjudicate which method is right — it
makes the disagreement visible to a person instead of resolving it silently in a conversion
table.

**The simulation.**

```bash
python scripts/simulate.py seine-2024 -v
```

6 rows → 4 `coded`, **1 `blocked_qty`**, 1 `no_code`. One alert: `coliforms` (critical) →
all three audiences.

- **The unit conflict.** Rows 1 and 2 are the same site at the same instant, reported by two
  sources, differing by more than threefold. The `CFU/100mL` row normalises to
  `980 {cfu}/dL`. The `MPN/100mL` row is **coded but its quantity is withheld**, because MPN
  is deliberately absent from the conversion table in `coding-rules.yaml`. Adding a factor of
  1.0 there would be a one-line change that silently equates two incompatible estimators —
  which is exactly the class of error this project exists to prevent. A reviewer decides.
- **Enterococci is refused.** The Bathing Water Directive's other mandatory indicator has no
  OAH code.
- The 1 August reading (220 CFU/100 mL) is below threshold and raises nothing, which is the
  "the alert clears" case.

**Sources.**
[World Triathlon — Paris 2024 water quality update and thresholds](https://triathlon.org/news/paris-2024-olympic-games-triathlon---update-water-quality) ·
[CNN, 18 Jun 2024 — Fluidion readings vs official testing](https://www.cnn.com/2024/06/18/sport/paris-olympics-seine-triathlon-bacteria-intl/) ·
[CBS News — the postponement](https://www.cbsnews.com/news/paris-olympic-triathlon-seine-river-bacteria-e-coli-impacted-postponed-pollution-challenge-tony-estangue) ·
[*Sports Med Open* / PMC — ethical lessons from the Seine](https://pmc.ncbi.nlm.nih.gov/articles/PMC11611586/) ·
[EU Bathing Water Directive 2006/7/EC](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32006L0007)

---

## 12. Brixham cryptosporidiosis outbreak — Devon, UK, May 2024

**What happened.** From 14 May to 8 July 2024, an outbreak of cryptosporidiosis in Brixham,
south Devon, produced 118 laboratory-confirmed cases and over 1,000 suspected ones; two
people were hospitalised. A boil water notice was issued on 15 May, initially covering Alston
and Hillhead and reaching about 16,000–17,000 properties at its height; for some properties
it stayed in force for 54 days. South West Water attributed the likely cause to a broken
valve on private property. The outbreak cost Pennon around £16 million, of which £3.5 million
was customer compensation. The Drinking Water Inspectorate subsequently prosecuted South West
Water under s70(1) of the Water Industry Act 1991.

**The failure mode — residents knew before the utility's system did.** Illness reports from
residents preceded the confirmed water-quality finding. Citizen-generated signal was the
earliest indicator, and it had no route into the operational data model.

**Why this matters for OneAquaHealth.** The project's citizen-science app is a core
deliverable. This incident is the argument for treating a citizen report as a first-class
ingestion path with the same provenance as an agency sample — which is what
`source_type=citizen` and the free-text intake surface are for.

**What this bridge would and would not have changed.** It gives a citizen report and a
laboratory result the same shape, the same audit trail, and the same review queue, so the
earlier signal is not structurally second-class. It would **not** have fixed the valve, and
it does not detect *Cryptosporidium*.

**The simulation.**

```bash
python scripts/simulate.py brixham-2024 -v
```

5 rows → 4 `coded`, 1 `no_code`. Two alerts: `coliforms` (critical), `tss` (high).

Free chlorine residual at 0.06 mg/L — a failing residual — is refused for the fifth time in
this catalogue. The 20 May TSS reading (12.0 mg/L) is a recovery value below threshold and
correctly raises nothing.

Run `data/incidents/brixham-2024.bulletin.txt` through `POST /api/v1/intake`: the confirmed
*Cryptosporidium* oocysts are reported with **no count**, and must come back as a warning
rather than a fabricated number.

**Sources.**
[UKHSA / Wikipedia summary of the Devon cryptosporidiosis outbreak](https://en.wikipedia.org/wiki/Devon_cryptosporidiosis_outbreak) ·
[ITV News — a timeline of events, one year on](https://www.itv.com/news/westcountry/2025-05-14/water-parasite-outbreak-one-year-on-a-timeline-of-events) ·
[South West Water — lessons following the outbreak](https://www.southwestwater.co.uk/about-us/latest-news/we-continue-to-learn-lessons-following-the-cryptosporidium-outbreak-in-brixham) ·
[Drinking Water Inspectorate — prosecution of South West Water Ltd](https://www.dwi.gov.uk/30-september-2025-prosecution-of-south-west-water-limited-for-s701-offences-under-the-water-industry-act-1991)

---

## 13. Synthetic abuse cases — sensor faults, boundaries, and unknown inputs

Not an incident. This is the fixture to run **first** after changing `coding.py`,
`thresholds.py`, or either YAML file.

```bash
python scripts/simulate.py edge-cases -v
```

10 rows → 4 `coded`, **5 `blocked_qty`**, 1 `no_code`. Two alerts, both from the boundary
rows.

| Row | Input | Expected | Why it is here |
|---|---|---|---|
| 1 | dissolved oxygen `-5.0 mg/L` | `blocked_qty` | Physically impossible. **Used to raise a `critical` alert to veterinary and water-authority at 0.99 confidence.** |
| 2 | pH `130.0` | `blocked_qty` | Decimal typo for 13.0. pH cannot exceed 14. |
| 3 | water temperature `-400.0 Cel` | `blocked_qty` | Below absolute zero. |
| 4 | conductivity `999999.0 mS/cm` | `blocked_qty` | Absurd magnitude — a stuck or overflowed register. |
| 5 | dissolved oxygen `4.0 mg/L` | alert fires | `lte 4.0` must be **inclusive** at the boundary. |
| 6 | conductivity `2.0 mS/cm` | alert fires | `gte 2.0` must be **inclusive** at the boundary. |
| 7 | dissolved oxygen `4.01 mg/L` | no alert | Just outside. Off-by-one in the other direction. |
| 8 | conductivity `1.99 mS/cm` | no alert | Same. |
| 9 | `radon activity concentration` | `no_code` | An indicator no alias is close to. Must refuse, not guess. |
| 10 | dissolved oxygen in `quarts per fortnight` | `blocked_qty` | Nonsense unit. The *concept* is still proposed so a reviewer sees it; only the number is withheld. |

Additional robustness beyond this fixture is covered in
[`tests/test_robustness.py`](../tests/test_robustness.py): null and non-numeric quantities
from a FHIR server, absent resource ids, FHIR partial dates (`2022-07`), wrong-typed
`code.coding`, non-finite values at the model boundary, and FHIR id collisions after lossy
normalisation.

---

## Precedents without fixtures

Five further incidents inform the design but do not have simulation fixtures, either because
they duplicate an edge case already covered or because the decisive indicator is one no
standard in scope can express.

| Incident | Why it matters here |
|---|---|
| **Sandoz / Schweizerhalle, Rhine, Nov 1986** — firefighting water carried pesticides and mercury into the Rhine; the eel kill ran from Rhine km 159 to km 560. | The direct ancestor of this project's thesis. It caused the ICPR to build the Rhine Alarm Model and the international warning and alarm plan, in which seven warning centres between Basel and Arnhem notify all downstream centres. That is a cross-border alerting network built by treaty; this bridge is the same idea expressed in a health-interoperability standard. [ICPR — the turning point](https://www.iksr.org/en/icpr/about-us/history/the-turning-point-the-sandoz-accident/) · [ICPR Rhine Alarm Model](https://www.iksr.org/en/topics/pollution/international-warning-and-alarm-plan/rhine-alarm-model) · [UBA, 25 years on](https://www.umweltbundesamt.de/en/press/pressinformation/sandoz-chemical-spill-25-years-on) |
| **Östersund, Sweden, Nov 2010** — ~27,000 people (45% of the population) ill with *Cryptosporidium hominis*. | Detection came from health-advice-line call volumes before the water finding. The strongest argument for the OAH IG's human-health indicators being fused with environmental ones. [*Emerg Infect Dis*](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3966397/) · [early outbreak detection via advice-line calls](https://ncbi.nlm.nih.gov/pmc/articles/PMC5395832) |
| **Gold King Mine, Colorado, Aug 2015** — over 3 million gallons of acid mine drainage into Cement Creek and the Animas, affecting Colorado, New Mexico, Arizona, Utah and the Navajo Nation. | The `ph-acidic` rule exists for this shape of event. Duplicates the Baia Mare multi-jurisdiction case. [USGS water-quality data and activities](https://www.usgs.gov/mission-areas/water-resources/science/gold-king-mine-release-2015-usgs-water-quality-data-and) · [USBR technical evaluation](https://www.usbr.gov/docs/goldkingminereport.pdf) |
| **East Palestine, Ohio, Feb 2023** — derailment; ~44,000 aquatic animals killed within five miles, and Ohio River drinking-water intakes closed ahead of the plume. | The purest downstream-intake routing case. Excluded because vinyl chloride, butyl acrylate and ethylhexyl acrylate have no OAH codes — the fixture would be almost entirely refusals. [US EPA incident page](https://www.epa.gov/east-palestine-oh-train-derailment) · [Ohio DNR wildlife update](https://ema.ohio.gov/media-publications/news/update-east-palestine-train-derailment-impact-wildlife-odnr) |
| **AMR in urban rivers and wastewater** — a trans-Europe study of 12 urban treatment plants across seven countries found AMR profiles mirroring the clinical resistance gradient. | The revised Urban Wastewater Treatment Directive requires Member States to report AMR monitoring from December 2030. A standards-based environmental-to-health bus is the obvious carrier, and the OAH IG's `pharmaceuticals` concept is the hook. [Pärnänen et al., *Sci Adv*](https://www.science.org/doi/10.1126/sciadv.aau9124) · [EEA — AMR in European surface waters](https://www.eea.europa.eu/en/analysis/publications/antimicrobial-resistance-in-european-surface-waters-a-developing-area) |

---

## Edge-case coverage matrix

| Edge case | Scenario | Enforced by |
|---|---|---|
| Multilingual label defeats alias matching (`Leitfähigkeit`, `chlorki`) | oder-2022 | manifest counts |
| Unit conversion µS/cm → mS/cm | oder-2022 | manifest counts |
| Unit conversion mg/L → µg/L | flint-2014 | manifest counts |
| Incompatible estimators must not be converted (MPN vs CFU) | seine-2024 | `test_incompatible_estimators_are_not_silently_converted` |
| Two spellings of one unit both normalise | walkerton-2000, brixham-2024 | manifest counts |
| Unknown unit blocks the quantity, not the proposal | edge-cases | `test_an_unknown_unit_still_blocks_the_quantity_not_the_proposal` |
| Unknown parameter refused, near misses still shown | edge-cases | manifest counts |
| Concept absent from the OAH IG → refused, never guessed | 6 scenarios | `test_an_indicator_the_oah_ig_lacks_is_refused_not_guessed` |
| Negative value on a non-negative indicator | edge-cases | `test_a_negative_dissolved_oxygen_raises_nothing` |
| Decimal typo above a hard physical ceiling | ajka-2010, edge-cases | `test_a_decimal_typo_in_ph_is_withheld_not_published` |
| Below absolute zero | edge-cases | `test_physically_impossible_values_are_withheld` |
| Absurd magnitude / stuck register | edge-cases | `test_physically_impossible_values_are_withheld` |
| Threshold inclusive at the boundary | edge-cases | `test_thresholds_are_inclusive_at_the_boundary` |
| Threshold silent just outside the boundary | edge-cases | `test_thresholds_do_not_fire_just_outside_the_boundary` |
| Two rules on one code get distinct alert ids | ajka-2010 | `test_two_rules_on_one_code_get_distinct_alert_ids` |
| Blocked or uncoded proposal can never be published | all 13 | `test_a_blocked_quantity_can_never_be_published` |
| Nothing is ever auto-approved | all 13 | `test_no_scenario_reading_is_ever_auto_approved` |
| Upstream normal, downstream critical (site resolution) | akerselva-2011, ajka-2010 | manifest alert sets |
| Recovery reading does not alert | brixham-2024, seine-2024 | manifest alert sets |
| Cross-audience One Health routing from one reading | havelock-north-2016 | manifest audiences |
| Multi-jurisdiction plume, three countries | baia-mare-2000 | manifest counts |
| Citizen sample alongside agency sample | flint-2014 | manifest counts |
| Satellite and agency data fused at one site | toledo-2014, oder-2022 | manifest counts |
| Two independent indices corroborate | toledo-2014 | manifest alert set |
| Naturally extreme site defeats a global threshold | mar-menor-2021 | documented, deliberate |
| Record tampering is detectable and located | flint-2014, walkerton-2000 | `/api/v1/provenance/verify` drill |
| Free-text report with no measurement | oder-2022, akerselva-2011, brixham-2024 | `tests/test_intake.py` |
| Every policy rule targets a producible code | all | `test_every_policy_rule_targets_a_code_the_catalog_can_produce` |
| Every policy rule uses a reachable unit | all | `test_every_policy_rule_uses_a_unit_the_catalog_normalises_to` |
| Every routed audience can be briefed | all | `test_every_alert_audience_is_one_the_briefing_writer_knows` |
| Every curated code is a published OAH concept | all | `test_every_curated_code_is_an_oah_temporary_code_system_concept` |
| Malformed FHIR from a Subscription | — | [`tests/test_robustness.py`](../tests/test_robustness.py) |

---

## Terminology gaps this catalogue found

The refusals are an output, not a shortfall. This is the list to submit.

### Absent from the OAH temporary code system

| Indicator | Incidents that turned on it | Note |
|---|---|---|
| **Turbidity** | Milwaukee 1993, Brixham 2024, Östersund 2010 | The primary filtration-performance indicator in drinking-water treatment worldwide. `tss` is a defensible but non-identical proxy. |
| **Free chlorine residual** | Walkerton 2000, Flint 2014, Havelock North 2016, Akerselva 2011, Brixham 2024 | Appears in **five of twelve** incidents. The most consequential single gap found. |
| **Cyanide** | Baia Mare 2000 | The contaminant in Europe's largest post-Chernobyl water disaster. |
| **Microcystin / cyanotoxins** | Toledo 2014 | The substance drinking-water advisories are actually issued on. |
| **Enterococci** | Seine 2024 | A mandatory Bathing Water Directive (2006/7/EC) indicator. `coliforms` covers only the *E. coli* half. |
| Volatile organics (vinyl chloride, acrylates) | East Palestine 2023 | Whole class absent. |
| **Phytoplankton cell density** | Oder 2022 | The IG has `diatomes` but no concept for a cell count of a named alga. Found while building the biodiversity crosswalk: GBIF resolves *Prymnesium parvum* to `7513065` at 99% confidence, and the reading still cannot be published because there is no indicator to hang it on. |

### No taxonomy anywhere in the IG

The code system carries ten biological indicators (`fishes`, `diatomes`,
`macroinvertebreates`, `macrophytes`, `amphibians`, `birds`, `diptera`,
`ticks`, `invasiveOrganisms`, `fish`) and binds **none** of them to Darwin
Core, GBIF, ENVO or NCBI Taxonomy. A reading naming *Prymnesium parvum* loses
the organism the moment it is coded. The
[biodiversity crosswalk](../README.md#the-biodiversity-crosswalk) now suggests
a GBIF Backbone key for the organism named in a source label, reviewer-gated
and published as an `Observation.component`. Submitting a taxonomic binding to
the IG is the real fix.

### Also observed in the IG

- **Duplicate concepts.** `ph` and `pH`, `conductivity` and `electrical-conductivity`,
  `dissolvedO2` and `dissolved-oxygen`, `fish` and `fishes` all exist as separate codes. Two
  conformant implementations can encode the same measurement differently and fail to join.
  Worth raising with HL7 Europe.
- **Coded-value indicators are not yet supported here.** `foam` (Foam/colour/smell),
  `macrophytes`, `macroinvertebreates` and the ordinal value sets are `CodeableConcept`
  observations, not quantities. This bridge publishes `valueQuantity` only. Since these are
  the backbone of citizen-science stream assessment, supporting them is the highest-value
  extension to the ingestion model.

### Absent from environmental LOINC

Unchanged from the crosswalk analysis in the [README](../README.md#the-terminology-crosswalk):
LOINC has exact terms for pH in water (`9481-3`), chloride in water (`12530-2`) and
electrical conductivity of water (`87444-6`), but **none** for dissolved oxygen or water
temperature in an environmental specimen, and none for a satellite-derived index. The
crosswalk returns nothing rather than a plausible-looking wrong code.

### The One Health closure that is available and not yet built

The OAH IG already publishes the human leg (`gastrointestinal`, `campylobacter`,
`cryptosporidium`, `hospitalization-*`, `causes-of-death`) and the animal leg (`fish`,
`amphibians`, `birds`, `ticks`, `diptera`) alongside the environmental one, and provides a
second profile — `observation-health-measure-oah` — for the human measures. Every outbreak
scenario in this catalogue currently stops at the environmental reading. Publishing the
human-health counterpart against the same `Location`, through the profile the IG already
defines, would make the ecosystem-to-human link a queryable fact rather than a narrative
claim. That is the single highest-value next addition to this repository.

---

## Honesty statement

Read this before citing any number from a simulation.

1. **Every measurement value in `data/incidents/` is synthetic.** The values are shaped
   around each incident's published narrative to exercise the pipeline. They are not
   reconstructed measurements, and no scenario should be cited as a description of what was
   actually recorded. The published figures are in the "What happened" sections, with sources.
2. **The thresholds in `config/thresholds.yaml` are a demonstration policy.** They are not
   WFD/EQS limits, Drinking Water Directive parametric values, or Bathing Water Directive
   thresholds. The policy is stamped `demo-not-for-operational-use` and the Mar Menor scenario
   is kept in the catalogue specifically because it shows a global threshold failing on a
   site where it does not belong.
3. **No scenario claims an incident would have been prevented.** Each says what earlier
   machine-readable evidence would plausibly have enabled, and states in the same breath what
   it would not have changed. In every case the underlying cause — a discharge, a failed
   valve, an unchlorinated bore, agricultural nitrate, a tailings dam — is an enforcement,
   engineering or policy problem that a data layer does not solve.
4. **Retrospective simulation is not prediction.** These fixtures were built knowing the
   outcome. They demonstrate that the pipeline *represents and routes* the relevant signal;
   they do not demonstrate that it would have distinguished that signal from noise in real
   time, and no claim of detection performance should be made from them.
5. **Nothing here is clinical, veterinary, public-warning, or regulatory output.** Advisory
   drafts are marked `draft`, carry a disclaimer, and require an accountable authority to
   review them before any use.
