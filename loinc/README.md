# LOINC 2.83

The core LOINC 2.83 distribution tables, for offline terminology lookups
(display text, component/property/system/scale, class) without a live UMLS
UTS call — a lighter complement to the UMLS crosswalk in
[`terminology.py`](../src/aquafhir/terminology.py), which searches the same
codes online but needs `UMLS_API_KEY`.

- `LoincTable/Loinc.csv` — the full LOINC table
- `LoincTableCore/LoincTableCore.csv` — the reduced "Core" subset
- `loinc.xml` — schema/metadata
- `LoincLicense_5.8.txt` — the license these files are distributed under

**Not included:** `AccessoryFiles/` (~908MB: linguistic variants, panels and
forms, part-link tables, etc.) — several of its files exceed GitHub's 100MB
per-file limit, and none of it is needed for the OAH terminology work here.
Download the full LOINC release yourself from <https://loinc.org/downloads/>
if you need it.

## License

Redistribution is permitted under the Regenstrief Institute / LOINC
Committee license in `LoincLicense_5.8.txt`: free for commercial and
non-commercial use, provided the Group 1 Artifacts (this table) are not
altered and are not used to build a competing identification standard. See
that file for the full terms. LOINC® is a registered trademark of
Regenstrief Institute, Inc.
