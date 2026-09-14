import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.v1.accounts import DEVELOPER_DEVICE_IDS
from app.main import app
from app.core.config import settings


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "authenticated_accounts_enabled", False)
    monkeypatch.setattr(settings, "developer_mode_enabled", True)
    monkeypatch.setattr(settings, "local_accounts_enabled", True)
    return TestClient(app)


def test_first_developer_login_with_slot_device_id(client: TestClient) -> None:
    # Use deterministic slot 1 device ID as the calling device
    device_id = str(DEVELOPER_DEVICE_IDS[0])
    response = client.post(
        "/v1/account/developer-login",
        json={"pin": "2468"},
        headers={"X-Device-Id": device_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["role"] == "developer"
    assert data["display_name"] == "Developer 1"
    assert data["developer_slot"] == 1


def test_repeated_developer_login_with_slot_device_is_idempotent(
    client: TestClient,
) -> None:
    device_id = str(DEVELOPER_DEVICE_IDS[0])
    # Subsequent calls must succeed without UniqueViolation or 500
    for _ in range(3):
        response = client.post(
            "/v1/account/developer-login",
            json={"pin": "2468"},
            headers={"X-Device-Id": device_id},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["role"] == "developer"
        assert data["developer_slot"] == 1


def test_developer_login_with_distinct_phone_device(client: TestClient) -> None:
    # A physical phone with a random UUID logs in as Developer 2 (pin 1357)
    phone_device_id = str(uuid.uuid4())
    response = client.post(
        "/v1/account/developer-login",
        json={"pin": "1357"},
        headers={"X-Device-Id": phone_device_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["role"] == "developer"
    assert data["display_name"] == "Developer 2"
    assert data["developer_slot"] == 2

    # Verify repeated login with the same phone device succeeds idempotently
    repeat_response = client.post(
        "/v1/account/developer-login",
        json={"pin": "1357"},
        headers={"X-Device-Id": phone_device_id},
    )
    assert repeat_response.status_code == 200, repeat_response.text
    assert repeat_response.json()["id"] == data["id"]


def test_developer_login_when_device_already_linked_to_another_account(client: TestClient) -> None:
    # Create a player local account for a phone
    phone_device_id = str(uuid.uuid4())
    create_resp = client.post(
        "/v1/account/local-accounts",
        json={"display_name": "Test Player"},
        headers={"X-Device-Id": phone_device_id},
    )
    assert create_resp.status_code == 200, create_resp.text
    player_account = create_resp.json()
    assert player_account["role"] == "player"

    # Now that device logs in as Developer 3 (pin 9876)
    dev_resp = client.post(
        "/v1/account/developer-login",
        json={"pin": "9876"},
        headers={"X-Device-Id": phone_device_id},
    )
    assert dev_resp.status_code == 200, dev_resp.text
    dev_account = dev_resp.json()
    assert dev_account["role"] == "developer"
    assert dev_account["developer_slot"] == 3
    assert dev_account["id"] != player_account["id"]

    # Re-checking account returns the developer account
    get_resp = client.get(
        "/v1/account",
        headers={"X-Device-Id": phone_device_id},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == dev_account["id"]


def test_invalid_developer_pin_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/account/developer-login",
        json={"pin": "0000"},
        headers={"X-Device-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 403
