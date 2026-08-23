"""Authenticated runtime administration API tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.owlet_cam.api.models import OwletCloudMetadata
from custom_components.owlet_cam.const import (
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    CONF_EMAIL,
    CONF_MODE,
    CONF_PASSWORD,
    CONF_REGION,
    DOMAIN,
    MODE_EMBEDDED,
    REGION_EUROPE,
)
from custom_components.owlet_cam.runtime.manager import OwletRuntimeError

DSN = "OCD123456789"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Nursery",
        data={
            CONF_MODE: MODE_EMBEDDED,
            CONF_EMAIL: "parent@example.invalid",
            CONF_PASSWORD: "fixture-account-password",
            CONF_REGION: REGION_EUROPE,
            CONF_CAMERA_DSN: DSN,
            CONF_CAMERA_NAME: "Nursery",
        },
        unique_id=DSN,
    )


def _metadata() -> OwletCloudMetadata:
    return OwletCloudMetadata(
        account_id="fixture-account",
        camera_dsn=DSN,
        camera_uid_available=True,
        auth_key_available=True,
        av_password_available=True,
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    with (
        patch("custom_components.owlet_cam.OwletCloudClient") as client_class,
        patch(
            "custom_components.owlet_cam.OwletRuntimeManager."
            "async_schedule_previous_validation_restore"
        ),
    ):
        client_class.return_value.async_validate_configured_camera = AsyncMock(
            return_value=_metadata()
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_runtime_api_requires_authentication(
    hass: HomeAssistant, hass_client_no_auth
) -> None:
    await _setup(hass)
    client = await hass_client_no_auth()
    response = await client.get("/api/owlet_cam/runtime")
    assert response.status == 401


async def test_runtime_api_requires_administrator(
    hass: HomeAssistant, hass_client, hass_read_only_user
) -> None:
    await _setup(hass)
    refresh_token = await hass.auth.async_create_refresh_token(
        hass_read_only_user, client_id="http://pytest.local/"
    )
    access_token = hass.auth.async_create_access_token(refresh_token)
    client = await hass_client(access_token)
    response = await client.get("/api/owlet_cam/runtime")
    assert response.status == 403


async def test_admin_upload_status_and_confirmed_delete(
    hass: HomeAssistant, hass_client
) -> None:
    entry = await _setup(hass)
    client = await hass_client()

    response = await client.post(
        f"/api/owlet_cam/runtime/{entry.entry_id}/application",
        data=b"fixture-private-application",
        headers={"X-Owlet-Archive-Extension": ".apk"},
    )
    assert response.status == 201
    payload = await response.json()
    assert payload["ok"] is True
    assert payload["size"] == len(b"fixture-private-application")
    assert "path" not in str(payload).lower()

    response = await client.get("/api/owlet_cam/runtime")
    assert response.status == 200
    payload = await response.json()
    assert payload["entries"][0]["runtime"]["application"]["status"] == "uploaded"

    response = await client.delete(
        f"/api/owlet_cam/runtime/{entry.entry_id}/application"
    )
    assert response.status == 428

    response = await client.delete(
        f"/api/owlet_cam/runtime/{entry.entry_id}/application",
        headers={"X-Owlet-Confirm-Delete": "delete-proprietary-files"},
    )
    assert response.status == 200
    payload = await response.json()
    assert payload["runtime"]["application"]["status"] == "deleted"
    assert payload["runtime"]["application"]["proprietary_files_present"] is False


async def test_unknown_runtime_action_is_rejected(
    hass: HomeAssistant, hass_client
) -> None:
    entry = await _setup(hass)
    client = await hass_client()
    response = await client.post(
        f"/api/owlet_cam/runtime/{entry.entry_id}/action/not-allowed"
    )
    assert response.status == 404


@pytest.mark.parametrize(
    ("action", "method"),
    [
        ("authentication-test", "async_run_authentication_test"),
        ("runtime-probe", "async_prepare_and_probe_libraries"),
        ("frame-probe", "async_run_frame_probe"),
        ("stream-probe", "async_run_stream_probe"),
        ("restart-stream", "async_restart_stream"),
    ],
)
async def test_allowlisted_runtime_actions(
    hass: HomeAssistant, hass_client, action: str, method: str
) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data.runtime_manager
    assert manager is not None
    client = await hass_client()
    with patch.object(manager, method, new_callable=AsyncMock) as call:
        response = await client.post(
            f"/api/owlet_cam/runtime/{entry.entry_id}/action/{action}"
        )
    assert response.status == 200
    call.assert_awaited_once_with()


async def test_runtime_action_returns_only_safe_error(
    hass: HomeAssistant, hass_client
) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data.runtime_manager
    assert manager is not None
    client = await hass_client()
    with patch.object(
        manager,
        "async_run_frame_probe",
        AsyncMock(side_effect=OwletRuntimeError("frame_probe_failed", "Safe failure")),
    ):
        response = await client.post(
            f"/api/owlet_cam/runtime/{entry.entry_id}/action/frame-probe"
        )
    assert response.status == 409
    assert await response.json() == {
        "code": "frame_probe_failed",
        "message": "Safe failure",
    }
