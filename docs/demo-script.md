# Five-minute demo

The point of the demo is not that an AI reads water data. It is that a **data steward at a
municipal water authority** can turn fragmented water, citizen and public-health readings
into reviewed OneAquaHealth FHIR resources, and that nothing an AI produces can be published
without her. Name the user out loud in the first fifteen seconds, and land the terminology
moment before the two-minute mark: those are the two things a judge scores that the
interface alone will not say for you.

## Setup

1. Put a Gemini key in `.env` as `GEMINI_API_KEY=...` (free at
   <https://aistudio.google.com/apikey>). The default `GEMINI_MODEL=gemini-3.1-pro-preview`
   writes the best briefings but needs a billed project. On a free-tier key the bridge falls
   back to `gemini-3.1-flash-lite` on its own; set `GEMINI_MODEL=gemini-3.1-flash-lite`
   directly for the recording to save one failed round trip per call.
2. Set `GEMINI_ASSIST_MODE=always` for the recording so every card shows its AI attribution.
   `auto` is the sensible default outside a demo.
3. Optional: put your UTS key from <https://uts.nlm.nih.gov/uts/profile> in `.env` as
   `UMLS_API_KEY=...`. The local LOINC table answers the water-quality codes on its own,
   and the key only adds SNOMED CT breadth.
4. Run `docker compose up --build` and wait for all three services to become healthy.
5. Open the console (<http://localhost:8000>) and the HAPI UI in separate tabs. Append
   `?theme=light` or `?theme=dark` to the console URL to force the theme for the recording.
6. Confirm the top-bar pills read `AI gemini-3.1-…`, `FHIR enabled`, and
   `Crosswalk loinc-table+gbif` (or `+umls`), and that the sidebar footer shows the chain as
   `valid`. Set your reviewer identity from the avatar (top right) so approvals carry a name.
7. Run `python scripts/simulate.py havelock-north-2016 coimbra-citizen-2026 --propose-only`
   in a second terminal so the board already holds the One Health and citizen-science cards.

Rehearse once, then **stop rebuilding**. Repeated `docker compose up --build` re-pulls
`hapiproject/hapi` and `postgres` and can hit Docker Hub's anonymous pull limit on shared
conference Wi-Fi. `docker login` with a free account before you travel.

## Narrative

**0:00–0:15 — Name the user.** Say it before anything is on screen: *"This is a review
console for a data steward at a municipal water authority in a OneAquaHealth pilot city.
Readings reach her as CSV rows, French laboratory labels, a bulletin, a citizen's word that
the stream is foaming, a health board's case counts. She has to publish what a
public-health officer, a veterinarian and her own operations team can act on, and prove
afterwards exactly what she published and why."* Then show the board.

**0:15–0:45 — The terminology moment, first.** Open a pending `pH` card, go to its
**Crosswalk** tab and press **Suggest LOINC / SNOMED**. Say plainly: *a generic clinical
terminology search for "pH" ranks Peliosis hepatis, a liver disease, above anything about
water.* This bridge searches the published LOINC table scoped to environmental specimens and
returns `9481-3` **pH of Water**, validated against the term list. Click the chip: it will be
attached beside the OAH code when she approves. Twenty seconds, and it says more about
standards than any slide.

**0:45–1:30 — The hard case for the co-pilot.** Press **Create** (`C`). The parameter is
already `Leitfähigkeit`, unit `uS/cm`. Submit, open the card. String matching scores this at
0.31 and gives up; the card comes back mapped to `electrical-conductivity` with a `GEMINI`
chip, the quoted evidence, the prompt hash, the latency. Point at `2.35 mS/cm`: the model
never computed that. It named the unit; the factor comes from the reviewed
`coding-rules.yaml`, the prompt never contained the answer, and the model could only choose
from a closed enum of catalog codes. Confidence is capped at 0.95 and the card is still
`pending`. There is no confidence value that publishes anything.

**1:30–2:15 — The loop closed.** Filter the board to *Brookvale Road bore field*. Two kinds
of card share that site: the coliform reading from the water lab, and the district health
board's campylobacteriosis rate, tagged **human**. Open the human card's **FHIR** tab: its
profile is `observation-health-measure-oah`, the IG's second profile, and its subject is the
same `Location` as the water reading. Approve both. In HAPI, run
`Observation?subject=Location/brookvale-bore-1`: the pathway comes back as one search. Say
what Havelock North was: sheep faeces, rain, an unchlorinated bore, 5,500 ill, and animal
health, water and public health each somebody's job and nobody's single view. Then open
**Incidents**: the campylobacter rule routed to public health, veterinary *and* the water
authority from one crossing.

**2:15–2:45 — The citizen's word.** Open the `foam` card from Coimbra. As received:
*"present"*. It publishes as `valueCodeableConcept` `present`, a concept from the IG's own
value set, not a number the app never recorded. Now open the other foam card: *"kinda
foamy"*. Withheld. The bridge does not round words to the nearest concept; the approve
dialog offers the three reviewed values and requires a reason. That is the shape of the
OneAquaHealth app's real data, and it is the difference between integrating with the
project and running beside it.

**2:45–3:30 — Real data, not a fixture.** Press **Create → Live data** and **Pull Hub'Eau
now**. Real laboratory analyses from the Garonne inside Toulouse arrive, keyless, with the
French labels and units exactly as the laboratory wrote them: `Conductivité à 25°C 277
µS/cm`, `Oxygène dissous 11.5 mg(O2)/L`, `Nitrates 3.9 mg(NO3)/L`. Each is coded through the
same catalog, each cites its source record, each carries a **live** chip, and each is
`pending`. Point at the E. coli row: `179 n/(100mL)` is withheld, because whether that count
is MPN or CFU depends on the method and the connector does not guess. Press **List recent
scenes** for the same reach: the Sentinel-2 products that covered it this month, with cloud
cover, from the Copernicus catalogue.

**3:30–4:10 — A failed sensor cannot raise an alert.** Open the edge-case card for
dissolved oxygen at `-5.0 mg/L`. It is coded, and its quantity is withheld: no publication,
no alert, approval blocked until a person corrects it. Say that before this guard existed,
that probe raised a *critical* alert to veterinary and water-authority at 0.99 confidence.
Then **Approve all pending** on the Oder replay, open the low-oxygen incident and press
**Draft · Veterinary**: Gemini writes the advisory the phone call would have carried, marked
`draft`, with its uncertainty stated and a disclaimer that an accountable authority must
review it.

**4:10–5:00 — Trust.** Open **Audit log**, press **Verify chain**, and scroll:
`mapping-proposed`, `mapping-approved` (with the profile and the leg), `connector-pull`
(which query, how many rows, which proposals), `alert-created`, `briefing-drafted`, each
carrying the model id and prompt hash where a model was involved, each hash-chained,
verification `VALID`. Close on the boundary: the bridge gives earlier machine-readable
decision support across all three legs of One Health; accountable authorities review and
communicate the warning.

## The question judges will ask

*"What if the model is wrong?"* Have the answer ready and demonstrate it if there is time:

- Wrong code → the reviewer sees the disagreement flag, the competing candidates, and the
  quoted evidence, and overrides the coding and quantity in the approve dialog.
- No safe code → the model returns `NO_MATCH`, confidence drops to zero, and approval is
  blocked until a human supplies one.
- Unknown unit, implausible value, or a word outside the value set → the value stays empty
  and approval is blocked. A code without a publishable value cannot be published.
- Model down, key missing, or a pinned model the key cannot use → delete `GEMINI_API_KEY`
  and restart: everything still works, the badge reads `AI off`, the AI-only endpoints
  return `503`. With a key and no quota for the pinned model, the bridge falls back once to
  `GEMINI_FALLBACK_MODEL` and records the model that actually answered.
- *"Why isn't the LOINC/SNOMED coding automatic?"* Because a wrong crosswalk is worse than
  none. The same answer as the coding co-pilot: suggest, never select.
- *"Why not just query UMLS?"* Because a generic Metathesaurus search is a clinical search.
  Ask it for `pH` and it ranks *Peliosis hepatis* above anything about water; ask for
  `Water temperature` and it offers *Checking bath water temperature*. It also returns LOINC
  Parts (`LP...`) and Metathesaurus ids (`MTHU...`) that are not publishable LOINC codes at
  all. So the bridge searches the published LOINC table scoped to environmental specimens
  first, which finds `9481-3` pH of Water and `12530-2` Chloride in Water exactly, and
  validates every candidate against that table before a reviewer ever sees it.
- *"What about dissolved oxygen?"* Environmental LOINC has no term for it, nor for water
  temperature in water, nor for NDCI. The crosswalk returns nothing rather than a
  plausible-looking wrong code. That gap is exactly why the OAH IG needs a temporary code
  system, and saying so is more convincing than pretending full coverage.
- *"Is the human leg real data?"* No. Every incident fixture is synthetic, shaped around the
  published narrative. The Hub'Eau readings are the real data in the demo, and the console
  marks them **live**. Say which is which; the honesty is part of the pitch.
- *"Why is the sheep not in FHIR?"* Because the OAH IG has no concept for livestock. The
  bridge refuses rather than mapping to a neighbour, and the refusal is on the gap list to
  submit to the IG.

## Evidence to capture

- Count of records ingested, mapped, approved, rejected, and alerted, split by leg and by
  live versus fixture.
- FHIR transaction response and both profile URLs.
- The HAPI search that returns both legs on one `Location`.
- Median raw-to-proposal and approval-to-publication latency, and Gemini latency separately.
- Reviewer override rate, and the `NO_MATCH` refusal rate.
- Validator output against the frozen OAH package.
- Exact demo policy id, model id (and any fallback), prompt-template ids, and source-data checksum.
- Which crosswalk sources answered, and the code picked (or the honest gap).
- The `connector-pull` chain entries, with their request hashes.
