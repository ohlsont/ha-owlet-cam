"""Tests for Owlet Cam user, reauth, reconfigure, and options flows."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import FormData
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_setup_component,
)

from custom_components.owlet_cam.api.exceptions import (
    OwletAuthenticationError,
    OwletBridgeAuthenticationError,
    OwletBridgeCompatibilityError,
    OwletBridgeConnectionError,
    OwletCameraNotFoundError,
    OwletConnectionError,
    OwletRateLimitError,
)
from custom_components.owlet_cam.api.models import (
    BridgeCamera,
    BridgeInfo,
    OwletCloudMetadata,
)
from custom_components.owlet_cam.const import (
    CONF_BRIDGE_CAMERA_ID,
    CONF_BRIDGE_PASSWORD,
    CONF_BRIDGE_TIMEOUT,
    CONF_BRIDGE_URL,
    CONF_BRIDGE_USERNAME,
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    CONF_CONFIRM_DELETE,
    CONF_DEBUG_LOGGING,
    CONF_DELETE_PROPRIETARY_FILES,
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
    CONF_RETAIN_APPLICATION,
    CONF_RTSP_OVERRIDE,
    CONF_RUNTIME_CHANNEL,
    CONF_RUNTIME_PACKAGE,
    CONF_STREAM_QUALITY,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_TLS,
    DEV_MODE_ENV,
    DOMAIN,
    MODE_DEVELOPMENT,
    MODE_EMBEDDED,
    MODE_EXTERNAL,
    REGION_EUROPE,
)
from custom_components.owlet_cam.runtime.manager import OwletRuntimeError
from custom_components.owlet_cam.runtime.upload import OwletUploadError

DSN = "OCD123456789"
BRIDGE_URL = "https://bridge.example.invalid:8088"
FILE_ID = "00000000-0000-0000-0000-000000000001"


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


def _inspect_stored_upload(directory: Path) -> tuple[int, str, bytes, int]:
    stored = list(directory.iterdir())
    if len(stored) != 1:
        return len(stored), "", b"", 0
    return (
        len(stored),
        stored[0].suffix,
        stored[0].read_bytes(),
        stored[0].stat().st_mode & 0o777,
    )


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Nursery",
        data={CONF_MODE: MODE_EMBEDDED, **_input(CONF_CAMERA_DSN=DSN)},
        unique_id=DSN,
    )


def _external_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Nursery",
        data={
            CONF_MODE: MODE_EXTERNAL,
            **_external_input(),
            CONF_BRIDGE_CAMERA_ID: "nursery",
            CONF_CAMERA_NAME: "Nursery",
        },
        unique_id="bridge-fixture",
    )


async def test_ordinary_flow_hides_development_mode(hass: HomeAssistant) -> None:
    """The ordinary selector defaults to embedded and hides development mode."""
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
    assert result["data_schema"]({})[CONF_MODE] == MODE_EMBEDDED


def _bridge_camera(name: str = "nursery") -> BridgeCamera:
    return BridgeCamera(
        camera_id=name,
        name=name.title(),
        online=True,
        stream_healthy=True,
        stream_codec="H.264",
        received_bytes=123,
        rtsp_url=f"rtsp://bridge.example.invalid:18554/{name}",
    )


def _external_input() -> dict[str, object]:
    return {
        CONF_BRIDGE_URL: BRIDGE_URL,
        CONF_BRIDGE_USERNAME: "api-user",
        CONF_BRIDGE_PASSWORD: "fixture-bridge-password",
        CONF_RTSP_OVERRIDE: "",
        CONF_VERIFY_TLS: True,
    }


async def test_external_mode_validates_and_creates(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.owlet_cam.config_flow.OwletHttpBridgeClient"
    ) as client_class:
        client_class.return_value.async_validate = AsyncMock(
            return_value=BridgeInfo(
                api_family="btoth525/owlet-to-rtsp",
                api_version=None,
                supports_snapshots=True,
                supports_sensors=True,
            )
        )
        client_class.return_value.async_get_cameras = AsyncMock(
            return_value=[_bridge_camera()]
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_EXTERNAL},
        )
        assert result["step_id"] == "external"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _external_input()
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Nursery"
    assert result["data"][CONF_MODE] == MODE_EXTERNAL
    assert result["data"][CONF_BRIDGE_CAMERA_ID] == "nursery"
    assert result["data"][CONF_BRIDGE_URL] == BRIDGE_URL


async def test_external_mode_selects_one_of_multiple_cameras(
    hass: HomeAssistant,
) -> None:
    with patch(
        "custom_components.owlet_cam.config_flow.OwletHttpBridgeClient"
    ) as client_class:
        client_class.return_value.async_validate = AsyncMock()
        client_class.return_value.async_get_cameras = AsyncMock(
            return_value=[_bridge_camera(), _bridge_camera("playroom")]
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_MODE: MODE_EXTERNAL},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _external_input()
        )
        assert result["step_id"] == "external_camera"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BRIDGE_CAMERA_ID: "playroom"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Playroom"
    assert result["data"][CONF_BRIDGE_CAMERA_ID] == "playroom"


async def test_external_flow_recovers_from_safe_errors(hass: HomeAssistant) -> None:
    errors = [
        (OwletBridgeAuthenticationError("safe"), "invalid_bridge_auth"),
        (OwletBridgeCompatibilityError("safe"), "unsupported_bridge"),
        (OwletBridgeConnectionError("safe"), "cannot_connect_bridge"),
    ]
    for exception, expected_error in errors:
        with patch(
            "custom_components.owlet_cam.config_flow.OwletHttpBridgeClient"
        ) as client_class:
            client_class.return_value.async_validate = AsyncMock(
                side_effect=[exception, None]
            )
            client_class.return_value.async_get_cameras = AsyncMock(
                return_value=[_bridge_camera()]
            )
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={CONF_MODE: MODE_EXTERNAL},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], _external_input()
            )
            assert result["errors"] == {"base": expected_error}
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], _external_input()
            )
            assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.config_entries.async_remove(result["result"].entry_id)


async def test_external_reauth_and_reconfigure_reload_once_each(
    hass: HomeAssistant,
) -> None:
    entry = _external_entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.owlet_cam.config_flow.OwletHttpBridgeClient"
        ) as client_class,
        patch.object(hass.config_entries, "async_schedule_reload") as reload_entry,
    ):
        client_class.return_value.async_validate = AsyncMock()
        client_class.return_value.async_get_cameras = AsyncMock(
            return_value=[_bridge_camera()]
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=dict(entry.data),
        )
        assert result["step_id"] == "reauth_bridge"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_BRIDGE_USERNAME: "new-user",
                CONF_BRIDGE_PASSWORD: "replacement-secret",
            },
        )
        assert result["reason"] == "reauth_successful"
        assert entry.data[CONF_BRIDGE_USERNAME] == "new-user"
        assert entry.data[CONF_BRIDGE_PASSWORD] == "replacement-secret"
        reload_entry.assert_called_once_with(entry.entry_id)

        reload_entry.reset_mock()
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        assert result["step_id"] == "reconfigure_bridge"
        updated = {**_external_input(), CONF_BRIDGE_URL: f"{BRIDGE_URL}/new"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], updated
        )

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_BRIDGE_URL] == f"{BRIDGE_URL}/new"
    reload_entry.assert_called_once_with(entry.entry_id)


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
    with (
        patch(
            "custom_components.owlet_cam.config_flow.OwletCloudClient"
        ) as client_class,
        patch(
            "custom_components.owlet_cam.config_flow."
            "OwletCamConfigFlow._async_store_runtime_package",
            new=AsyncMock(return_value=None),
        ) as store_package,
    ):
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "embedded_runtime"
        file_validator = next(iter(result["data_schema"].schema.values()))
        assert file_validator.config["accept"] == ".owletcam"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_RUNTIME_PACKAGE: FILE_ID}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Nursery"
    assert result["data"][CONF_CAMERA_DSN] == DSN
    assert result["data"][CONF_MODE] == MODE_EMBEDDED
    serialized = str(result["data"])
    for secret in ("fixture-firebase-token", "fixture-camera-uid", "fixture-auth-key"):
        assert secret not in serialized
    store_package.assert_awaited_once_with(FILE_ID)


async def test_duplicate_dsn_is_rejected(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.owlet_cam.config_flow.OwletCloudClient"
    ) as client_class:
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
        with (
            patch(
                "custom_components.owlet_cam.config_flow.OwletCloudClient"
            ) as client_class,
            patch(
                "custom_components.owlet_cam.config_flow."
                "OwletCamConfigFlow._async_store_runtime_package",
                new=AsyncMock(return_value=None),
            ),
        ):
            validate = AsyncMock(side_effect=[exception, _metadata()])
            client_class.return_value.async_validate_configured_camera = validate
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
            assert result["step_id"] == "embedded_runtime"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_RUNTIME_PACKAGE: FILE_ID}
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
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
        assert result["step_id"] == "reconfigure_runtime"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Baby room"
    schedule_reload.assert_called_once_with(entry.entry_id)
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_embedded_runtime_upload_error_recovers(
    hass: HomeAssistant,
) -> None:
    """A failed native upload stays in the setup flow and can be retried."""
    with (
        patch(
            "custom_components.owlet_cam.config_flow.OwletCloudClient"
        ) as client_class,
        patch(
            "custom_components.owlet_cam.config_flow._store_file_selector_upload",
            side_effect=[
                OwletUploadError("invalid", "safe"),
                OSError("safe"),
                None,
            ],
        ),
    ):
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_RUNTIME_PACKAGE: FILE_ID}
        )
        assert result["errors"] == {"base": "invalid_runtime_package"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_RUNTIME_PACKAGE: FILE_ID}
        )
        assert result["errors"] == {"base": "runtime_package_unavailable"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_RUNTIME_PACKAGE: FILE_ID}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_embedded_setup_consumes_native_file_upload(
    hass: HomeAssistant,
    hass_client,
) -> None:
    """The public Home Assistant file service feeds private embedded setup storage."""
    assert await async_setup_component(hass, "file_upload", {})
    client = await hass_client()
    form = FormData()
    form.add_field(
        "file",
        b"fixture-compact-runtime-package",
        filename="personal.owletcam",
        content_type="application/zip",
    )
    response = await client.post("/api/file_upload", data=form)
    assert response.status == 200
    file_id = (await response.json())["file_id"]

    with patch(
        "custom_components.owlet_cam.config_flow.OwletCloudClient"
    ) as client_class:
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_RUNTIME_PACKAGE: file_id}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_RUNTIME_PACKAGE not in result["data"]
    uploads = Path(
        hass.config.path("custom_components", "owlet_cam", "userfiles", "uploads")
    )
    count, suffix, content, mode = await hass.async_add_executor_job(
        _inspect_stored_upload, uploads
    )
    assert count == 1
    assert suffix == ".owletcam"
    assert content == b"fixture-compact-runtime-package"
    assert mode == 0o600


async def test_reconfigure_can_replace_runtime_package(
    hass: HomeAssistant,
) -> None:
    """Reconfigure accepts an optional native runtime package and reloads once."""
    entry = _entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.owlet_cam.config_flow.OwletCloudClient"
        ) as client_class,
        patch(
            "custom_components.owlet_cam.config_flow."
            "OwletCamConfigFlow._async_store_runtime_package",
            new=AsyncMock(return_value=None),
        ) as store_package,
        patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload,
    ):
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
            result["flow_id"], _input()
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_RUNTIME_PACKAGE: FILE_ID}
        )

    assert result["type"] is FlowResultType.ABORT
    store_package.assert_awaited_once_with(FILE_ID)
    schedule_reload.assert_called_once_with(entry.entry_id)


async def test_reconfigure_requires_confirmation_to_delete_runtime_files(
    hass: HomeAssistant,
) -> None:
    """Deletion is available in configuration and requires a separate confirmation."""
    entry = _entry()
    entry.add_to_hass(hass)
    delete_files = AsyncMock()
    entry.runtime_data = SimpleNamespace(
        runtime_manager=SimpleNamespace(async_delete_proprietary_files=delete_files)
    )
    with (
        patch(
            "custom_components.owlet_cam.config_flow.OwletCloudClient"
        ) as client_class,
        patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload,
    ):
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
            result["flow_id"], _input()
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DELETE_PROPRIETARY_FILES: True}
        )
        assert result["step_id"] == "confirm_delete_runtime"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CONFIRM_DELETE: False}
        )
        assert result["errors"] == {"base": "deletion_confirmation_required"}
        delete_files.assert_not_awaited()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CONFIRM_DELETE: True}
        )

    assert result["type"] is FlowResultType.ABORT
    delete_files.assert_awaited_once_with()
    schedule_reload.assert_called_once_with(entry.entry_id)


async def test_reconfigure_rejects_conflicting_runtime_actions(
    hass: HomeAssistant,
) -> None:
    """Replacement and deletion cannot be requested together."""
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.owlet_cam.config_flow.OwletCloudClient"
    ) as client_class:
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
            result["flow_id"], _input()
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_RUNTIME_PACKAGE: FILE_ID,
                CONF_DELETE_PROPRIETARY_FILES: True,
            },
        )

    assert result["step_id"] == "reconfigure_runtime"
    assert result["errors"] == {"base": "choose_one_runtime_action"}


async def test_runtime_deletion_reports_unavailable_and_safe_runtime_errors(
    hass: HomeAssistant,
) -> None:
    """Deletion failures remain redacted and retryable in the confirmation step."""
    entry = _entry()
    entry.add_to_hass(hass)
    delete_files = AsyncMock(
        side_effect=[OwletRuntimeError("safe_code", "safe message"), None]
    )
    with (
        patch(
            "custom_components.owlet_cam.config_flow.OwletCloudClient"
        ) as client_class,
        patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload,
    ):
        client_class.return_value.async_validate_configured_camera = AsyncMock(
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
            result["flow_id"], _input()
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DELETE_PROPRIETARY_FILES: True}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CONFIRM_DELETE: True}
        )
        assert result["errors"] == {"base": "runtime_package_unavailable"}

        entry.runtime_data = SimpleNamespace(
            runtime_manager=SimpleNamespace(async_delete_proprietary_files=delete_files)
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CONFIRM_DELETE: True}
        )
        assert result["errors"] == {"base": "runtime_package_unavailable"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CONFIRM_DELETE: True}
        )

    assert result["type"] is FlowResultType.ABORT
    assert delete_files.await_count == 2
    schedule_reload.assert_called_once_with(entry.entry_id)


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
        CONF_RETAIN_APPLICATION: False,
    }
    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["step_id"] == "general"
        assert result["data_schema"]({})[CONF_ENABLE_AUDIO] is True
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


async def test_external_options_reload_exactly_once(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Nursery",
        data={
            CONF_MODE: MODE_EXTERNAL,
            CONF_BRIDGE_URL: BRIDGE_URL,
            CONF_BRIDGE_CAMERA_ID: "nursery",
            CONF_CAMERA_NAME: "Nursery",
            CONF_VERIFY_TLS: True,
        },
        unique_id="bridge-fixture",
    )
    entry.add_to_hass(hass)
    general = {
        CONF_UPDATE_INTERVAL: 60,
        CONF_KEEP_WARM: False,
        CONF_IDLE_TIMEOUT: 60,
        CONF_STREAM_QUALITY: "high",
        CONF_ENABLE_AUDIO: False,
        CONF_DEBUG_LOGGING: False,
    }
    external = {
        CONF_BRIDGE_TIMEOUT: 15,
        CONF_RTSP_OVERRIDE: "rtsp://bridge.example.invalid:18554/nursery",
    }
    with patch.object(hass.config_entries, "async_schedule_reload") as reload_entry:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], general
        )
        assert result["step_id"] == "external"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], external
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**general, **external}
    reload_entry.assert_called_once_with(entry.entry_id)
