from datetime import UTC, datetime

from aquafhir.models import RawReading, SourceType


def reading(parameter: str = "EC", value: float = 2350, unit: str = "uS/cm") -> RawReading:
    return RawReading(
        source_id="agency-1",
        source_type=SourceType.AGENCY,
        parameter=parameter,
        value=value,
        unit=unit,
        observed_at=datetime(2022, 7, 27, tzinfo=UTC),
        site_code="oder-kostrzyn",
        site_name="Oder at Kostrzyn",
        latitude=52.5887,
        longitude=14.6495,
    )


def test_curated_alias_and_ucum_conversion(service):
    proposal = service.propose(reading())

    assert proposal.coding is not None
    assert proposal.coding.code == "electrical-conductivity"
    assert proposal.normalized_value == 2.35
    assert proposal.normalized_unit == "mS/cm"
    assert proposal.requires_review is True


def test_unknown_parameter_is_not_auto_coded(service):
    proposal = service.propose(reading("mystery rainbow foam", 1, "1"))

    assert proposal.coding is None
    assert proposal.normalized_value is None
    assert proposal.requires_review is True

