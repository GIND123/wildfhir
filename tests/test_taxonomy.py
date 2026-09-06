"""The biodiversity crosswalk, end to end.

The official OneAquaHealth IG carries only coarse biological codes (`fishes`,
`diatomes`, `macroinvertebreates`) with no taxonomic backing. This crosswalk
fills that gap by naming the organism, under the same suggest-never-select
rule as every other assist in the project.
"""

import pytest

from aquafhir.fhir import build_resources
from aquafhir.gbif import GBIF_SYSTEM, GbifClient
from aquafhir.models import Coding, RawReading, ReviewDecision
from aquafhir.service import AiUnavailableError
from aquafhir.terminology import TerminologyCrosswalk, _taxon_candidates
from aquafhir.umls import UMLSClient
from tests.fakes import FakeGbif

TROUT = {
    "usageKey": 2401664, "scientificName": "Salmo trutta Linnaeus, 1758",
    "canonicalName": "Salmo trutta", "rank": "SPECIES", "status": "ACCEPTED",
    "confidence": 99, "matchType": "EXACT", "kingdom": "Animalia", "genus": "Salmo",
}
REFUSAL = {"matchType": "NONE", "confidence": 100, "synonym": False}


def crosswalk(responses) -> TerminologyCrosswalk:
    return TerminologyCrosswalk(UMLSClient(api_key=""), gbif=FakeGbif(responses))


# -- what the crosswalk keys on --------------------------------------------


def test_the_organism_is_read_from_the_source_label_not_the_curated_display() -> None:
    """The two crosswalks sit on different axes.

    The OAH display `fishes` is not a taxon and GBIF refuses it. The source
    label `Salmo trutta count` names one exactly. Keying the taxon lookup on
    the curated display would therefore find nothing, every time.
    """
    assert _taxon_candidates("Salmo trutta count")[:2] == ["Salmo trutta count", "Salmo trutta"]
    matches = crosswalk([REFUSAL, TROUT]).suggest_taxa("Salmo trutta count")
    assert [m.code for m in matches] == ["2401664"]
    assert matches[0].system == GBIF_SYSTEM
    assert matches[0].vocabulary == "GBIF"


def test_a_non_organism_label_yields_nothing() -> None:
    """An empty list is the correct answer for every chemical and physical label."""
    assert crosswalk([REFUSAL, REFUSAL, REFUSAL]).suggest_taxa("dissolved oxygen") == []


def test_a_refusal_with_full_confidence_never_becomes_a_suggestion() -> None:
    assert crosswalk([REFUSAL] * 3).suggest_taxa("Leitfaehigkeit") == []


def test_the_same_taxon_is_only_offered_once() -> None:
    """Several phrases from one label can resolve to the same organism."""
    matches = crosswalk([TROUT, TROUT, TROUT]).suggest_taxa("Salmo trutta count")
    assert len(matches) == 1


def test_gbif_is_reported_as_a_source_and_is_independent_of_umls() -> None:
    cw = crosswalk([REFUSAL])
    assert cw.sources() == ["gbif"]
    assert cw.taxa_available is True
    # GBIF alone must not make the LOINC/SNOMED crosswalk claim to work.
    assert cw.available is False


def test_without_a_gbif_client_the_crosswalk_simply_has_no_taxa() -> None:
    cw = TerminologyCrosswalk(UMLSClient(api_key=""))
    assert cw.taxa_available is False
    assert cw.suggest_taxa("Salmo trutta") == []


def test_a_disabled_client_is_not_advertised_as_a_source() -> None:
    cw = TerminologyCrosswalk(UMLSClient(api_key=""), gbif=GbifClient(enabled=False))
    assert cw.taxa_available is False
    assert "gbif" not in cw.sources()


# -- the review gate --------------------------------------------------------


def reading(parameter: str, value: float = 12, unit: str = "{count}") -> RawReading:
    return RawReading(
        source_id="oslo-vav", source_type="agency", parameter=parameter, value=value,
        unit=unit, observed_at="2011-03-09T09:00:00Z", site_code="akerselva-vaterland",
        site_name="Akerselva at Vaterland", latitude=59.9110, longitude=10.7590,
    )


