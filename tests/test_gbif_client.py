"""GBIF client: what it accepts, what it refuses, and how it fails.

The client's whole job is to be trustworthy over raw, uncurated source text,
so the refusal paths matter more here than the happy path.
"""

import httpx
import pytest

from aquafhir.gbif import GbifClient, GbifError
from tests.fakes import FakeGbif

EXACT = {
    "usageKey": 7513065,
    "scientificName": "Prymnesium parvum N.Carter",
    "canonicalName": "Prymnesium parvum",
    "rank": "SPECIES",
    "status": "ACCEPTED",
    "confidence": 99,
    "matchType": "EXACT",
    "kingdom": "Chromista",
    "phylum": "Haptophyta",
    "genus": "Prymnesium",
    "species": "Prymnesium parvum",
}


def test_an_exact_match_becomes_a_usable_taxon() -> None:
    match = FakeGbif([EXACT]).match("Prymnesium parvum")
    assert match is not None
    assert match.usage_key == 7513065
    assert match.rank == "SPECIES"
    assert "Chromista" in match.lineage and "Prymnesium" in match.lineage


def test_a_refusal_carrying_full_confidence_is_still_a_refusal() -> None:
    """The trap this client was written around.

    GBIF answers a miss with `matchType: NONE` *and* `confidence: 100`. Any
    implementation that thresholds on confidence accepts every miss, so the
    decision must key on `matchType` alone.
    """
    payload = {"matchType": "NONE", "confidence": 100, "synonym": False}
    assert FakeGbif([payload]).match("dissolved oxygen") is None


def test_a_higher_rank_guess_is_refused() -> None:
    """HIGHERRANK means GBIF got no further than a kingdom. Too coarse to publish."""
    payload = {"matchType": "HIGHERRANK", "usageKey": 6, "rank": "KINGDOM", "confidence": 95}
    assert FakeGbif([payload]).match("plantae something") is None


def test_a_match_without_a_key_or_rank_is_refused() -> None:
    assert FakeGbif([{"matchType": "EXACT", "confidence": 99}]).match("x") is None
    assert FakeGbif([{"matchType": "EXACT", "usageKey": 1, "confidence": 99}]).match("x") is None


def test_a_synonym_resolves_to_the_accepted_taxon() -> None:
    """Publishing the queried synonym key would pin a name GBIF has superseded."""
    payload = {
        "matchType": "EXACT", "usageKey": 111, "acceptedUsageKey": 222,
        "scientificName": "Old name", "acceptedScientificName": "Accepted name",
        "rank": "SPECIES", "status": "SYNONYM", "synonym": True, "confidence": 97,
    }
    match = FakeGbif([payload]).match("Old name")
    assert match is not None
    assert match.usage_key == 222
    assert match.scientific_name == "Accepted name"
    assert match.synonym is True


def test_an_empty_label_never_reaches_the_network() -> None:
    client = FakeGbif([EXACT])
    assert client.match("   ") is None
    assert client.calls == []


def test_a_disabled_client_refuses_rather_than_silently_returning_nothing() -> None:
    with pytest.raises(GbifError, match="disabled"):
        FakeGbif([EXACT], enabled=False).match("Prymnesium parvum")


# -- transport -------------------------------------------------------------


class _Transport(GbifClient):
    def __init__(self, responses: list[object]) -> None:
        super().__init__(max_retries=2, timeout=0.01)
        self.responses = list(responses)
        self.attempts = 0

    def _one(self):
        self.attempts += 1
        return self.responses.pop(0)


def _client(monkeypatch, responses):
    client = _Transport(responses)

    def fake_get(self, url, params=None):  # noqa: ANN001
        item = client._one()
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    return client


def _response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload if payload is not None else {})


def test_a_rate_limit_is_retried_then_succeeds(monkeypatch) -> None:
    client = _client(monkeypatch, [_response(429, {}), _response(200, EXACT)])
    assert client.match("Prymnesium parvum") is not None
    assert client.attempts == 2


def test_a_client_error_is_not_retried(monkeypatch) -> None:
    client = _client(monkeypatch, [_response(400, {})])
    with pytest.raises(GbifError, match="400"):
        client.match("x")
    assert client.attempts == 1


def test_a_network_error_is_retried_and_then_reported(monkeypatch) -> None:
    client = _client(monkeypatch, [httpx.ConnectError("boom")] * 3)
    with pytest.raises(GbifError, match="after retries"):
        client.match("x")
    assert client.attempts == 3


def test_a_non_object_body_is_an_error_not_a_crash(monkeypatch) -> None:
    client = _client(monkeypatch, [httpx.Response(200, json=[1, 2, 3])])
    with pytest.raises(GbifError, match="non-object"):
        client.match("x")
