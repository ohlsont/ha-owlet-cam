"""Diagnostic sensor tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

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
    MODE_DEVELOPMENT,
    MODE_EMBEDDED,
    REGION_EUROPE,
)
from custom_components.owlet_cam.runtime.media_probe import MediaProbeResult

DSN = "OCD123456789"


async def test_sensor_properties_use_cached_coordinator_data(
    hass: HomeAssistant,
) -> None:
    """Reading entity state must never touch a network or filesystem client."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Owlet Cam Development",
        data={CONF_MODE: MODE_DEVELOPMENT},
        unique_id=MODE_DEVELOPMENT,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.client = Mock(side_effect=AssertionError("I/O attempted"))

    state = hass.states.get("sensor.owlet_cam_integration_status")
    assert state is not None
    assert state.state == "ready"
    entry.runtime_data.client.assert_not_called()


async def test_embedded_entity_properties_use_only_cached_data(
    hass: HomeAssistant,
) -> None:
    """Reading all cloud entity properties cannot call the client."""
    entry = MockConfigEntry(
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
    entry.add_to_hass(hass)
    expiry = datetime.now(UTC) + timedelta(hours=1)
    metadata = OwletCloudMetadata(
        account_id="fixture-account-id",
        camera_dsn=DSN,
        camera_uid_available=True,
        auth_key_available=True,
        av_password_available=True,
        token_expiry=expiry,
    )
    with patch("custom_components.owlet_cam.OwletCloudClient") as client_class:
        validate = AsyncMock(return_value=metadata)
        client_class.return_value.async_validate_configured_camera = validate
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        validate.reset_mock()

        cloud = hass.states.get("binary_sensor.nursery_cloud_reachable")
        credentials = hass.states.get(
            "binary_sensor.nursery_camera_credentials_available"
        )
        auth_expiry = hass.states.get("sensor.nursery_authentication_expiry")
        manager = entry.runtime_data.runtime_manager
        assert manager is not None
        manager.snapshot.last_stream_probe = MediaProbeResult(
            codec="h264",
            profile="High",
            level=40,
            width=1920,
            height=1080,
            fps=14.0,
            bitrate_kbps=750.0,
            frames=112,
            container="mpegts",
        )
        manager.snapshot.last_stream_probe_at = expiry
        manager._notify_listeners()
        await hass.async_block_till_done()
        resolution = hass.states.get("sensor.nursery_detected_resolution")
        fps = hass.states.get("sensor.nursery_detected_fps")
        codec = hass.states.get("sensor.nursery_stream_codec")
        profile = hass.states.get("sensor.nursery_stream_profile")
        bitrate = hass.states.get("sensor.nursery_stream_bitrate")

    assert cloud is not None
    assert cloud.state == "on"
    assert credentials is not None
    assert credentials.state == "on"
    assert auth_expiry is not None
    assert resolution is not None
    assert resolution.state == "1920x1080"
    assert fps is not None
    assert fps.state == "14.0"
    assert codec is not None
    assert codec.state == "h264"
    assert profile is not None
    assert profile.state == "High"
    assert bitrate is not None
    assert bitrate.state == "750.0"
    validate.assert_not_awaited()
