"""Config-entry lifecycle tests."""

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.owlet_cam import CONFIG_SCHEMA
from custom_components.owlet_cam.api.exceptions import (
    OwletAuthenticationError,
    OwletConnectionError,
)
from custom_components.owlet_cam.api.models import (
    CameraSensors,
    CameraStatus,
    OwletCloudMetadata,
)
from custom_components.owlet_cam.const import (
    CONF_BRIDGE_CAMERA_ID,
    CONF_BRIDGE_PASSWORD,
    CONF_BRIDGE_URL,
    CONF_BRIDGE_USERNAME,
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    CONF_EMAIL,
    CONF_MODE,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_VERIFY_TLS,
    DOMAIN,
    MODE_DEVELOPMENT,
    MODE_EMBEDDED,
    MODE_EXTERNAL,
    REGION_EUROPE,
)

ENTITY_ID = "sensor.owlet_cam_integration_status"
DSN = "OCD123456789"


def test_yaml_configuration_is_reported(caplog: pytest.LogCaptureFixture) -> None:
    """A YAML block is reported and never used to configure an entry."""
    assert CONFIG_SCHEMA({}) == {}
    with caplog.at_level(logging.ERROR):
        config = CONFIG_SCHEMA({DOMAIN: {}})
    assert config == {DOMAIN: {}}
    assert "does not support YAML setup" in caplog.text


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Owlet Cam Development",
        data={CONF_MODE: MODE_DEVELOPMENT},
        unique_id=MODE_DEVELOPMENT,
    )


def _embedded_entry() -> MockConfigEntry:
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


def _external_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Nursery",
        data={
            CONF_MODE: MODE_EXTERNAL,
            CONF_BRIDGE_URL: "https://bridge.example.invalid:8088",
            CONF_BRIDGE_USERNAME: "api-user",
            CONF_BRIDGE_PASSWORD: "fixture-bridge-password",
            CONF_VERIFY_TLS: True,
            CONF_BRIDGE_CAMERA_ID: "nursery",
            CONF_CAMERA_NAME: "Nursery",
        },
        unique_id="bridge-fixture",
    )


def _metadata() -> OwletCloudMetadata:
    return OwletCloudMetadata(
        account_id="fixture-account-id",
        camera_dsn=DSN,
        camera_uid_available=True,
        auth_key_available=True,
        av_password_available=True,
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )


async def test_setup_unload_and_reload(hass: HomeAssistant) -> None:
    """Setup, unload, and reload leave exactly one entity."""
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID) is not None
    assert len(hass.states.async_entity_ids("sensor")) == 1

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID) is not None
    assert len(hass.states.async_entity_ids("sensor")) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(ENTITY_ID) is None


async def test_remove_entry_cleanly(hass: HomeAssistant) -> None:
    """Removing an entry unloads its entity and leaves no integration tasks."""
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert hass.states.get(ENTITY_ID) is None
    assert not hass.services.async_services().get(DOMAIN)


async def test_embedded_setup_unload_and_reload(hass: HomeAssistant) -> None:
    """Embedded setup reloads cloud and runtime entities without duplicates."""
    entry = _embedded_entry()
    entry.add_to_hass(hass)
    with (
        patch("custom_components.owlet_cam.OwletCloudClient") as client_class,
        patch(
            "custom_components.owlet_cam.OwletRuntimeManager."
            "async_schedule_previous_validation_restore",
            autospec=True,
        ) as schedule_restore,
    ):
        validate = AsyncMock(return_value=_metadata())
        client_class.return_value.async_validate_configured_camera = validate

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert hass.states.get("binary_sensor.nursery_cloud_reachable") is not None
        assert (
            hass.states.get("binary_sensor.nursery_camera_credentials_available")
            is not None
        )
        assert hass.states.get("sensor.nursery_authentication_expiry") is not None
        assert len(hass.states.async_entity_ids("camera")) == 1

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert len(hass.states.async_entity_ids("binary_sensor")) == 4
        assert len(hass.states.async_entity_ids("sensor")) == 11

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert not hass.states.async_entity_ids("binary_sensor")
    assert not hass.states.async_entity_ids("sensor")
    assert not hass.states.async_entity_ids("camera")
    assert validate.await_count == 2
    assert schedule_restore.call_count == 2


async def test_external_setup_exposes_native_camera_and_room_entities(
    hass: HomeAssistant,
) -> None:
    entry = _external_entry()
    entry.add_to_hass(hass)
    with patch("custom_components.owlet_cam.OwletHttpBridgeClient") as client_class:
        client = client_class.return_value
        client.async_get_status = AsyncMock(
            return_value=CameraStatus(online=True, stream_healthy=True)
        )
        client.async_get_sensors = AsyncMock(
            return_value=CameraSensors(
                temperature=21.5,
                humidity=48,
                sound_level=33,
                illuminance=7,
                wifi_signal=-61,
            )
        )
        client.async_get_stream_source = AsyncMock(
            return_value="rtsp://bridge.example.invalid:18554/nursery"
        )
        client.async_get_snapshot = AsyncMock(return_value=b"\xff\xd8fixture\xff\xd9")

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        expected_states = {
            "camera.nursery": "streaming",
            "sensor.nursery_temperature": "21.5",
            "sensor.nursery_humidity": "48",
            "binary_sensor.nursery_bridge_online": "on",
            "binary_sensor.nursery_camera_online": "on",
            "binary_sensor.nursery_stream_healthy": "on",
        }
        for entity_id, expected_state in expected_states.items():
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == expected_state

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert not hass.states.async_entity_ids("camera")
    assert not hass.states.async_entity_ids("sensor")
    assert not hass.states.async_entity_ids("binary_sensor")


async def test_temporary_outage_uses_setup_retry(hass: HomeAssistant) -> None:
    entry = _embedded_entry()
    entry.add_to_hass(hass)
    with patch("custom_components.owlet_cam.OwletCloudClient") as client_class:
        client_class.return_value.async_validate_configured_camera = AsyncMock(
            side_effect=OwletConnectionError("safe")
        )
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_invalid_credentials_start_reauthentication(
    hass: HomeAssistant,
) -> None:
    entry = _embedded_entry()
    entry.add_to_hass(hass)
    with patch("custom_components.owlet_cam.OwletCloudClient") as client_class:
        client_class.return_value.async_validate_configured_camera = AsyncMock(
            side_effect=OwletAuthenticationError("safe")
        )
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"].get("source") == config_entries.SOURCE_REAUTH
        for flow in hass.config_entries.flow.async_progress()
    )
