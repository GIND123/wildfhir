

def test_wrong_unit_does_not_trigger_even_with_same_number(service):
    observation = {
        "resourceType": "Observation",
        "id": "obs-1",
        "code": {"coding": [{"code": "electrical-conductivity"}]},
        "subject": {"reference": "Location/oder"},
        "effectiveDateTime": "2022-07-27T08:00:00Z",
        "valueQuantity": {"value": 2350, "code": "uS/cm"},
    }

    assert service.thresholds.evaluate(observation) == []

