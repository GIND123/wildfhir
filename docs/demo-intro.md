# Cold open: the incidents

Twenty to twenty-five seconds before the demo proper. The point is not that water can be
dangerous. It is that in every case below **a reading, a lab result or a case count already
existed** and did not reach the people who could act on it, and that the failure was one of
routing, units, records or vocabulary: the four things this bridge actually does. Say the
numbers; let the graphic carry the dates.

Everything here is a published figure with a source. None of it is a simulation output. The
catalogue in [incidents.md](incidents.md) has the full account of each case and of what the
bridge would **not** have changed.

## The graphic

- [media/signal-to-warning-light.png](media/signal-to-warning-light.png) and
  [media/signal-to-warning-dark.png](media/signal-to-warning-dark.png): 1920 × 1080, ready
  to drop into the edit.
- [media/signal-to-warning.html](media/signal-to-warning.html): the source. Open it in a
  browser for hover detail and a table view. Re-render after an edit with:

```bash
cd docs/media
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for t in light dark; do
  "$CH" --headless=new --disable-gpu --hide-scrollbars --window-size=960,540 \
    --force-device-scale-factor=2 --screenshot="signal-to-warning-$t.png" \
    "file://$PWD/signal-to-warning.html?theme=$t"
done
```

The chart plots one number per incident: the days between the first *recorded* signal and
the first public warning. Havelock North is the last row and reads *same day*, because there
the finding and the notice fell within hours; its failure was that three agencies each held a
third of the picture, which is the demo's own centrepiece at 1:30. Flint is a tile rather
than a bar because fifteen months on the same axis would flatten the others. The frame wears
the console's own chrome, tokens and typeface, so it cuts to the board without a visual jump.

## Voice-over (about 22 seconds)

> *"Milwaukee, 1993. The treatment plant's own turbidity log left a ten-year baseline on the
> twenty-third of March. The boil-water advisory came fifteen days later. Four hundred
> thousand people were ill.*
>
> *The Oder, 2022. Polish monitoring saw the readings on the twenty-sixth of July. Germany,
> downstream, found out from anglers two weeks later.*
>
> *Walkerton, 2000. The laboratory confirmed E. coli on the seventeenth of May, to the
> utility. Not to the health unit. Seven people died.*
>
> *Flint. County epidemiologists linked Legionnaires' cases to the river water in October
> 2014. The public heard in January 2016.*
>
> *In every one of these, the evidence existed. It sat in the wrong office, in the wrong
> unit, in the wrong vocabulary. This is a tool for the person whose job is to make sure it
> doesn't."*

Then cut to the board and the first line of the [demo script](demo-script.md): *"This is a
review console for a data steward..."*

## The incidents, and the demo moment each one earns

| Incident | What existed, and where it sat | What the bridge does with that exact input | Demo moment |
|---|---|---|---|
| **Milwaukee, 1993** | Treated-water turbidity had not exceeded 0.4 NTU in ten years; from 23 March it sat at or above 0.45 NTU, peaking at 1.7 NTU, in the plant's operations log. Advisory 7 April. 403,000 ill, 69 deaths. | A threshold crossing becomes a routed, machine-readable event with a public-health audience attached, not a number in a log. Turbidity itself has no OneAquaHealth (OAH) code, and the bridge says so rather than mapping it to a neighbour. | 4:10 Incidents view; the gap list in the judges' answers |
| **Oder River, 2022** | Polish authorities had anomalous readings on 26–28 July and dead fish by 28 July. German authorities learned on 9 August, from anglers. At least 300 tonnes of fish; 500 km of river. | `Leitfähigkeit 2350 uS/cm` arrives in German, in microsiemens. String matching gives up at 0.31; the co-pilot names the unit, the reviewed factor converts it, and the conductivity crossing routes to public health, veterinary and the water authority in one step, as a FHIR resource the other bank can read. | 0:45 the hard case; 3:30 the Oder replay and the veterinary draft |
| **Walkerton, 2000** | A private lab confirmed E. coli in three samples on 17 May and told the utility. The health unit was not notified until 23 May; the advisory went out 21 May on the health unit's own initiative. Annual reports had been falsified. 2,300 ill, 7 deaths. | A coliform exceedance routes to the health unit as a standards-based event instead of depending on one operator placing a call. Every reading is hash-chained on ingestion, so a later alteration breaks verification at a named sequence number. | 1:30 the routed campylobacter rule; 4:10 Verify chain |
| **Brixham, 2024** | UKHSA reported an illness cluster to South West Water on 13 May. The utility reviewed its operations and found no issue. Cryptosporidium was found in the Hillhead supply overnight on 14–15 May. 118 confirmed cases, 17,000 properties under notice, 54 days. | A citizen or health-agency report enters the same queue, with the same provenance, as a laboratory result, so the earlier signal is not structurally second-class. | 2:15 the citizen's word; `source_type=citizen` |
| **Flint, 2014–16** | County and state epidemiologists knew of the Legionnaires' rise and suspected the river by October 2014. Public disclosure came 13 January 2016. In the lead round, two high samples were dropped from the report, moving the city from over to under the federal action level. 87+ cases, 12 deaths. | Lead arrives in mg/L and is converted to µg/L by a reviewed factor, never by a model. The hash chain cannot stop a sample being excluded, but it makes the exclusion visible and attributable. | 4:10 the tamper drill in [incidents.md](incidents.md#6-flint-drinking-water-crisis--michigan-usa-20142015) |
| **Havelock North, 2016** | Rain on 5–6 August carried sheep faeces into an unchlorinated bore. Illness and the bore's E. coli result both surfaced on the morning of 12 August; the notice went out at 18:40 the same day. 5,500 ill, 45 hospitalised, up to four deaths. The inquiry called the relationship between the two councils dysfunctional. | Not a latency case. The water lab's coliform reading and the health board's campylobacteriosis rate publish against the same `Location`, through two profiles, and come back as one HAPI search. One rule routes to all three legs. | 1:30 the loop closed |

