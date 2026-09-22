# Demo-video incident research

Candidate incidents for the "it actually happened → run it through AquaFHIR" video.

**None of these are in `docs/incidents.md` yet.** The existing twelve are the CI catalogue;
this is a fresh sweep aimed specifically at the video, selected against four filters:

1. **A published stat that fits on a title card** — deaths, cases, tonnes, people cut off.
2. **A documented gap** — the reading existed at time *T*, the warning came at *T + N*. The
   video needs *N* on screen.
3. **Indicators this repo can actually code**, so the dashboard run is real, not mimed.
4. **A failure mode that maps to a specific AquaFHIR feature**, so each incident proves one
   different thing instead of five incidents proving the same thing.

Incidents that fail filter 2 are excluded no matter how large they are. A disaster with no
documented delay gives the video nothing to contrast against.

---

## Segment 0 — the stats montage (open the video with these)

These are aggregate findings, not incidents. They establish that the gap is systemic before
you show a single case, and they are all from peer-reviewed or regulator sources.

| Stat | Source |
|---|---|
| **35 waterborne outbreaks, 6,128 cases** in Greece 2004–2023. Median time from first symptom onset to *reporting*: **7 days** (range 1–26). | Sideroglou et al., *IJERPH* 2024 |
| In **14.3%** of those outbreaks, the authorities were informed **by the media**, not by the health or water system. | same |
| Water samples were collected in only **54.3%** of them, at a mean lag of **5 days** (range 1–20) after the first cases. | same |
| The same organism was found in **both the patient and the water in 1 outbreak — 6.25%**. | same |
| Average delay between pool contamination and disinfection in cryptosporidiosis outbreaks: **27 days**. | Ly et al., *J Infect Dis* 2026 |
| England: **11,474** water-company investigations 2015–2025 → **58 prosecutions (0.5%)**. **5,998** serious incidents downgraded to "minor" 2016–2025 **without visiting the site**. | Channel 4 News / EA data |
| From **6 July 2026**, failing to report a pollution incident **within four hours** is a civil-penalty offence in England (Water (Special Measures) Act 2025). | UK Gov / EA |

**The line to say over this montage:** *"In twenty years of Greek waterborne outbreaks, the
organism in the patient and the organism in the water were matched exactly once. That is not
a science problem. That is a plumbing problem — between two databases."*

That single statistic is the strongest possible setup for the One Health closure demo,
because closing it is literally what `observation-health-measure-oah` on the same `Location`
does.

---

## Tier 1 — the hero incidents

Five, each proving a different feature. If the video is 3–5 minutes, use two or three.

---

### 1. Munster Blackwater fish kill — Ireland, August 2025 ⭐ **open with this one**

**Why it's the best candidate in this document:** it is recent, it is EU, it is the largest
ever recorded in its country, and — uniquely — the **European Commission's own Joint Research
Centre published an independent report in February 2026 whose central recommendation is,
almost word for word, the product you built.** You are not claiming your tool would have
helped. The European Commission is.

**Stats for the title card**
- **~42,000 fish killed** — largest recorded fish kill in Irish history
- **~30 km** of river affected, near Mallow, Co. Cork
- Cause: **never determined**
- **Nine** separate agencies/entities involved in the response
- Report: EU JRC, published **11 February 2026** (JRC145279)

**The gap — put this on screen as a timeline**

| | |
|---|---|
| 5–6 Aug 2025 | Pollutant enters the river (later inferred by Marine Institute analysis) |
| 9 Aug | Dead fish first spotted |
| 11–12 Aug | Authorities finally notified — **by anglers and local stakeholders, not by any monitoring system** |
| 12 Aug | First testing organised |
| — | **5–6 days elapsed.** The pollutant had dissipated. Cause unknown to this day. |

The JRC named this a **"detection gap"**: short-lived pollution events dissipate before
anyone samples, so the investigation is dead on arrival.

**What the JRC recommended**
- Automated **continuous monitoring on all rivers >100 km**, with **publicly accessible
  data** on chemical composition, temperature, **oxygen levels**, algae and turbidity
- A tested **multi-agency plan** for major fish kills
- **One designated lead agency** (nine were involved)
- A public communication strategy that states uncertainty honestly

Read that list next to your README. Continuous readings, normalised, publicly addressable,
routed to named audiences, with an honest refusal when the data won't support a claim.

**The feature it proves:** latency + fragmentation. The core pitch.

**Dashboard run**
- Rows: `dissolved-oxygen` (crashing), `ammonium` (agricultural/organic load),
  `waterTemperature`, `ph`, `fishes` (mortality count), `tss`
