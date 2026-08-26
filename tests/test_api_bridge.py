"""External Owlet-To-Rtsp bridge adapter tests."""

from base64 import b64encode

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.owlet_cam.api.bridge import (
    OwletHttpBridgeClient,
    normalize_bridge_url,
    normalize_rtsp_url,
)
from custom_components.owlet_cam.api.exceptions import (
    OwletBridgeAuthenticationError,
    OwletBridgeCompatibilityError,
    OwletBridgeConnectionError,
)

BASE_URL = "https://bridge.example.invalid:8088"
JPEG = b"\xff\xd8fixture-jpeg\xff\xd9"


def _client(hass: HomeAssistant, **kwargs: object) -> OwletHttpBridgeClient:
    return OwletHttpBridgeClient(
        async_get_clientsession(hass), base_url=BASE_URL, **kwargs
    )


def _mock_status(aioclient_mock: AiohttpClientMocker, *, status: int = 200) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/api/status",
        status=status,
        json={
            "have_login": True,
            "have_libs": True,
            "config_writable": True,
            "busy": False,
            "cameras": 1,
            "cameras_with_key": 1,
            "streams_live": 1,
            "rtsp_port": 18554,
            "http_port": 1985,
            "webrtc_port": 18555,
        },
    )


def _mock_cameras(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/api/cameras",
        json={
            "cameras": [
                {
                    "name": "nursery",
                    "camera_dsn": "must-be-ignored",
                    "uid": "must-be-ignored",
                    "authkey": "must-be-ignored",
                    "av_password": "********",
                    "have_key": True,
                    "busy": False,
                    "stream_up": True,
                    "codec": "H.264",
                    "recv": 123456,
                }
            ],
            "rtsp_port": 18554,
            "http_port": 1985,
            "webrtc_port": 18555,
        },
    )


async def test_validates_and_parses_current_bridge_contract(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    client = _client(
        hass,
        username="api-user",
        password_or_token="fixture-bridge-password",  # noqa: S106
    )
    _mock_status(aioclient_mock)
    _mock_cameras(aioclient_mock)

    info = await client.async_validate()
    cameras = await client.async_get_cameras()
    status = await client.async_get_status("nursery")

    assert info.api_family == "btoth525/owlet-to-rtsp"
    assert info.supports_snapshots
    assert len(cameras) == 1
    camera = cameras[0]
    assert camera.camera_id == "nursery"
    assert camera.online
    assert camera.stream_healthy
    assert camera.stream_codec == "H.264"
    assert camera.rtsp_url == "rtsp://bridge.example.invalid:18554/nursery"
    assert status.online
    assert status.stream_healthy
    authorization = aioclient_mock.mock_calls[0][3]["Authorization"]
    expected = b64encode(b"api-user:fixture-bridge-password").decode()
    assert authorization == f"Basic {expected}"
    assert "must-be-ignored" not in repr(cameras)


async def test_reads_metric_room_sensors_and_snapshot(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    client = _client(hass)
    _mock_cameras(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/api/vitals?units=metric",
        json={
            "units": "metric",
            "devices": [
                {
                    "dsn": "nursery",
                    "name": "nursery",
                    "kind": "cam",
                    "model": "Owlet Cam",
                    "sensors": {
                        "temperature": 21.4,
                        "humidity": 48,
                        "noise": 32.5,
                        "brightness": 7,
                        "wifi_rssi": -62,
                    },
                }
            ],
        },
    )
    aioclient_mock.get(f"{BASE_URL}/snapshot/nursery.jpg", content=JPEG)

    sensors = await client.async_get_sensors("nursery")
    snapshot = await client.async_get_snapshot("nursery")

    assert sensors.temperature == 21.4
    assert sensors.humidity == 48
    assert sensors.sound_level == 32.5
    assert sensors.illuminance == 7
    assert sensors.wifi_signal == -62
    assert snapshot == JPEG


async def test_missing_optional_endpoints_do_not_break_video(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    client = _client(hass)
    _mock_cameras(aioclient_mock)
    aioclient_mock.get(f"{BASE_URL}/api/vitals?units=metric", status=404)
    aioclient_mock.get(f"{BASE_URL}/snapshot/nursery.jpg", status=404)

    assert await client.async_get_stream_source("nursery") is not None
    assert (await client.async_get_sensors("nursery")).temperature is None
    assert await client.async_get_snapshot("nursery") is None


@pytest.mark.parametrize("status", [401, 403])
async def test_rejects_bridge_authentication(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
) -> None:
    client = _client(hass, password_or_token="fixture-token")  # noqa: S106
    _mock_status(aioclient_mock, status=status)

    with pytest.raises(OwletBridgeAuthenticationError):
        await client.async_validate()


async def test_rejects_malformed_and_failed_bridge_responses(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    client = _client(hass)
    aioclient_mock.get(f"{BASE_URL}/api/status", text="not-json")
    with pytest.raises(OwletBridgeCompatibilityError):
        await client.async_validate()

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE_URL}/api/status", status=500)
    with pytest.raises(OwletBridgeConnectionError):
        await client.async_validate()


@pytest.mark.parametrize(
    "value",
    [
        "bridge.example.invalid",
        "ftp://bridge.example.invalid",
        "https://user:secret@bridge.example.invalid",
        "https://bridge.example.invalid/?token=secret",
    ],
)
def test_rejects_unsafe_bridge_urls(value: str) -> None:
    with pytest.raises(ValueError, match="base URL is invalid"):
        normalize_bridge_url(value)


def test_normalizes_bridge_and_rtsp_urls() -> None:
    assert normalize_bridge_url(f" {BASE_URL}/ ") == BASE_URL
    assert (
        normalize_rtsp_url("rtsp://bridge.example.invalid:18554/nursery")
        == "rtsp://bridge.example.invalid:18554/nursery"
    )
    with pytest.raises(ValueError, match="RTSP source is invalid"):
        normalize_rtsp_url("http://bridge.example.invalid/video")
