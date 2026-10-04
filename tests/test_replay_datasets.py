"""The twelve real incidents load from one file through the console's replay button."""

import pytest
from fastapi.testclient import TestClient

from aquafhir import main
from aquafhir.config import Settings
from aquafhir.models import ReviewStatus


@pytest.fixture
def settings_without_key(monkeypatch) -> Settings:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    return settings


def client_for(service) -> TestClient:
    main.app.dependency_overrides[main.get_service] = lambda: service
    return TestClient(main.app)


def test_the_default_replay_is_unchanged_and_names_its_source(service, settings_without_key):
    proposals = client_for(service).post("/api/v1/replay").json()

    assert len(proposals) == 5
    payload = proposals[0]["reading"]["raw_payload"]
    assert payload["replay_source"] == "data/oder-replay.csv"
    assert payload["incident_fixture"] == "oder-replay"
    assert payload["synthetic"] is True


def test_incidents_csv_loads_every_real_incident_row_as_pending(service, settings_without_key):
    response = client_for(service).post("/api/v1/replay", params={"dataset": "incidents"})

    assert response.status_code == 201
    proposals = response.json()
    assert len(proposals) == 83
    assert {item["status"] for item in proposals} == {ReviewStatus.PENDING.value}
    fixtures = []
    for item in proposals:
        payload = item["reading"]["raw_payload"]
        assert payload["replay_source"] == "data/incidents.csv"
        if not fixtures or fixtures[-1] != payload["incident_fixture"]:
            fixtures.append(payload["incident_fixture"])
    assert len(fixtures) == 12
    assert fixtures[0] == "oder-2022" and fixtures[-1] == "brixham-2024"
    assert "edge-cases" not in fixtures and "coimbra-citizen-2026" not in fixtures
    assert proposals[0]["reading"]["raw_payload"]["incident_title"].startswith("Oder River")


def test_an_unknown_dataset_is_refused(service, settings_without_key):
    response = client_for(service).post("/api/v1/replay", params={"dataset": "../etc"})
    assert response.status_code == 422


def test_a_full_round_reviews_every_row_and_routes_the_documented_alerts(
    service, settings_without_key
):
    client = client_for(service)

    response = client.post(
        "/api/v1/replay/run", params={"dataset": "incidents", "reviewer": "tester@example.org"}
    )

    assert response.status_code == 201
    report = response.json()
    assert report["loaded"] == 83
    # docs/incidents.md, no model key: 66 coded rows across the twelve incidents.
    assert report["approved"] == 66 and report["rejected"] == 17
    assert report["chain"]["valid"] is True
    assert report["fhir_write_mode"] == "dry-run"
    assert report["audiences"] == ["public-health", "veterinary", "water-authority"]
    by_id = {f["id"]: f for f in report["fixtures"]}
    assert len(by_id) == 12
    havelock = by_id["havelock-north-2016"]
    assert (havelock["coded"], havelock["withheld"], havelock["refused"]) == (8, 1, 1)
    assert havelock["title"].startswith("Havelock North")
    fired = {(a["rule_code"], a["severity"]) for a in report["alerts"]}
    assert {("coliforms", "critical"), ("lead-dissolved", "critical"), ("ph", "critical")} <= fired
    # Every incident raised something, nothing is left pending, every decision is attributed.
    assert all(f["alerts"] >= 1 for f in report["fixtures"])
    proposals = client.get("/api/v1/proposals", params={"limit": 500}).json()
    assert {p["status"] for p in proposals} == {"approved", "rejected"}
    assert {p["reviewer"] for p in proposals} == {"tester@example.org"}


def test_a_full_round_on_the_oder_replay_raises_its_three_alerts(service, settings_without_key):
    report = client_for(service).post("/api/v1/replay/run", params={"reviewer": "t@x.org"}).json()

    assert report["loaded"] == 5 and report["approved"] == 5 and len(report["alerts"]) == 3
    assert report["fixtures"][0]["id"] == "oder-replay"


def test_loading_a_dataset_twice_never_shows_a_reading_twice(service, settings_without_key):
    client = client_for(service)

    first = client.post("/api/v1/replay", params={"dataset": "incidents"}).json()
    again = client.post("/api/v1/replay", params={"dataset": "incidents"}).json()
    rerun = client.post(
        "/api/v1/replay/run", params={"dataset": "incidents", "reviewer": "t@x.org"}
    ).json()

    assert len(first) == 83 and again == [] and rerun["loaded"] == 0
    proposals = client.get("/api/v1/proposals", params={"limit": 500}).json()
    assert len(proposals) == 83
    assert not any(p["duplicate_of"] for p in proposals)