def test_suggestions_are_offered_even_when_nothing_could_be_coded(taxon_service) -> None:
    """The case the gap analysis turns on.

    A reading the curated catalog cannot code is exactly where an organism name
    most often survives untranslated. Requiring a coding first would lose it.
    """
    service = taxon_service([REFUSAL, TROUT])
    proposal = service.propose(reading("Salmo trutta cell count", unit="ppm"))
    assert proposal.coding is None, "no OAH indicator matches this label"
    assert [m.code for m in service.suggest_taxa(proposal.id)] == ["2401664"]


def test_a_taxon_never_attaches_itself(taxon_service) -> None:
    service = taxon_service([REFUSAL, TROUT])
    proposal = service.propose(reading("fish count"))
    service.suggest_taxa(proposal.id)
    assert service.repository.get_proposal(proposal.id).taxon is None


def test_a_reviewer_attached_taxon_is_published_and_hash_chained(taxon_service) -> None:
    service = taxon_service([])
    proposal = service.propose(reading("fish count"))
    assert proposal.coding is not None and proposal.coding.code == "fishes"

    taxon = Coding(system=GBIF_SYSTEM, code="2401664", display="Salmo trutta Linnaeus, 1758")
    result = service.approve(
        proposal.id, ReviewDecision(reviewer="reviewer@authority.example", taxon=taxon)
    )

    component = result.observation["component"]
    assert component[0]["valueCodeableConcept"]["coding"][0]["code"] == "2401664"
    # The indicator axis is untouched, so the policy engine still reads what it did.
    assert [c["code"] for c in result.observation["code"]["coding"]] == ["fishes"]
    assert "valueQuantity" in result.observation

    entry = next(
        e for e in service.repository.list_provenance(50) if e.event_type == "mapping-approved"
    )
    # The chain records the exact taxon, not a boolean saying one was attached.
    assert entry.payload["taxon"]["code"] == "2401664"
    assert entry.payload["taxon"]["system"] == GBIF_SYSTEM
    assert entry.payload["published_coding"]["code"] == "fishes"
    assert entry.payload["published_value"] == 12
    assert entry.payload["published_unit"] == "{count}"
    assert entry.payload["observation_hash"]


def test_an_observation_without_a_taxon_grows_no_component(taxon_service) -> None:
    service = taxon_service([])
    proposal = service.propose(reading("fish count"))
    result = service.approve(proposal.id, ReviewDecision(reviewer="reviewer@authority.example"))
    assert "component" not in result.observation


def test_a_taxon_cannot_reach_the_alerting_path(curated_agent, policy) -> None:
    """A biodiversity suggestion must never influence whether an incident fires."""
    proposal = curated_agent.propose(reading("fish count"))
    _location, _org, plain = build_resources(proposal)
    proposal.taxon = Coding(system=GBIF_SYSTEM, code="2401664", display="Salmo trutta")
    _location, _org, with_taxon = build_resources(proposal)
    assert policy.evaluate(plain) == policy.evaluate(with_taxon)


def test_the_feature_fails_closed_when_switched_off(service) -> None:
    proposal = service.propose(reading("fish count"))
    with pytest.raises(AiUnavailableError, match="disabled"):
        service.suggest_taxa(proposal.id)


def test_the_taxon_component_code_is_a_real_published_loinc_term() -> None:
    """The component code must be real, and must differ from `Observation.code`.

    FHIR invariant obs-7 forbids a component repeating the observation's own
    code while a value is present. HAPI rejects that, which is how this was
    found: the first implementation reused the OAH indicator and was refused.
    """
    from pathlib import Path

    from aquafhir.fhir import TAXON_COMPONENT_CODE, TAXON_COMPONENT_SYSTEM
    from aquafhir.loinc_table import LoincTable

    path = Path(__file__).parents[1] / "loinc" / "LoincTableCore" / "LoincTableCore.csv"
    table = LoincTable(path)
    assert table.available
    assert table.contains(TAXON_COMPONENT_CODE)
    assert TAXON_COMPONENT_SYSTEM == "http://loinc.org"


def test_the_component_code_differs_from_the_observation_code(curated_agent) -> None:
    from aquafhir.fhir import TAXON_COMPONENT_CODE

    proposal = curated_agent.propose(reading("fish count"))
    proposal.taxon = Coding(system=GBIF_SYSTEM, code="8215487", display="Salmo trutta")
    _location, _org, observation = build_resources(proposal)
    assert observation["code"]["coding"][0]["code"] != TAXON_COMPONENT_CODE
    assert observation["component"][0]["code"]["coding"][0]["code"] == TAXON_COMPONENT_CODE
