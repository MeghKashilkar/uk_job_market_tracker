"""API contract tests.

Filtered requests are exercised explicitly: an unfiltered call does not
validate the query-parameter models at all, so a broken filter dependency
passes every smoke test that only hits the bare endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from api import refresh as refresh_service
from api.main import app
from api.state import get_dataset


def _has_data() -> bool:
    """Whether the processed dataset exists, so the suite can skip rather than fail."""
    try:
        get_dataset()
    except FileNotFoundError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _has_data(),
    reason="processed dataset not built; run python -m src.process_data",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def a_role(client: TestClient) -> str:
    roles = client.get("/api/meta").json()["filters"]["role_category"]
    return roles[0]


def test_health_reports_loaded_dataset(client: TestClient) -> None:
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["dataset_rows"] > 0


READ_ENDPOINTS = [
    "/api/overview",
    "/api/skills",
    "/api/skills/trend",
    "/api/salary",
    "/api/postings",
]


@pytest.mark.parametrize("path", [*READ_ENDPOINTS, "/api/meta"])
def test_endpoints_respond_unfiltered(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_endpoints_respond_when_filtered(client: TestClient, path: str, a_role: str) -> None:
    """Regression: a query value must actually validate against the filter model."""
    response = client.get(path, params={"role_category": a_role})
    assert response.status_code == 200, response.text


def test_filtering_narrows_the_result_set(client: TestClient, a_role: str) -> None:
    everything = client.get("/api/overview").json()["totals"]["postings"]
    filtered = client.get("/api/overview", params={"role_category": a_role}).json()
    assert 0 < filtered["totals"]["postings"] < everything


def test_repeated_filter_values_are_combined(client: TestClient) -> None:
    roles = client.get("/api/meta").json()["filters"]["role_category"][:2]
    counts = [
        client.get("/api/overview", params={"role_category": role}).json()["totals"]["postings"]
        for role in roles
    ]
    both = client.get("/api/overview", params={"role_category": roles}).json()
    assert both["totals"]["postings"] == sum(counts)


def test_unknown_filter_value_yields_empty_not_error(client: TestClient) -> None:
    payload = client.get("/api/overview", params={"role_category": "Not A Real Role"}).json()
    assert payload["totals"]["postings"] == 0


def test_skill_limit_is_respected(client: TestClient) -> None:
    payload = client.get("/api/skills", params={"limit": 5}).json()
    assert len(payload["skills"]) <= 5


def test_skill_limit_is_bounded(client: TestClient) -> None:
    assert client.get("/api/skills", params={"limit": 9999}).status_code == 422


def test_predict_returns_a_plausible_salary(client: TestClient, a_role: str) -> None:
    meta = client.get("/api/meta").json()
    response = client.post(
        "/api/predict",
        json={
            "role_category": a_role,
            "seniority": meta["filters"]["seniority"][0],
            "region": meta["filters"]["region"][0],
            "contract_type": meta["filters"]["contract_type"][0],
            "contract_time": "full_time",
            "skills": ["Python", "SQL"],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert 10_000 < payload["predicted_salary"] < 500_000
    assert payload["lower_bound"] < payload["predicted_salary"] < payload["upper_bound"]


def test_predict_separates_known_from_unknown_skills(client: TestClient, a_role: str) -> None:
    meta = client.get("/api/meta").json()
    payload = client.post(
        "/api/predict",
        json={
            "role_category": a_role,
            "seniority": meta["filters"]["seniority"][0],
            "region": meta["filters"]["region"][0],
            "contract_type": meta["filters"]["contract_type"][0],
            "contract_time": "full_time",
            "skills": ["Python", "Definitely Not A Skill"],
        },
    ).json()
    assert payload["skills_recognised"] == ["Python"]
    assert payload["skills_ignored"] == ["Definitely Not A Skill"]


def test_predict_rejects_a_missing_required_field(client: TestClient) -> None:
    assert client.post("/api/predict", json={"role_category": "Data Analyst"}).status_code == 422


# --------------------------------------------------------------------- refresh


def test_refresh_status_is_always_readable(client: TestClient) -> None:
    payload = client.get("/api/refresh/status").json()
    assert payload["status"] in {"idle", "running", "done", "failed"}
    assert isinstance(payload["available"], bool)


def test_meta_reports_whether_refresh_is_available(client: TestClient) -> None:
    assert "available" in client.get("/api/meta").json()["refresh"]


def test_refresh_is_rejected_without_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without Adzuna keys the endpoint must refuse rather than half-run."""
    monkeypatch.setattr(refresh_service, "is_available", lambda: False)
    response = client.post("/api/refresh")
    assert response.status_code == 503
    assert "ADZUNA_APP_ID" in response.json()["detail"]


def test_refresh_is_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The cooldown protects the Adzuna free-tier quota from a public button."""
    monkeypatch.setattr(refresh_service, "is_available", lambda: True)
    monkeypatch.setattr(refresh_service, "cooldown_remaining", lambda: 42)
    response = client.post("/api/refresh")
    assert response.status_code == 429
    assert "42s" in response.json()["detail"]


def test_refresh_is_rejected_while_one_is_running(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(refresh_service, "is_available", lambda: True)
    monkeypatch.setattr(refresh_service, "is_running", lambda: True)
    assert client.post("/api/refresh").status_code == 409
