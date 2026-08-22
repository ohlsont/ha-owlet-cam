"""Snapshot-only embedded camera tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.camera import CameraEntityFeature
from homeassistant.components.ffmpeg import DATA_FFMPEG
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.owlet_cam.camera import OwletCamEmbeddedCamera
from custom_components.owlet_cam.const import (
    CONF_CAMERA_DSN,
    CONF_CAMERA_NAME,
    CONF_MODE,
    DOMAIN,
    MODE_EMBEDDED,
)
from custom_components.owlet_cam.runtime.manager import (
    OwletRuntimeError,
    OwletRuntimeManager,
)

DSN = "OCD123456789"
JPEG = b"\xff\xd8fixture-jpeg\xff\xd9"


def _camera(
    hass: HomeAssistant, manager: MagicMock | None = None
) -> tuple[OwletCamEmbeddedCamera, MagicMock]:
    runtime = manager or MagicMock(spec=OwletRuntimeManager)
    runtime.snapshot_available = True
    runtime.stream_available = False
    runtime.snapshot = SimpleNamespace(stream_healthy=False)
    runtime.async_add_listener.return_value = lambda: None
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Nursery",
        data={
            CONF_MODE: MODE_EMBEDDED,
            CONF_CAMERA_DSN: DSN,
            CONF_CAMERA_NAME: "Nursery",
        },
        unique_id=DSN,
    )
    entry.runtime_data = SimpleNamespace(runtime_manager=runtime)
    entity = OwletCamEmbeddedCamera(entry)
    entity.hass = hass
    return entity, runtime


def test_snapshot_camera_claims_no_stream_feature(hass: HomeAssistant) -> None:
    camera, manager = _camera(hass)

    assert camera.supported_features == CameraEntityFeature(0)
    assert not camera.use_stream_for_stills
    assert camera.content_type == "image/jpeg"
    assert camera.available
    manager.async_capture_snapshot.assert_not_called()


async def test_camera_claims_stream_only_after_runtime_gate(
    hass: HomeAssistant,
) -> None:
    camera, manager = _camera(hass)
    manager.stream_available = True
    manager.snapshot.stream_healthy = True
    manager.async_get_stream_source = AsyncMock(
        return_value="http://127.0.0.1:12345/private.h264"
    )

    assert camera.supported_features == CameraEntityFeature.STREAM
    assert camera.use_stream_for_stills
    assert camera.is_streaming
    assert await camera.stream_source() == "http://127.0.0.1:12345/private.h264"

    manager.async_get_stream_source.side_effect = OwletRuntimeError(
        "stream_runtime_missing", "safe"
    )
    assert await camera.stream_source() is None


async def test_snapshot_camera_caches_and_coalesces_concurrent_requests(
    hass: HomeAssistant,
) -> None:
    camera, manager = _camera(hass)
    started = asyncio.Event()
    release = asyncio.Event()

    async def capture(_decoder: object) -> bytes:
        started.set()
        await release.wait()
        return JPEG

    manager.async_capture_snapshot = AsyncMock(side_effect=capture)
    first = asyncio.create_task(camera.async_camera_image())
    await started.wait()
    second = asyncio.create_task(camera.async_camera_image())
    release.set()

    assert await first == JPEG
    assert await second == JPEG
    assert await camera.async_camera_image() == JPEG
    manager.async_capture_snapshot.assert_awaited_once()


async def test_snapshot_cache_expires(hass: HomeAssistant) -> None:
    camera, manager = _camera(hass)
    manager.async_capture_snapshot = AsyncMock(side_effect=[JPEG, JPEG])

    with patch(
        "custom_components.owlet_cam.camera.time.monotonic",
        side_effect=[10.0, 12.0, 16.0, 16.0, 17.0],
    ):
        assert await camera.async_camera_image() == JPEG
        assert await camera.async_camera_image() == JPEG
        assert await camera.async_camera_image() == JPEG

    assert manager.async_capture_snapshot.await_count == 2


async def test_snapshot_camera_returns_none_on_runtime_failure(
    hass: HomeAssistant,
) -> None:
    camera, manager = _camera(hass)
    manager.async_capture_snapshot = AsyncMock(
        side_effect=OwletRuntimeError("snapshot_capture_failed", "safe")
    )

    assert await camera.async_camera_image() is None


async def test_snapshot_decoder_accepts_only_jpeg_and_uses_safe_arguments(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    camera, _manager = _camera(hass)
    hass.data[DATA_FFMPEG] = SimpleNamespace(binary="/usr/bin/ffmpeg")
    capture = tmp_path / "private-capture.h264"
    capture.write_bytes(b"fixture")
    with patch(
        "custom_components.owlet_cam.camera.ImageFrame.get_image",
        new=AsyncMock(return_value=JPEG),
    ) as get_image:
        assert await camera._async_decode_capture(capture) == JPEG

    call = get_image.await_args
    assert str(capture) in call.args[0]
    assert call.kwargs == {
        "output_format": "mjpeg",
        "extra_cmd": "-q:v 2",
        "timeout": 10,
    }
    serialized = str(call)
    for secret in ("fixture-uid", "fixture-auth-key", "fixture-sdk-key"):
        assert secret not in serialized

    with patch(
        "custom_components.owlet_cam.camera.ImageFrame.get_image",
        new=AsyncMock(return_value=b"not-jpeg"),
    ):
        assert await camera._async_decode_capture(capture) is None


async def test_snapshot_decode_timeout_returns_none(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    camera, manager = _camera(hass)
    hass.data[DATA_FFMPEG] = SimpleNamespace(binary="/usr/bin/ffmpeg")
    capture = tmp_path / "private-capture.h264"
    capture.write_bytes(b"fixture")

    async def decode_with_manager(decoder: object) -> bytes | None:
        return await decoder(capture)  # type: ignore[operator]

    manager.async_capture_snapshot = AsyncMock(side_effect=decode_with_manager)

    async def never_finishes(*_args: object, **_kwargs: object) -> bytes:
        await asyncio.Future()
        return JPEG

    with (
        patch("custom_components.owlet_cam.camera._SNAPSHOT_DECODE_TIMEOUT", 0.01),
        patch(
            "custom_components.owlet_cam.camera.ImageFrame.get_image",
            new=AsyncMock(side_effect=never_finishes),
        ),
    ):
        assert await camera.async_camera_image() is None


async def test_entity_removal_cancels_in_flight_snapshot(
    hass: HomeAssistant,
) -> None:
    camera, manager = _camera(hass)
    started = asyncio.Event()

    async def capture(_decoder: object) -> bytes:
        started.set()
        await asyncio.Future()
        return JPEG

    manager.async_capture_snapshot = AsyncMock(side_effect=capture)
    task = asyncio.create_task(camera.async_camera_image())
    await started.wait()

    await camera.async_will_remove_from_hass()

    assert task.cancelled()
    assert camera._cached_image is None