def test_the_demo_seed_fills_all_three_columns_once(service, settings_without_key):
    counts = service.seed_demo_board()

    # One pending reading held back per incident; the rest decided as a full round would.
    assert counts == {"loaded": 83, "pending": 12, "approved": 54, "rejected": 17}
    proposals = client_for(service).get("/api/v1/proposals", params={"limit": 500}).json()
    by_status: dict[str, set[str]] = {}
    for p in proposals:
        fixture = p["reading"]["raw_payload"]["incident_fixture"]
        by_status.setdefault(p["status"], set()).add(fixture)
    assert set(by_status) == {"pending", "approved", "rejected"}
    assert len(by_status["pending"]) == 12
    assert not any(p["duplicate_of"] for p in proposals)
    assert client_for(service).get("/api/v1/alerts").json()

    assert service.seed_demo_board() == {"loaded": 0, "pending": 0, "approved": 0, "rejected": 0}
    assert len(client_for(service).get("/api/v1/proposals", params={"limit": 500}).json()) == 83


def test_startup_seeds_the_board_only_when_asked(monkeypatch, tmp_path):
    seeded = Settings(_env_file=None, database_path=tmp_path / "hosted.db", seed_demo_board=True)
    monkeypatch.setattr(main, "get_settings", lambda: seeded)
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as client:
        listed = client.get("/api/v1/proposals", params={"limit": 500}).json()
    statuses = {p["status"] for p in listed}
    assert statuses == {"pending", "approved", "rejected"}

    plain = Settings(_env_file=None, database_path=tmp_path / "local.db")
    monkeypatch.setattr(main, "get_settings", lambda: plain)
    with TestClient(main.app) as client:
        assert client.get("/api/v1/proposals").json() == []


def test_the_seed_tops_up_a_column_that_would_open_empty(service, settings_without_key):
    """A shared demo whose visitors decided everything still opens with cards.

    The load pass skips readings the board already holds, so on its own it
    would leave such a board exactly as the visitors left it: loaded, and
    missing a column.
    """
    client = client_for(service)
    # The board a visitor leaves behind by pressing the replay button: every
    # reading loaded, nothing reviewed, so two of the three columns are empty.
    client.post("/api/v1/replay", params={"dataset": "incidents"})
    assert {p["status"] for p in client.get("/api/v1/proposals", params={"limit": 500}).json()} == {
        "pending"
    }

    service.seed_demo_board()

    proposals = client.get("/api/v1/proposals", params={"limit": 500}).json()
    counts: dict[str, int] = {}
    for proposal in proposals:
        counts[proposal["status"]] = counts.get(proposal["status"], 0) + 1
    assert all(counts.get(column) for column in ("pending", "approved", "rejected"))
    # One publishable reading per incident stays pending, the shape a fresh
    # seed leaves, and no reading is shown twice.
    assert counts["pending"] >= 12
    assert not any(p["duplicate_of"] for p in proposals)


def test_the_seed_refills_pending_after_every_card_was_decided(service, settings_without_key):
    client = client_for(service)
    service.seed_demo_board()
    for proposal in client.get("/api/v1/proposals", params={"limit": 500}).json():
        if proposal["status"] == "pending":
            client.post(
                f"/api/v1/proposals/{proposal['id']}/approve", json={"reviewer": "judge@x.org"}
            )
    assert not [
        p
        for p in client.get("/api/v1/proposals", params={"limit": 500}).json()
        if p["status"] == "pending"
    ]

    service.seed_demo_board()

    proposals = client.get("/api/v1/proposals", params={"limit": 500}).json()
    assert [p for p in proposals if p["status"] == "pending"]
    assert not any(p["duplicate_of"] for p in proposals)


def test_a_render_service_seeds_itself_without_the_setting(monkeypatch, tmp_path):
    """RENDER is set by Render itself, so the hosted board fills even if the
    dashboard predates render.yaml and never carried SEED_DEMO_BOARD."""
    hosted = Settings(_env_file=None, database_path=tmp_path / "hosted.db", render=True)
    assert hosted.should_seed_demo_board and not hosted.seed_demo_board
    monkeypatch.setattr(main, "get_settings", lambda: hosted)
    main.app.dependency_overrides.clear()

    with TestClient(main.app) as client:
        listed = client.get("/api/v1/proposals", params={"limit": 500}).json()
        health = client.get("/api/v1/health").json()

    assert {p["status"] for p in listed} == {"pending", "approved", "rejected"}
    # An empty board has to be able to say why, so the seed reports itself.
    assert "loaded 83" in health["board_seed"]
