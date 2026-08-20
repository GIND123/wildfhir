import pytest

from aquafhir.umls import UMLSClient, UMLSDisabledError, UMLSError
from tests.fakes import FakeUMLS


def test_missing_key_disables_the_client():
    client = UMLSClient(api_key="  ")

    assert client.enabled is False
    with pytest.raises(UMLSDisabledError):
        client.search("dissolved oxygen")


def test_search_returns_source_vocabulary_codes_not_cuis():
    client = FakeUMLS(
        [
            {
                "result": {
                    "results": [
                        {
                            "ui": "2731-1",
                            "rootSource": "LNC",
                            "name": "Sodium [Moles/volume] in Serum or Plasma",
                            "uri": "https://uts-ws.nlm.nih.gov/rest/content/current/source/LNC/2731-1",
                        }
                    ]
                }
            }
        ]
    )

    matches = client.search("sodium")

    assert matches[0].code == "2731-1"
    assert matches[0].root_source == "LNC"


def test_search_sends_the_documented_query_parameters():
    client = FakeUMLS([{"result": {"results": []}}])

    client.search("dissolved oxygen", vocabularies=("LNC",), limit=3)

    params = client.calls[0]
    assert params["apiKey"] == "test-key"
    assert params["string"] == "dissolved oxygen"
    assert params["sabs"] == "LNC"
    assert params["returnIdType"] == "code"
    assert params["pageSize"] == "3"


def test_placeholder_and_none_codes_are_dropped():
    client = FakeUMLS(
        [
            {
                "result": {
                    "results": [
                        {"ui": "NONE", "rootSource": "LNC", "name": "no match"},
                        {"ui": "", "rootSource": "LNC", "name": "empty code"},
                        {"ui": "2731-1", "rootSource": "LNC", "name": "Sodium"},
                    ]
                }
            }
        ]
    )

    matches = client.search("sodium")

    assert len(matches) == 1
    assert matches[0].code == "2731-1"


def test_broken_transport_raises_umls_error():
    client = FakeUMLS([UMLSError("simulated outage")])

    with pytest.raises(UMLSError, match="simulated outage"):
        client.search("sodium")
