"""Snapshot-only embedded camera platform for Owlet Cam."""

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
    """Set up one gated snapshot-only embedded camera."""
    manager = entry.runtime_data.runtime_manager
    if entry.data.get(CONF_MODE) != MODE_EMBEDDED or manager is None:
        return
    async_add_entities([OwletCamEmbeddedCamera(entry)])


class OwletCamEmbeddedCamera(OwletCamRuntimeEntity, Camera):
    """Expose on-demand JPEG snapshots without claiming stream support."""

    _attr_name = None
    _attr_supported_features = CameraEntityFeature(0)

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
    def use_stream_for_stills(self) -> bool:
        """Keep stream integration disabled for the snapshot-only milestone."""
        return False

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