- Alerts that fire: `dissolved-oxygen ≤ 4 mg/L` → **critical** → veterinary + water-authority;
  `ammonium ≥ 1.0 mg/L` → high → public-health + water-authority
- **The honest moment:** `turbidity` is in the JRC's recommended list and is **absent from
  the OAH code system** — it lands in `no_code` and on your gap list. Say so on camera. The
  refusal is the credibility.
- Note: `fishes` codes but has no threshold rule — the alert comes from the water chemistry,
  which is the point. The fish are the lagging indicator.

**The kicker — and this is what makes it a video rather than a slide.** The JRC report
published in February 2026. By July 2026 Ireland had logged at least three more:

| Date | River | Fish killed |
|---|---|---|
| 3 June 2026 | River Glyde, Co. Louth | **20,000+** (suspected agricultural discharge) |
| July 2026 | Co. Cavan river | **4,500+** |
| 2 July 2026 | River Rye, Maynooth, Co. Kildare | ~500 |

*"The recommendation was published in February. By July it had happened three more times."*

**Sources:** [JRC145279](https://publications.jrc.ec.europa.eu/repository/handle/JRC145279) ·
[RTÉ, 13 Feb 2026](https://www.rte.ie/news/ireland/2026/0213/1558276-blackwater-fish-kill/) ·
[Irish Times, 13 Feb 2026](https://www.irishtimes.com/environment/2026/02/13/rivers-must-be-monitored-continuously-to-prevent-repeat-of-blackwater-fish-kill/) ·
[Irish Times, 27 Sep 2025](https://www.irishtimes.com/environment/2025/09/27/some-big-polluter-is-breathing-a-sigh-of-relief-questions-remain-over-blackwater-fish-kill/) ·
[Irish Examiner (Glyde)](https://www.irishexaminer.com/news/arid-41857029.html)

---

### 2. Askøy campylobacteriosis outbreak — Norway, June 2019 ⭐ **the One Health closure**

**Why:** this is Havelock North with a European postcode and a *DNA-sequenced animal source*.
It is the cleanest demonstration in existence of the animal → water → human pathway that the
OAH IG's three legs are designed to represent, and it produces a genuine, submittable
terminology gap on camera.

**Stats for the title card**
- **>1,500 confirmed cases**, estimated **>2,000 infected** — in a municipality of ~29,000
- **70 hospitalised**
- **2 deaths** — an infant and an elderly person
- Source traced by DNA faecal source tracking to **animal faeces, ~69% equine (horse)**

**The gap**

| | |
|---|---|
| Late May 2019 | Water contaminated — cracks in a mountain reservoir, heavy rain after a long dry spell |
| 6 June 2019 | Norwegian Institute of Public Health notified of >50 gastroenteritis cases |
| — | **~1 week.** Detection came from sick people, not from water data. |

The reservoir was an old covered holding pool. **E. coli was present.** The environmental
signal and the human signal existed in two different institutions and were joined only
retrospectively, by genomics, after two people had died.

**The feature it proves:** the One Health loop closed — human, animal and environmental
Observations on the *same* `Location`, via both IG profiles.

**Dashboard run — this is the money shot**
1. Ingest `coliforms` and `escherichia-coli` from the reservoir → `observation-indicators-oah`
2. Ingest `campylobacter` at the district rate → `observation-health-measure-oah`, **same
   `Location`**
3. `campylobacter ≥ 100 {cases}/100000` → **critical**, routed to **public-health +
   veterinary + water-authority** simultaneously
4. On screen: `Observation?subject=Location/askoy-reservoir` returns the environmental
   reading *and* the human case rate in one search. The pathway is a query, not a slide.

**The honest moment, and it's a strong one:** the animal leg here is **horses**. The OAH
animal leg has `fish`, `amphibians`, `birds`, `ticks`, `diptera` — **and nothing for
livestock or equines**. The 69%-equine finding, the single most important fact in the entire
investigation, **cannot be coded at all**. It goes on the gap list. This is the same gap
Havelock North (sheep) and Walkerton (cattle) produce — three outbreaks, one missing concept.
That repetition is a genuinely publishable finding for the IG.

**Sources:** [*Eurosurveillance* / PMC7472686](https://pmc.ncbi.nlm.nih.gov/articles/PMC7472686/) ·
[DNA faecal source tracking, *Int J Hyg Environ Health*](https://www.sciencedirect.com/science/article/pii/S1438463919308338) ·
[Hospitalised patients, *PLOS One*](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0248464)

---

### 3. Tunbridge Wells water crisis — Kent, UK, Nov–Dec 2025 ⭐ **"foreseeable and preventable"**

**Why:** the regulator's own published conclusion hands you the verdict. You do not have to
argue that better monitoring would have helped; the Drinking Water Inspectorate wrote it
down. And the cause — a bad coagulant batch — maps onto `aluminium-dissolved`, a code you
already ship with a threshold.

**Stats for the title card**
- **Up to 60,170 consumers** affected by loss of supply and the boil-water notice
- **~24,000 homes** without water or at reduced pressure at peak
- Boil notice ran **3 December → 12 December 2025** (nine days)
- Declared a **major incident** by the local authority
- DWI verdict: **"foreseeable and preventable"**, arising from **"longstanding weaknesses in
  operational management, treatment optimisation, monitoring, maintenance and organisational
  preparedness"** and **"systemic and repeated failings"**
- South East Water placed into a **transformation programme** — one of the DWI's most
  significant enforcement steps

**The gap**

| | |
|---|---|
| 29 Nov 2025 (evening) | Pembury treatment works shut down — a "bad" batch of coagulant contaminated the treatment process |
| 29 Nov – 3 Dec | Supply lost / pressure reduced across Tunbridge Wells, Pembury, Frant, Eridge |
| 3 Dec, midday | **Boil-water notice finally issued** |
| 12 Dec, 14:55 | Notice lifted |
| — | **~4 days** between the treatment failure and the instruction not to drink the water. |

**The feature it proves:** treatment-breakthrough detection, and the *blocked value* guard —
a dosing fault produces exactly the kind of out-of-range chemistry that must never silently
publish.

**Dashboard run**
- Rows: `aluminium-dissolved` (coagulant carryover), `ph` (coagulation shifts pH),
  `tss` (as the filtration-performance proxy), `coliforms`
- Alerts: `aluminium-dissolved ≥ 200 µg/L` → **high** → public-health + water-authority —
  fires on **29 November**, four days before the real notice went out
- `tss ≥ 25 mg/L` → high, same audiences
- **The honest moment, twice over:** (a) **turbidity**, the actual regulatory indicator for
  this failure, has no OAH code — `tss` is your defensible-but-not-identical proxy, and you
  should say "not identical" out loud; (b) **free chlorine residual** is absent too, and the
  README already flags it as the most consequential single gap, appearing in five of the
  twelve catalogued incidents. This incident makes it six.
- Good place to also show the **plausible-range guard**: feed a decimal-slipped aluminium
  reading and show it refuse to publish rather than raise a false critical.

**Sources:** [DWI investigation conclusion](https://www.dwi.gov.uk/drinking-water-inspectorate-south-east-water-tunbridge-wells-investigation-conclusion-november-2025/) ·
[South East Water boil notice](https://www.southeastwater.co.uk/help/works-and-outages/boil-notice-for-customers-in-tunbridge-wells/) ·
[ITV timeline](https://www.itv.com/news/meridian/2025-12-18/tunbridge-wells-water-outage-a-timeline-of-how-the-crisis-unfolded) ·
[TWBC major incident](https://tunbridgewells.gov.uk/news/2025/december/water-outage-declared-major-incident)

---

### 4. Sino-Metals Leach tailings dam collapse, Kafue River — Zambia, February 2025 ⭐ **the audit chain**

**Why:** every other incident here is about data arriving *late*. This one is about data
arriving **wrong**. An independent assessment reportedly put the spill at **~30× what the
operator reported**. That is the exact scenario the hash-chained, reviewer-gated provenance
ledger exists for — and it is the only incident in this set that gives you a reason to demo
`/api/v1/provenance/verify` with real stakes.

**Stats for the title card**
- **18 February 2025** — tailings dam collapse
- **~50 million litres** of acidic mining effluent into the Kafue
- Damage observed **≥100 km downstream**
- Water supply to **Kitwe (~700,000 people)** shut off
- Mass fish mortality; birdlife disappeared from affected stretches
- Independent assessment (Drizit Environmental) reportedly found the spill **~30× the volume
  the company first reported** — *treat as reported-by-media; verify before putting the
  number on screen*

**The gap**

| | |
|---|---|
| 18 Feb 2025 | Dam collapses |
| 23 Feb 2025 | Ministry of Fisheries advisory published |
| — | **5 days.** Meanwhile the number of record was the polluter's own. |

**The feature it proves:** tamper-evident provenance + the reviewer gate. Nobody's
self-reported figure publishes unchallenged, and any later edit is detectable by sequence
number.

**Dashboard run — the most visually satisfying of the five**
- Rows map to **four** metals codes you already ship, plus pH:
  `arsenic-dissolved`, `lead-dissolved`, `zinc-dissolved`, `copper-dissolved`, `ph`
- Alerts fire in a cascade: `arsenic ≥ 10 µg/L` **critical** → public-health + water-authority;
  `lead ≥ 10 µg/L` **critical**; `ph ≤ 5.5` (`ph-acidic`) **critical** → all three audiences;
  `zinc ≥ 500 µg/L` and `copper ≥ 100 µg/L` **high** → veterinary + water-authority
- Then the drill: **edit one stored reading** — the operator's revised-downward figure — and
  show `/api/v1/provenance/verify` flip from `valid: true` to a named
  `first_invalid_sequence`. *"It doesn't just tell you something changed. It tells you which
  record."*

**Sources:** [Wikipedia](https://en.wikipedia.org/wiki/2025_Sino-Metals_Leach_Zambia_dam_disaster) ·
[Mongabay, Aug 2026 follow-up](https://news.mongabay.com/2026/08/a-mine-polluted-a-zambian-river-in-2025-residents-continue-to-live-with-the-impacts/) ·
[*Environmental Challenges* assessment](https://www.sciencedirect.com/science/article/pii/S2772416626001038) ·
[ADF Magazine](https://adf-magazine.com/2025/04/toxic-spills-in-zambia-bring-chinese-mining-abuses-to-light/)

---

### 5. Mixed gastroenteritis outbreak, Northern Greece — Jan–Feb 2019

**Why:** the single most damning timeline in this document, and it is one sentence long. The
chlorine residual — the measurement that would have explained everything — was taken **the
day after the last case fell ill.**

**Stats for the title card**
- **638 cases**, onset 25 Jan – 4 Feb 2019
- **430 hospitalised** (a startling 67%), ages from a few months to 93
- Tap water explained **95.7%** of cases
- Multiple pathogens simultaneously: **norovirus, *Campylobacter jejuni*, EHEC, EPEC**
- Source of contamination: **never determined**

**The gap**

| | |
|---|---|
| 25 Jan – 4 Feb 2019 | 638 people fall ill |
| **5 Feb 2019** | Public health authority inspects the system and measures residual chlorine — **finding it low**, with technical failures in the water tanks |
| — | **The water was measured the day after the outbreak ended.** |

**The feature it proves:** the human leg as a *trigger* for environmental investigation —
your `gastrointestinal` rule routing back to the water authority. An outbreak of GI illness
*is* a water-quality signal, and the policy treats it as one.

**Dashboard run**
- `gastrointestinal ≥ 200 {cases}/100000` → **high** → public-health + **water-authority**.
  On screen: a health notification automatically tasking the water utility on day 2, not day 12.
- Then the environmental leg on the same `Location`: `coliforms`, `escherichia-coli`, `tss`
- **The honest moment:** free chlorine residual — the decisive reading in this entire
  outbreak — **has no OAH code**. `no_code`. Gap list. Seventh incident.

**Sources:** [*Epidemiology & Infection* (Cambridge)](https://www.cambridge.org/core/journals/epidemiology-and-infection/article/evidence-for-waterborne-origin-of-an-extended-mixed-gastroenteritis-outbreak-in-a-town-in-northern-greece-2019/037CE147B6756877B70E780DEDE43EBF) ·
[Food Safety News](https://www.foodsafetynews.com/2021/02/large-outbreak-in-greece-linked-to-tap-water/) ·
[Sideroglou et al., *IJERPH* 2024 (the 20-year gap analysis)](https://www.mdpi.com/1660-4601/21/6/701)

---

## Tier 2 — supporting material

Not full segments. Use as b-roll, as a rapid-fire "and it keeps happening" montage, or as
backup if a Tier 1 fact doesn't survive a second source check.

| Incident | Stat | The gap | Codes |
|---|---|---|---|
| **Málaga beach closures**, Spain, Aug 2026 | 6 beaches shut after storm sewage overflow; E. coli in routine tests | Explicit in the reporting: *"water is sampled faster than results come back, so closures lag behind the real hazard"* — latency stated as the problem | `coliforms`, `escherichia-coli` |
| **Copenhagen triathlon**, Denmark, 2010 | **487 cases** (Campylobacter, E. coli, Giardia) | Heavy rain → sewer overflow **before** the event. The event went ahead anyway. | `coliforms`, `gastrointestinal` |
| **Askøy's quieter cousin — Vuorela**, Finland, 2012 | **~800 cases** | Main pipe broken during road construction; contaminated water entered a reservoir with **no disinfection in place** | `coliforms`, `campylobacter` |
| **Bologna**, Italy, 2018 | **228 Giardia cases** | Contamination introduced **during planned network operations** — a scheduled, known, logged activity | `coliforms`, `gastrointestinal` |
| **Belgium**, 2010 | **222 cases** | River water entered the mains during **fire-fighting** — no reflux valves. A cross-domain event nobody's water system was watching. | `coliforms`, `gastrointestinal` |
| **Irish repeat kills**, 2026 | Glyde **20,000+**; Cavan **4,500+**; Rye **~500** | All three *after* the JRC recommended continuous monitoring | `dissolved-oxygen`, `ammonium`, `fishes` |
| **European rivers at record lows**, summer 2026 | Rhine and Danube visibly diminished from orbit (CNN, Aug 2026) | Not an incident — the **precondition**. Low flow + heat is exactly the Oder 2022 recipe: concentrated salinity, collapsing DO, blooms. Use as the closing "this is why now." | `electrical-conductivity`, `waterTemperature`, `dissolved-oxygen`, `ndci` |

---

## Deliberately excluded

Worth knowing why, in case someone suggests them:

- **East Palestine 2023** — already excluded in `docs/incidents.md` for the right reason:
  vinyl chloride and the acrylates have no OAH codes, so the fixture would be nearly all
  refusals. Dramatic, but it demos nothing except the gap list.
- **Indore, India 2025** (32 deaths, ~1,400 ill, sewage into the mains) — enormous stat, but
  the failure is a physical pipe leak with no monitoring record to contrast against. Fails
  filter 2. Also weakens EU/OneAquaHealth alignment.
- **PFAS contamination generally** — no OAH code, no threshold, and the timescale is decades,
  which kills the "N days" framing the whole video rests on.
- **Legionella outbreaks** — the largest killer in the CDC drinking-water surveillance data,
  but it is a building-systems problem and has no code in scope.

---

## Suggested video structure

| Time | Content |
|---|---|
| 0:00–0:25 | **Stats montage** (Segment 0). Land on the 6.25% line. |
| 0:25–1:10 | **Blackwater 2025.** Timeline card with the 5–6 day gap. Cut to the JRC recommendation list beside your README. |
| 1:10–2:10 | **Dashboard run on Blackwater.** Ingest → propose → one refusal (turbidity) → approve → `dissolved-oxygen` critical alert routed to two audiences. Show the refusal; do not skip it. |
| 2:10–3:00 | **Askøy 2019.** The One Health closure: one `Observation?subject=Location/...` search returning the water reading and the human case rate. Then the equine gap. |
| 3:00–3:35 | **Kafue 2025.** Metals cascade, then break a record and run `provenance/verify`. |
| 3:35–4:00 | **The "it keeps happening" montage** — three 2026 Irish kills, Málaga, record-low rivers — over the four-hour reporting rule coming into force July 2026. |
| 4:00–4:20 | Close on the gap list as an *output*: the concepts no standard can express, exported for submission to the IG and LOINC. |

**One framing note.** The README is already careful to say the Oder replay shows *plausible
earlier warning*, not prevention. Keep that discipline in the video. Blackwater is the case
where you can be most forceful — not because you'd have stopped the pollution, but because
the cause was **never identified**, and it was never identified specifically because nobody
sampled for five days. Earlier data there doesn't just mean an earlier warning; it means the
investigation would have had something to work with. That is a claim you can defend.

---

## Verification status

| Claim | Status |
|---|---|
| Blackwater: 42,000 fish, 30 km, 5–6 day delay, nine entities, JRC Feb 2026 | **Two+ independent sources** (JRC, RTÉ, Irish Times) |
| Askøy: >1,500 cases, 70 hospitalised, 2 deaths, 69% equine | **Peer-reviewed** (PMC7472686, ScienceDirect, PLOS One) |
| Tunbridge Wells: 60,170 consumers, "foreseeable and preventable", transformation programme | **Regulator primary source** (DWI) |
| Greece 2019: 638 cases, 430 hospitalised, chlorine measured 5 Feb | **Peer-reviewed** (Cambridge *Epi & Infection*) |
| Greece 2004–2023 aggregate stats | **Peer-reviewed** (Sideroglou, *IJERPH* 2024) |
| Kafue: 18 Feb, 50 M litres, 100 km, Kitwe ~700k, advisory 23 Feb | **Wikipedia + journal + press** — solid |
| Kafue: **"30× under-reported"** | ⚠️ **Secondary reporting only** (Drizit via Mongabay/ADF). Verify against the Drizit report itself before it goes on screen. |
| Irish 2026 repeat kills | Single-source each (RTÉ, Irish Examiner, Farmers Journal). Fine for a montage; don't build a segment on one. |
