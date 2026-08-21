"""Tests for Owlet Cam user, reauth, reconfigure, and options flows."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.owlet_cam.api.exceptions import (
    OwletAuthenticationError,
    OwletCameraNotFoundError,
    OwletConnectionError,
    OwletRateLimitError,
)
from custom_components.owlet_cam.api.models import OwletCloudMetadata
from custom_components.owlet_cam.const import (
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    CONF_DEBUG_LOGGING,
    CONF_EMAIL,
    CONF_ENABLE_AUDIO,
    CONF_EXPERIMENTAL_LOCAL_SENSORS,
    CONF_IDLE_TIMEOUT,
    CONF_KEEP_WARM,
    CONF_MODE,
    CONF_NO_FRAME_TIMEOUT,
    CONF_PASSWORD,
    CONF_PREFER_DIRECT_P2P,
    CONF_RECONNECT_BACKOFF,
    CONF_REGION,
    CONF_RUNTIME_CHANNEL,
    CONF_STREAM_QUALITY,
    CONF_UPDATE_INTERVAL,
    DEV_MODE_ENV,
    DOMAIN,
    MODE_DEVELOPMENT,
    MODE_EMBEDDED,
    MODE_EXTERNAL,
    REGION_EUROPE,
)

DSN = "OCD123456789"


def _input(**updates: object) -> dict[str, object]:
    data: dict[str, object] = {
        CONF_EMAIL: "parent@example.invalid",
        CONF_PASSWORD: "fixture-account-password",
        CONF_REGION: REGION_EUROPE,
        CONF_CAMERA_DSN: DSN.lower(),
        CONF_CAMERA_NAME: "Nursery",
    }
    data.update(updates)
    return data


def _metadata() -> OwletCloudMetadata:
    return OwletCloudMetadata(
        account_id="fixture-account-id",
        camera_dsn=DSN,
        camera_uid_available=True,
        auth_key_available=True,
        av_password_available=True,
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Nursery",
        data={CONF_MODE: MODE_EMBEDDED, **_input(CONF_CAMERA_DSN=DSN)},
        unique_id=DSN,
    )


async def test_ordinary_flow_hides_development_mode(hass: HomeAssistant) -> None:
    """The ordinary selector exposes only external and embedded modes."""
    with patch.dict("os.environ", {}, clear=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    mode_validator = next(iter(result["data_schema"].schema.values()))
    assert mode_validator(MODE_EXTERNAL) == MODE_EXTERNAL
    assert mode_validator(MODE_EMBEDDED) == MODE_EMBEDDED


async def test_external_mode_is_deferred(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_MODE: MODE_EXTERNAL},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "external_not_available"


async def test_development_flow_create_and_reject_duplicate(
    hass: HomeAssistant,
) -> None:
    """The explicit development switch creates exactly one config entry."""
    with patch.dict("os.environ", {DEV_MODE_ENV: "1"}, clear=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_DEVELOPMENT},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_DEVELOPMENT},
        )

    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"


async def test_development_input_rejected_without_switch(hass: HomeAssistant) -> None:
    with patch.dict("os.environ", {}, clear=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_DEVELOPMENT},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "development_disabled"


async def test_embedded_success_normalizes_and_creates(hass: HomeAssistant) -> None:
    """Successful validation stores no cloud or KMS token material."""
    with patch(
        "custom_components.owlet_cam.config_flow.OwletCloudClient"
    ) as client_class:
        client_class.return_value.async_validate_camera = AsyncMock(
            return_value=_metadata()
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_EMBEDDED},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _input()
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Nursery"
    assert result["data"][CONF_CAMERA_DSN] == DSN
    assert result["data"][CONF_MODE] == MODE_EMBEDDED
    serialized = str(result["data"])
    for secret in ("fixture-firebase-token", "fixture-camera-uid", "fixture-auth-key"):
        assert secret not in serialized


async def test_duplicate_dsn_is_rejected(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.owlet_cam.config_flow.OwletCloudClient"
    ) as client_class:
        client_class.return_value.async_validate_camera = AsyncMock(
            return_value=_metadata()
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_EMBEDDED},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _input()
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_flow_recovers_after_each_safe_error(hass: HomeAssistant) -> None:
    """A failed flow remains usable and can complete successfully."""
    errors = [
        (OwletAuthenticationError("safe"), "invalid_auth"),
        (OwletCameraNotFoundError("safe"), "camera_not_found"),
        (OwletRateLimitError("safe"), "rate_limited"),
        (OwletConnectionError("safe"), "cannot_connect"),
    ]
    for exception, error_key in errors:
        with patch(
            "custom_components.owlet_cam.config_flow.OwletCloudClient"
        ) as client_class:
            validate = AsyncMock(side_effect=[exception, _metadata()])
            client_class.return_value.async_validate_camera = validate
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={CONF_MODE: MODE_EMBEDDED},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], _input()
            )
            assert result["type"] is FlowResultType.FORM
            assert result["errors"] == {"base": error_key}
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                _input(**{CONF_CAMERA_DSN: f"OCD{len(errors)}23456789"}),
            )
            assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.config_entries.async_remove(result["result"].entry_id)


async def test_invalid_dsn_errors_do_not_call_network(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.owlet_cam.config_flow.OwletCloudClient"
    ) as client_class:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_EMBEDDED},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _input(**{CONF_CAMERA_DSN: "0CD123456789"})
        )
    assert result["errors"] == {"base": "invalid_dsn_zero"}
    client_class.assert_not_called()


async def test_invalid_email_recovers_without_network(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.owlet_cam.config_flow.OwletCloudClient"
    ) as client_class:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_EMBEDDED},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _input(**{CONF_EMAIL: "not-an-email"})
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_email"}
    client_class.assert_not_called()


async def test_reauthentication_error_then_success_reloads_once(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.owlet_cam.config_flow.OwletCloudClient"
        ) as client_class,
        patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload,
    ):
        client_class.return_value.async_validate_camera = AsyncMock(
            side_effect=[OwletAuthenticationError("safe"), _metadata()]
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=dict(entry.data),
        )
        assert result["step_id"] == "reauth_confirm"
        wrong = {
            CONF_EMAIL: "parent@example.invalid",
            CONF_PASSWORD: "wrong-password",
            CONF_REGION: REGION_EUROPE,
        }
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], wrong
        )
        assert result["errors"] == {"base": "invalid_auth"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**wrong, CONF_PASSWORD: "corrected-password"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "corrected-password"
    schedule_reload.assert_called_once_with(entry.entry_id)
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reconfigure_updates_existing_entry_once(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.owlet_cam.config_flow.OwletCloudClient"
        ) as client_class,
        patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload,
    ):
        client_class.return_value.async_validate_camera = AsyncMock(
            return_value=_metadata()
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _input(**{CONF_CAMERA_NAME: "Baby room"})
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Baby room"
    schedule_reload.assert_called_once_with(entry.entry_id)
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_options_are_grouped_and_reload_exactly_once(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    general = {
        CONF_UPDATE_INTERVAL: 600,
        CONF_KEEP_WARM: False,
        CONF_IDLE_TIMEOUT: 90,
        CONF_STREAM_QUALITY: "high",
        CONF_ENABLE_AUDIO: False,
        CONF_DEBUG_LOGGING: True,
    }
    embedded = {
        CONF_RUNTIME_CHANNEL: "stable",
        CONF_RECONNECT_BACKOFF: 30,
        CONF_NO_FRAME_TIMEOUT: 15,
        CONF_PREFER_DIRECT_P2P: False,
        CONF_EXPERIMENTAL_LOCAL_SENSORS: False,
    }
    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["step_id"] == "general"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], general
        )
        assert result["step_id"] == "embedded"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], embedded
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**general, **embedded}
    schedule_reload.assert_called_once_with(entry.entry_id)
