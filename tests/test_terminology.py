from pathlib import Path

import pytest

from aquafhir.loinc_table import LoincTable
from aquafhir.terminology import TerminologyCrosswalk
from aquafhir.umls import UMLSClient, UMLSError
from tests.fakes import FakeUMLS


def _result(results: list[dict]) -> dict:
    return {"result": {"results": results}}


def _loinc_table(tmp_path: Path, *codes: str) -> LoincTable:
    """Codes only -- enough for validation, not searchable."""
    path = tmp_path / "LoincTableCore.csv"
    rows = "".join(f'"{code}","x"\n' for code in codes)
    path.write_text('"LOINC_NUM","COMPONENT"\n' + rows, encoding="utf-8")
    return LoincTable(path)


def _env_table(tmp_path: Path) -> LoincTable:
    """A searchable environmental table with one pH-of-Water term."""
    path = tmp_path / "env.csv"
    path.write_text(
        '"LOINC_NUM","COMPONENT","SYSTEM","LONG_COMMON_NAME","STATUS"\n'
        '"9481-3","pH","Water","pH of Water","ACTIVE"\n',
        encoding="utf-8",
    )
    return LoincTable(path)


def test_unavailable_with_no_source():
    crosswalk = TerminologyCrosswalk(UMLSClient(api_key=""))

    assert crosswalk.available is False
    assert crosswalk.sources() == []


def test_the_local_table_alone_makes_the_crosswalk_available(tmp_path: Path):
    """No UMLS key needed: environmental LOINC works entirely offline."""
    crosswalk = TerminologyCrosswalk(
        UMLSClient(api_key=""), loinc_table=_loinc_table(tmp_path, "9481-3")
    )

    assert crosswalk.available is True
    assert crosswalk.sources() == ["loinc-table"]


def test_local_environmental_matches_rank_above_umls(tmp_path: Path):
    """The whole point: 'pH of Water' must beat UMLS's clinical top hit."""
    umls = FakeUMLS(
        [_result([{"ui": "58008004", "rootSource": "SNOMEDCT_US", "name": "Peliosis hepatis"}])]
    )
    crosswalk = TerminologyCrosswalk(umls, loinc_table=_env_table(tmp_path))

    matches = crosswalk.suggest("pH")

    assert matches[0].code == "9481-3"
    assert matches[0].system == "http://loinc.org"


def test_umls_tops_up_when_local_matches_are_short(tmp_path: Path):
    umls = FakeUMLS(
        [_result([{"ui": "81065003", "rootSource": "SNOMEDCT_US", "name": "pH measurement"}])]
    )
    crosswalk = TerminologyCrosswalk(umls, loinc_table=_env_table(tmp_path))

    codes = [match.code for match in crosswalk.suggest("pH")]

    assert codes == ["9481-3", "81065003"]


def test_a_umls_outage_degrades_to_local_matches(tmp_path: Path):
    umls = FakeUMLS([UMLSError("simulated outage")])
    crosswalk = TerminologyCrosswalk(umls, loinc_table=_env_table(tmp_path))

    matches = crosswalk.suggest("pH")

    assert [match.code for match in matches] == ["9481-3"]


def test_a_umls_outage_with_no_local_match_is_surfaced(tmp_path: Path):
    """Never tell a reviewer 'no match' when the truth is 'lookup broke'."""
    umls = FakeUMLS([UMLSError("simulated outage")])
    crosswalk = TerminologyCrosswalk(umls, loinc_table=_env_table(tmp_path))

    with pytest.raises(UMLSError):
        crosswalk.suggest("Dissolved Oxygen")


def test_duplicate_codes_across_sources_appear_once(tmp_path: Path):
    umls = FakeUMLS([_result([{"ui": "9481-3", "rootSource": "LNC", "name": "pH of Water"}])])
    crosswalk = TerminologyCrosswalk(umls, loinc_table=_env_table(tmp_path))

    codes = [match.code for match in crosswalk.suggest("pH")]

    assert codes.count("9481-3") == 1


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


def test_loinc_parts_and_metathesaurus_ids_are_dropped(tmp_path: Path):
    """UMLS returns LP... and MTHU... ids that are not publishable LOINC codes."""
    umls = FakeUMLS(
        [
            _result(
                [
                    {"ui": "MTHU001949", "rootSource": "LNC", "name": "pH"},
                    {"ui": "LP14752-7", "rootSource": "LNC", "name": "pH"},
                    {"ui": "11556-8", "rootSource": "LNC", "name": "pH of Water"},
                ]
            )
        ]
    )
    crosswalk = TerminologyCrosswalk(
        umls, vocabularies=("LNC",), loinc_table=_loinc_table(tmp_path, "11556-8")
    )

    matches = crosswalk.suggest("pH")

    assert [match.code for match in matches] == ["11556-8"]


def test_snomed_codes_are_not_filtered_by_the_loinc_table(tmp_path: Path):
    umls = FakeUMLS(
        [_result([{"ui": "81065003", "rootSource": "SNOMEDCT_US", "name": "pH measurement"}])]
    )
    crosswalk = TerminologyCrosswalk(
        umls, loinc_table=_loinc_table(tmp_path, "11556-8")
    )

    matches = crosswalk.suggest("pH")

    assert [match.code for match in matches] == ["81065003"]


def test_without_a_loinc_table_nothing_is_filtered(tmp_path: Path):
    """A missing table degrades to no validation rather than dropping everything."""
    umls = FakeUMLS([_result([{"ui": "MTHU001949", "rootSource": "LNC", "name": "pH"}])])
    crosswalk = TerminologyCrosswalk(
        umls, vocabularies=("LNC",), loinc_table=LoincTable(tmp_path / "absent.csv")
    )

    matches = crosswalk.suggest("pH")

    assert [match.code for match in matches] == ["MTHU001949"]


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