## Two lines to keep honest

- The bridge would not have chlorinated a bore, fixed a valve, or stopped a discharge. It
  buys response time; the catalogue's [honesty statement](incidents.md#honesty-statement)
  says so in every case, and the judges will respect it more than a claim of prevention.
- The Havelock North human-leg figures on the board are synthetic. The published numbers
  in this document are the ones to say out loud.

## The dates behind the bars

| Incident | First recorded signal | Public warning | Days |
|---|---|---|---|
| Milwaukee | 23 Mar 1993, treated-water turbidity leaves baseline | 7 Apr 1993, boil-water advisory | 15 |
| Oder | 26 Jul 2022, anomalous readings on the Polish reach | 9 Aug 2022, German authorities learn of the kill | 14 |
| Walkerton | 17 May 2000, lab confirms E. coli to the utility | 21 May 2000, boil-water advisory | 4 |
| Brixham | 13 May 2024, UKHSA reports the cluster to the utility | 15 May 2024, boil-water notice | 2 |
| Flint | Oct 2014, county epidemiologists link the cluster to river water | 13 Jan 2016, governor discloses the outbreak | ≈450 |

Walkerton's health unit was only formally notified on 23 May; the 21 May advisory rests on
the health unit's own investigation. The bar uses the advisory date, the earlier of the two.

## Sources

- Milwaukee: [MacKenzie et al., *NEJM* 331:161 (1994)](https://www.nejm.org/doi/full/10.1056/NEJM199407213310304) · [Milwaukee Water Works, water quality assurances](https://city.milwaukee.gov/ImageLibrary/Groups/WaterWorks/files/WaterQualityAssurancesinMilwaukee)
- Oder: [BMUV, Fish die-off in the Oder River, August 2022](https://www.bundesumweltministerium.de/fileadmin/Daten_BMU/Download_PDF/Binnengewaesser/Bericht_-_Fischsterben_in_der_Oder_20220929_en_bf.pdf) · [IGB, The big kill](https://www.igb-berlin.de/en/news/big-kill) · [EU analysis of the 2022 Oder disaster](https://op.europa.eu/en/publication-detail/-/publication/acae85a4-ae18-11ed-8912-01aa75ed71a1/language-en)
- Walkerton: [Report of the Walkerton Inquiry (O'Connor, 2002)](https://www.ontario.ca/page/walkerton-inquiry-reports) · [CBC, Inside Walkerton](https://www.cbc.ca/news/canada/inside-walkerton-canada-s-worst-ever-e-coli-contamination-1.887200) · [Wikipedia, Walkerton E. coli outbreak](https://en.wikipedia.org/wiki/Walkerton_E._coli_outbreak)
- Brixham: [ITV, one year on: a timeline](https://www.itv.com/news/westcountry/2025-05-14/water-parasite-outbreak-one-year-on-a-timeline-of-events) · [South West Water, Brixham incident](https://www.southwestwater.co.uk/household/help-support/in-your-area/service-updates/brixham-incident) · [Wikipedia, Devon cryptosporidiosis outbreak](https://en.wikipedia.org/wiki/Devon_cryptosporidiosis_outbreak) · [DWI prosecution notice](https://www.dwi.gov.uk/4-march-2026-prosecution-of-south-west-water-limited-for-s701-offences-under-the-water-industry-act-1991)
- Flint: [Detroit News, health director knew of Legionnaires' a year before governor](https://www.detroitnews.com/story/news/michigan/flint-water-crisis/2016/03/24/health-director-knew-legionnaires-year-gov/82237342/) · [Zahran et al., *PNAS* (2018)](https://www.pnas.org/doi/10.1073/pnas.1718679115) · [CNN, the two discarded samples](https://www.cnn.com/2016/01/14/us/flint-water-investigation/index.html)
- Havelock North: [Government Inquiry, Stage 1 overview](https://www.dia.govt.nz/government-inquiry-into-havelock-north-drinking-water-report---part-1---overview) · [Australian Water Association, lessons from the outbreak](https://www.awa.asn.au/resources/latest-news/community/public-health/lessons-from-nzs-2016-havelock-north-water-supply-outbreak)
