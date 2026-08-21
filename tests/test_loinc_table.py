from pathlib import Path

import pytest

from aquafhir.loinc_table import LoincTable

HEADER = '"LOINC_NUM","COMPONENT","LONG_COMMON_NAME"\n'


def _table(tmp_path: Path, body: str, name: str = "LoincTableCore.csv") -> LoincTable:
    path = tmp_path / name
    path.write_text(HEADER + body, encoding="utf-8")
    return LoincTable(path)


def test_missing_file_disables_validation_instead_of_crashing(tmp_path: Path):
    table = LoincTable(tmp_path / "absent.csv")

    assert table.available is False
    assert table.codes == frozenset()


def test_published_codes_are_loaded(tmp_path: Path):
    table = _table(tmp_path, '"11556-8","Oxygen","Dissolved oxygen"\n"2731-1","Sodium","Sodium"\n')

    assert table.available is True
    assert table.contains("11556-8") is True
    assert table.contains("2731-1") is True


def test_unknown_code_is_rejected(tmp_path: Path):
    table = _table(tmp_path, '"11556-8","Oxygen","Dissolved oxygen"\n')

    assert table.contains("MTHU001949") is False
    assert table.contains("LP14752-7") is False


def test_surrounding_whitespace_does_not_defeat_the_check(tmp_path: Path):
    table = _table(tmp_path, '"11556-8","Oxygen","Dissolved oxygen"\n')

    assert table.contains("  11556-8  ") is True


def test_a_table_without_the_code_column_is_ignored(tmp_path: Path):
    path = tmp_path / "wrong.csv"
    path.write_text('"SOMETHING_ELSE","x"\n"11556-8","y"\n', encoding="utf-8")

    assert LoincTable(path).available is False


REAL_TABLE = Path(__file__).parents[1] / "loinc" / "LoincTableCore" / "LoincTableCore.csv"
real_table_only = pytest.mark.skipif(
    not REAL_TABLE.exists(), reason="licensed LOINC table not present"
)


@real_table_only
def test_the_real_committed_table_loads_and_contains_a_known_code():
    """Guards the actual artifact this repository ships, not just a fixture."""
    table = LoincTable(REAL_TABLE)

    assert table.available is True
    assert table.contains("11556-8") is True
    assert table.contains("MTHU001949") is False


@real_table_only
@pytest.mark.parametrize(
    ("oah_display", "expected_code"),
    [
        ("pH", "9481-3"),
        ("Chloride", "12530-2"),
        ("Electrical conductivity", "87444-6"),
    ],
)
def test_real_table_finds_the_right_environmental_code(oah_display: str, expected_code: str):
    """The codes a generic clinical search cannot surface, found locally.

    These are the exact OAH display terms from config/coding-rules.yaml.
    """
    results = LoincTable(REAL_TABLE).search(oah_display)

    assert results, f"no environmental LOINC candidate for {oah_display!r}"
    assert results[0][1].code == expected_code


@real_table_only
@pytest.mark.parametrize("oah_display", ["Dissolved Oxygen", "Water temperature"])
def test_real_table_stays_silent_where_environmental_loinc_has_no_term(oah_display: str):
    """Honest gaps beat plausible-looking wrong codes."""
    assert LoincTable(REAL_TABLE).search(oah_display) == []


# -- environmental search ---------------------------------------------------

SEARCH_ROWS = (
    '"LOINC_NUM","COMPONENT","SYSTEM","LONG_COMMON_NAME","STATUS"\n'
    '"9481-3","pH","Water","pH of Water","ACTIVE"\n'
    '"12530-2","Chloride","Water","Chloride [Moles/volume] in Water","ACTIVE"\n'
    '"38335-6","Vinyl chloride","Water","Vinyl chloride [Mass/volume] in Water","ACTIVE"\n'
    '"87444-6","Electron","Water","Electron [Electrical Conductivity] of Water","ACTIVE"\n'
    '"11556-8","Oxygen","Bld","Oxygen [Partial pressure] in Blood","ACTIVE"\n'
    '"55555-5","pH","Airway adaptor","pH at airway adaptor","ACTIVE"\n'
    '"99999-9","pH","Water","Deprecated pH of Water","DEPRECATED"\n'
)


def _search_table(tmp_path: Path) -> LoincTable:
    path = tmp_path / "LoincTableCore.csv"
    path.write_text(SEARCH_ROWS, encoding="utf-8")
    return LoincTable(path)


def test_exact_analyte_match_ranks_first(tmp_path: Path):
    results = _search_table(tmp_path).search("Chloride")

    assert results[0][1].code == "12530-2"
    assert results[0][0] == 1.0


def test_a_partial_analyte_match_ranks_below_the_exact_one(tmp_path: Path):
    codes = [entry.code for _score, entry in _search_table(tmp_path).search("Chloride")]

    assert codes.index("12530-2") < codes.index("38335-6")


def test_a_term_only_findable_through_the_full_name_is_still_found(tmp_path: Path):
    """The analyte for conductivity is 'Electron'; only the long name matches."""
    results = _search_table(tmp_path).search("Electrical conductivity")

    assert results[0][1].code == "87444-6"


def test_clinical_specimens_are_excluded(tmp_path: Path):
    """Blood is not an environmental specimen, however well the name matches."""
    codes = [entry.code for _score, entry in _search_table(tmp_path).search("Oxygen")]

    assert "11556-8" not in codes


def test_airway_systems_are_not_treated_as_air_quality(tmp_path: Path):
    """'Airway adaptor' is a respiratory device, not an environmental specimen."""
    codes = [entry.code for _score, entry in _search_table(tmp_path).search("pH")]

    assert codes == ["9481-3"]


def test_deprecated_terms_are_never_suggested(tmp_path: Path):
    codes = [entry.code for _score, entry in _search_table(tmp_path).search("pH")]

    assert "99999-9" not in codes


def test_deprecated_terms_still_validate(tmp_path: Path):
    """A deprecated code was legitimately published, so it is not 'invalid'."""
    assert _search_table(tmp_path).contains("99999-9") is True


def test_sharing_only_the_specimen_word_is_not_a_match(tmp_path: Path):
    """'water temperature' must not drag in every Water-system term."""
    assert _search_table(tmp_path).search("Water temperature") == []


def test_a_concept_absent_from_environmental_loinc_returns_nothing(tmp_path: Path):
    assert _search_table(tmp_path).search("Dissolved Oxygen") == []
