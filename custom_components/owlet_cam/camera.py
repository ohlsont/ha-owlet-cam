"""Embedded snapshot and gated live-stream camera platform for Owlet Cam."""

from __future__ import annotations

import asyncio
import shlex
import time
from contextlib import suppress
from pathlib import Path
from typing import Final, override

from haffmpeg.tools import IMAGE_JPEG, ImageFrame
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CAMERA_DSN, CONF_CAMERA_NAME, CONF_MODE, MODE_EMBEDDED
from .data import OwletCamConfigEntry
from .entity import OwletCamRuntimeEntity
from .runtime.manager import OwletRuntimeError

_SNAPSHOT_CACHE_SECONDS: Final = 5.0
_SNAPSHOT_DECODE_TIMEOUT: Final = 10.0
_MAX_JPEG_BYTES: Final = 16 * 1024 * 1024


async def async_setup_entry(
    _hass: object,
    entry: OwletCamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one gated embedded camera."""
    manager = entry.runtime_data.runtime_manager
    if entry.data.get(CONF_MODE) != MODE_EMBEDDED or manager is None:
        return
    async_add_entities([OwletCamEmbeddedCamera(entry)])


class OwletCamEmbeddedCamera(OwletCamRuntimeEntity, Camera):
    """Expose snapshots and a timestamped loopback media source after its gate."""

    _attr_name = None

    def __init__(self, entry: OwletCamConfigEntry) -> None:
        Camera.__init__(self)
        manager = entry.runtime_data.runtime_manager
        if manager is None:
            raise RuntimeError("Embedded runtime manager is unavailable")
        OwletCamRuntimeEntity.__init__(
            self,
            manager,
            camera_identifier=entry.data[CONF_CAMERA_DSN],
            camera_name=entry.data[CONF_CAMERA_NAME],
            key="camera",
        )
        self._snapshot_lock = asyncio.Lock()
        self._cached_image: bytes | None = None
        self._cached_at = 0.0
        self._active_snapshot_task: asyncio.Task[bytes | None] | None = None

    @property
    @override
    def available(self) -> bool:
        """Return cached runtime availability without performing I/O."""
        return self.runtime_manager.snapshot_available

    @property
    @override
    def supported_features(self) -> CameraEntityFeature:
        """Claim streaming only when the versioned helper includes it."""
        if self.runtime_manager.stream_available:
            return CameraEntityFeature.STREAM
        return CameraEntityFeature(0)

    @property
    @override
    def use_stream_for_stills(self) -> bool:
        """Reuse the continuous producer once the live path is gated."""
        return self.runtime_manager.stream_available

    @property
    @override
    def is_streaming(self) -> bool:
        """Return cached producer health without performing I/O."""
        return self.runtime_manager.snapshot.stream_healthy

    @override
    async def stream_source(self) -> str | None:
        """Return the integration-owned timestamped loopback media source."""
        try:
            return await self.runtime_manager.async_get_stream_source()
        except OwletRuntimeError:
            return None

    @override
    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Capture, decode, and briefly cache one JPEG on explicit demand."""
        del width, height
        cached = self._fresh_cached_image()
        if cached is not None:
            return cached
        async with self._snapshot_lock:
            cached = self._fresh_cached_image()
            if cached is not None:
                return cached
            task = asyncio.current_task()
            if task is not None:
                self._active_snapshot_task = task
            try:
                image = await self.runtime_manager.async_capture_snapshot(
                    self._async_decode_capture
                )
            except (OwletRuntimeError, TimeoutError):
                return None
            finally:
                if self._active_snapshot_task is task:
                    self._active_snapshot_task = None
            self._cached_image = image
            self._cached_at = time.monotonic()
            return image

    async def _async_decode_capture(self, capture_path: Path) -> bytes | None:
        """Decode one trusted private H.264 file with HA's FFmpeg binary."""
        manager = get_ffmpeg_manager(self.hass)
        decoder = ImageFrame(manager.binary)
        input_source = shlex.join(("-f", "h264", "-i", str(capture_path)))
        async with asyncio.timeout(_SNAPSHOT_DECODE_TIMEOUT):
            image = await decoder.get_image(
                input_source,
                output_format=IMAGE_JPEG,
                extra_cmd="-q:v 2",
                timeout=int(_SNAPSHOT_DECODE_TIMEOUT),
            )
        if (
            not isinstance(image, bytes)
            or not 4 <= len(image) <= _MAX_JPEG_BYTES
            or not image.startswith(b"\xff\xd8")
            or not image.endswith(b"\xff\xd9")
        ):
            return None
        return image

    def _fresh_cached_image(self) -> bytes | None:
        image = self._cached_image
        if (
            image is None
            or time.monotonic() - self._cached_at >= _SNAPSHOT_CACHE_SECONDS
        ):
            return None
        return image

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Cancel an in-flight capture/decode before entity removal."""
        task = self._active_snapshot_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._cached_image = None
        await super().async_will_remove_from_hass()
