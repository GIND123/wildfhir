# Vendored OneAquaHealth IG artifacts

Copied unchanged from the `hl7.eu.fhir.oah` NPM package, continuous build
`0.1.0-ci-build`, package date `2026-06-11T10:57:01+00:00`
(<https://build.fhir.org/ig/hl7-eu/oah/package.tgz>).

| File | Why it is here |
|---|---|
| `CodeSystem-temporarySystem-oah-eu.json` | The temporary project code system (185 concepts in this release). `tests/test_oah_package.py` fails if any code in `config/coding-rules.yaml` is not in it. |
| `ValueSet-health-indicators-oah-vs.json` | The human-health value set bound to `observation-health-measure-oah`. The test checks that every `leg: human` rule is in it and no other rule is. |
| `ValueSet-macrophytes-indicator-value-oah-vs.json` | `absent` / `present` / `extensive`, the coded values the citizen-science indicators publish. |
| `StructureDefinition-observation-health-measure-oah.json` | The human-leg profile: Location subject, Quantity or CodeableConcept value. |
| `StructureDefinition-observation-indicators-oah.json` | The environmental/animal profile the bridge always used. |

The IG is an unauthorised, changing continuous build. This snapshot is what
the catalog was checked against; refresh it deliberately and re-run the test,
never silently.
