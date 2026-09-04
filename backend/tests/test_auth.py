"""Stream A: HTTP Basic auth guard tests."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


CREDENTIALS = {"APP_USERNAME": "reviewer", "APP_PASSWORD": "s3cret"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key, value in CREDENTIALS.items():
        monkeypatch.setenv(key, value)
    return TestClient(app)


def test_health_stays_public(client: TestClient) -> None:
    """Deployment health checks must not require credentials."""

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_route_rejects_missing_credentials(client: TestClient) -> None:
    response = client.get("/api/session")

    assert response.status_code == 401
    # Without this header the browser never shows its credential prompt.
    assert response.headers["www-authenticate"].startswith("Basic")


def test_protected_route_accepts_configured_credentials(client: TestClient) -> None:
    response = client.get("/api/session", auth=("reviewer", "s3cret"))

    assert response.status_code == 200
    assert response.json() == {"username": "reviewer"}


@pytest.mark.parametrize(
    "auth_pair",
    [("reviewer", "wrong"), ("intruder", "s3cret"), ("intruder", "wrong")],
)
def test_protected_route_rejects_bad_credentials(
    client: TestClient, auth_pair: tuple[str, str]
) -> None:
    response = client.get("/api/session", auth=auth_pair)

    assert response.status_code == 401


def test_unconfigured_credentials_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset password must not be read as 'no auth on this deployment'."""

    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    unconfigured = TestClient(app)

    response = unconfigured.get("/api/session", auth=("reviewer", "s3cret"))

    assert response.status_code == 503


def test_config_exposes_no_credential_defaults() -> None:
    """A fallback credential in config would quietly undo the 503 above."""

    from backend.core import config

    assert not hasattr(config, "APP_USERNAME")
    assert not hasattr(config, "APP_PASSWORD")
