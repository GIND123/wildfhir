from aquafhir.terminology import TerminologyCrosswalk
from aquafhir.umls import UMLSClient
from tests.fakes import FakeUMLS


def _result(results: list[dict]) -> dict:
    return {"result": {"results": results}}


def test_unavailable_without_a_key():
    crosswalk = TerminologyCrosswalk(UMLSClient(api_key=""))

    assert crosswalk.available is False


def test_suggest_maps_root_source_to_the_canonical_fhir_system():
    umls = FakeUMLS(
        [
            _result(
                [
                    {"ui": "11556-8", "rootSource": "LNC", "name": "Dissolved oxygen"},
                    {
                        "ui": "271737000",
                        "rootSource": "SNOMEDCT_US",
                        "name": "Low dissolved oxygen",
                    },
                ]
            )
        ]
    )
    crosswalk = TerminologyCrosswalk(umls)

    matches = crosswalk.suggest("Dissolved Oxygen")

    systems = {match.vocabulary: match.system for match in matches}
    assert systems["LNC"] == "http://loinc.org"
    assert systems["SNOMEDCT_US"] == "http://snomed.info/sct"


def test_best_name_match_is_ranked_first():
    umls = FakeUMLS(
        [
            _result(
                [
                    {"ui": "999", "rootSource": "LNC", "name": "Something unrelated entirely"},
                    {"ui": "11556-8", "rootSource": "LNC", "name": "Dissolved oxygen"},
                ]
            )
        ]
    )
    crosswalk = TerminologyCrosswalk(umls)

    matches = crosswalk.suggest("Dissolved Oxygen")

    assert matches[0].code == "11556-8"
    assert matches[0].score >= matches[1].score


def test_out_of_vocabulary_results_are_dropped():
    umls = FakeUMLS(
        [
            _result(
                [
                    {"ui": "123", "rootSource": "ICD10CM", "name": "Some ICD-10 concept"},
                    {"ui": "11556-8", "rootSource": "LNC", "name": "Dissolved oxygen"},
                ]
            )
        ]
    )
    crosswalk = TerminologyCrosswalk(umls, vocabularies=("LNC",))

    matches = crosswalk.suggest("Dissolved Oxygen")

    assert len(matches) == 1
    assert matches[0].vocabulary == "LNC"
