"""Embedded runtime preparation, capability probes, and lifecycle ownership."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import secrets
import shutil
import stat
import tempfile
import time
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..api.cloud import OwletCloudClient
from ..api.exceptions import (
    OwletAuthenticationError,
    OwletCameraNotFoundError,
    OwletCamError,
    OwletConnectionError,
    OwletRateLimitError,
)
from ..const import (
    DEFAULT_ENABLE_AUDIO,
    DEFAULT_EXPERIMENTAL_LOCAL_SENSORS,
    EXPECTED_HELPER_VERSION,
)
from .apk import (
    REQUIRED_LIBRARIES,
    SUPPORTED_ARCHIVE_SUFFIXES,
    ExtractedLibrary,
    ExtractedOwletApplication,
    OwletArchiveError,
    extract_owlet_application,
)
from .elf import ElfInspectionError, inspect_elf
from .media_probe import (
    MediaProbeError,
    MediaProbeResult,
    ffprobe_binary,
    ffprobe_failure_code,
    media_probe_error_code,
    parse_media_probe_output,
    safe_media_probe_observation,
)
from .process import OwletHelperProcessError, OwletHelperProcessRunner
from .protocol import (
    MAX_SNAPSHOT_CAPTURE,
    FrameProbeResult,
    LibraryProbeResult,
    OwletHelperProtocolError,
    OwletHelperReportedError,
    parse_frame_probe_output,
    parse_library_probe_output,
    parse_snapshot_capture_output,
)
from .stream import H264LoopbackServer
from .upload import StoredUpload, async_store_upload

_LOGGER = logging.getLogger(__name__)

RUNTIME_LAYOUT_VERSION: Final = 1
RUNTIME_MANIFEST: Final = "runtime-manifest.json"
RUNTIME_CURRENT: Final = "current"
SUPPORTED_MACHINE: Final = "aarch64"
_VALIDATION_MARKER: Final = "native-validation-consent.json"
_VALIDATION_MARKER_CONTENT: Final = (
    b'{"prior_explicit_runtime_validation":true,"schema_version":1}\n'
)
_FRAME_PROBE_TIMEOUT: Final = 75.0
_LIBRARY_PROBE_TIMEOUT: Final = 30.0
_SNAPSHOT_CAPTURE_TIMEOUT: Final = 30.0
_STREAM_PROBE_SECONDS: Final = 8.0
_STREAM_PROBE_TIMEOUT: Final = 20.0
_STREAM_PROBE_TERMINATE_TIMEOUT: Final = 2.0
_MAX_RECONNECT_BACKOFF: Final = 300.0
_STREAM_REPAIR_THRESHOLD: Final = 5
_PROCESS_SESSION: Final = secrets.token_hex(8)
_REQUIRED_RUNTIME_FILES: Final = frozenset(
    {
        "bin/frame_probe",
        "bin/probe_libraries",
        "bin/snapshot_capture",
        "runtime/bin/linker64",
        "runtime/lib64/libc.so",
        "runtime/lib64/libdl.so",
        "runtime/lib64/libm.so",
    }
)
_REQUIRED_SYMBOLS: Final = {
    "libTUTKGlobalAPIs.so": frozenset(
        {"TUTK_SDK_Set_License_Key", "TUTK_SDK_Set_Region"}
    ),
    "libIOTCAPIs.so": frozenset(
        {
            "IOTC_Initialize2",
            "IOTC_Set_LanSearchPort",
            "IOTC_Setup_Session_Alive_Timeout",
            "IOTC_Get_SessionID",
            "IOTC_Connect_ByUIDEx",
            "IOTC_Connect_Stop_BySID",
            "IOTC_Session_Check",
            "IOTC_Session_Close",
            "IOTC_DeInitialize",
        }
    ),
    "libAVAPIs.so": frozenset(
        {
            "avInitialize",
            "avClientStartEx",
            "avSendIOCtrl",
            "avRecvIOCtrl",
            "avRecvFrameData2",
            "avClientStop",
            "avDeInitialize",
        }
    ),
    "libRDTAPIs.so": frozenset({"RDT_Initialize", "RDT_DeInitialize"}),
    "libP2PTunnelAPIs.so": frozenset(
        {"P2PTunnelAgentInitialize", "P2PTunnelAgentDeInitialize"}
    ),
}


class OwletRuntimeError(RuntimeError):
    """A redacted embedded-runtime failure with an actionable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    """Verified metadata for an installed open-source helper runtime."""

    version: str
    architecture: str
    root: Path
    files: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class NativeLibraryReport:
    """Safe structural report for one user-supplied shared library."""

    name: str
    sha256: str
    architecture: str
    required_symbols_present: bool
    writable_executable_segment: bool


@dataclass(frozen=True, slots=True)
class PreparedRuntime:
    """Paths and non-secret reports accepted by every capability gate."""

    manifest: RuntimeManifest
    library_directory: Path
    libraries: tuple[NativeLibraryReport, ...]
    source_sha256: str
    package_name: str | None = None
    app_version: str | None = None
    stream_helper_available: bool = False


@dataclass(slots=True)
class RuntimeSnapshot:
    """Entity-safe in-memory runtime state."""

    status: str = "not_prepared"
    helper_version: str | None = None
    detected_apk_version: str | None = None
    libraries_compatible: bool | None = None
    last_error_code: str | None = None
    last_frame_probe_at: datetime | None = None
    last_frame_probe: FrameProbeResult | None = None
    last_snapshot_at: datetime | None = None
    last_snapshot_width: int | None = None
    last_snapshot_height: int | None = None
    last_stream_probe_at: datetime | None = None
    last_stream_probe: MediaProbeResult | None = None
    last_stream_probe_observation: dict[str, Any] | None = None
    stream_status: str = "idle"
    stream_healthy: bool = False
    stream_active: bool = False
    stream_frames: int = 0
    stream_bytes: int = 0
    stream_reconnect_count: int = 0
    stream_session_count: int = 0
    stream_stop_count: int = 0
    stream_last_started_at: datetime | None = None
    stream_last_frame_at: datetime | None = None
    stream_last_interruption_at: datetime | None = None
    stream_last_interruption_code: str | None = None
    stream_last_recovery_at: datetime | None = None
    stream_last_stopped_at: datetime | None = None
    audio_status: str = "disabled"
    audio_frames: int = 0
    audio_bytes: int = 0
    audio_codec_id: int | None = None
    audio_native_framing: str | None = None
    audio_last_frame_at: datetime | None = None
    audio_last_error_code: str | None = None
    temperature: int | None = None
    humidity: int | None = None
    sound_level: int | None = None
    illuminance: int | None = None
    wifi_signal: int | None = None
    last_sensor_update_at: datetime | None = None
    application_status: str = "not_uploaded"
    last_application_upload_at: datetime | None = None
    last_application_upload_size: int | None = None
    proprietary_files_present: bool = False


class OwletRuntimeManager:
    """Keep native execution isolated and owned by one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        root: Path,
        client: OwletCloudClient,
        camera_identifier: str,
        runner: OwletHelperProcessRunner | None = None,
        keep_warm: bool = False,
        idle_disconnect_timeout: float = 60.0,
        no_frame_timeout: float = 15.0,
        reconnect_backoff: float = 30.0,
        retain_application: bool = False,
        enable_audio: bool = DEFAULT_ENABLE_AUDIO,
        enable_local_sensors: bool = DEFAULT_EXPERIMENTAL_LOCAL_SENSORS,
    ) -> None:
        self._hass = hass
        self._root = root
        self._client = client
        self._camera_identifier = camera_identifier
        self._runner = runner or OwletHelperProcessRunner()
        self._lock = asyncio.Lock()
        self._stream_lock = asyncio.Lock()
        self._media_probe_lock = asyncio.Lock()
        self._listeners: set[Callable[[], None]] = set()
        self._prepared: PreparedRuntime | None = None
        self._sdk_key: bytearray | None = None
        self._shutdown = False
        self._keep_warm = keep_warm
        self._idle_disconnect_timeout = max(0.0, idle_disconnect_timeout)
        self._no_frame_timeout = max(1.0, no_frame_timeout)
        self._reconnect_backoff = max(0.0, reconnect_backoff)
        self._retain_application = retain_application
        self._audio_enabled = enable_audio
        self._local_sensors_enabled = enable_local_sensors
        self.snapshot = RuntimeSnapshot(
            audio_status="idle" if enable_audio else "disabled"
        )
        self._stream_requested = False
        self._stream_task: asyncio.Task[None] | None = None
        self._idle_disconnect_task: asyncio.Task[None] | None = None
        self._restore_task: asyncio.Task[None] | None = None
        self._media_probe_process: asyncio.subprocess.Process | None = None
        self._stream_server = H264LoopbackServer(
            on_first_client=self._async_stream_client_connected,
            on_last_client=self._async_stream_client_disconnected,
            audio_enabled=enable_audio,
        )

    @property
    def supported_architecture(self) -> bool:
        """Return the cached machine capability without filesystem I/O."""
        return _normalized_machine() == SUPPORTED_MACHINE

    @property
    def frame_probe_available(self) -> bool:
        """Return whether every earlier gate has passed."""
        return self._prepared is not None and self.snapshot.libraries_compatible is True

    @property
    def snapshot_available(self) -> bool:
        """Return whether the gated snapshot path is currently usable."""
        return self.frame_probe_available and self.snapshot.status != "error"

    @property
    def stream_available(self) -> bool:
        """Return the cached continuous-stream capability gate."""
        return self._stream_runtime_configured and self.snapshot.status == "ready"

    @property
    def _stream_runtime_configured(self) -> bool:
        """Return whether the validated native stream pieces are present."""
        return (
            self.frame_probe_available
            and self._prepared is not None
            and self._prepared.stream_helper_available
        )

    @property
    def stream_source_url(self) -> str | None:
        """Return the loopback-only URL without starting any I/O."""
        return self._stream_server.url

    @property
    def local_sensors_enabled(self) -> bool:
        """Return whether the optional embedded telemetry path is enabled."""
        return self._local_sensors_enabled

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a synchronous state listener."""
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    async def async_refresh_proprietary_state(self) -> None:
        """Cache whether user-supplied material exists without entity-property I/O."""
        present = await self._hass.async_add_executor_job(
            _proprietary_files_present, self._root
        )
        self.snapshot.proprietary_files_present = present
        if present:
            if self.snapshot.application_status == "not_uploaded":
                self.snapshot.application_status = "stored"
        elif self.snapshot.status == "not_prepared":
            self.snapshot.last_error_code = "missing_apk"
        self._notify_listeners()

    async def async_store_application_upload(
        self,
        content: AsyncIterable[bytes],
        *,
        suffix: str,
        content_length: int | None,
    ) -> StoredUpload:
        """Store one authenticated upload without buffering it in memory."""
        async with self._lock:
            self._raise_if_stopped()
            stored = await async_store_upload(
                self._hass,
                self._root / "uploads",
                content,
                suffix=suffix,
                content_length=content_length,
            )
            self.snapshot.application_status = "uploaded"
            self.snapshot.last_application_upload_at = datetime.now(UTC)
            self.snapshot.last_application_upload_size = stored.size
            self.snapshot.proprietary_files_present = True
            self.snapshot.last_error_code = None
            self._notify_listeners()
            return stored

    async def async_delete_proprietary_files(self) -> None:
        """Stop native work and delete every user-supplied proprietary file."""
        await self.async_stop_stream()
        async with self._lock:
            self._raise_if_stopped()
            self._replace_sdk_key(None)
            self._prepared = None
            await self._hass.async_add_executor_job(
                _delete_proprietary_files, self._root
            )
            self.snapshot.application_status = "deleted"
            self.snapshot.proprietary_files_present = False
            self.snapshot.libraries_compatible = None
            self.snapshot.helper_version = None
            self.snapshot.detected_apk_version = None
            self.snapshot.last_error_code = "missing_apk"
            self._set_status("not_prepared")

    async def async_run_authentication_test(self) -> None:
        """Refresh camera credentials and retain only a safe success state."""
        try:
            credentials = await self._client.async_get_camera_credentials(
                self._camera_identifier
            )
            del credentials
            self.snapshot.last_error_code = None
            self._notify_listeners()
        except OwletCamError as err:
            code = _cloud_error_code(err)
            self.snapshot.last_error_code = code
            self._notify_listeners()
            raise OwletRuntimeError(code, "Owlet authentication test failed") from err

    async def async_restart_stream(self) -> None:
        """Restart the producer when a local consumer is still connected."""
        had_consumers = self._stream_server.client_count > 0
        await self.async_stop_stream()
        if had_consumers or self._keep_warm:
            await self._async_stream_client_connected()

    async def async_prepare_and_probe_libraries(self) -> LibraryProbeResult:
        """Extract, inspect, verify, then dlopen without contacting a camera."""
        async with self._lock:
            self._raise_if_stopped()
            if self._stream_requested:
                raise OwletRuntimeError(
                    "stream_active", "Stop the live stream before probing the runtime"
                )
            self._set_status("preparing")
            try:
                prepared, sdk_key = await self._async_prepare_runtime_files()
                self._replace_sdk_key(sdk_key)
                command, environment = self._helper_invocation(
                    prepared, "probe_libraries"
                )
                result = await self._runner.async_run(
                    command,
                    timeout_seconds=_LIBRARY_PROBE_TIMEOUT,
                    cwd=prepared.manifest.root,
                    environment=environment,
                )
                if result.returncode != 0:
                    raise OwletRuntimeError(
                        "library_probe_failed", "Native libraries could not be loaded"
                    )
                probe = parse_library_probe_output(result.stdout)
                self._raise_if_stopped()
                self._prepared = prepared
                self.snapshot.helper_version = prepared.manifest.version
                self.snapshot.detected_apk_version = prepared.app_version
                self.snapshot.libraries_compatible = probe.compatible
                self.snapshot.proprietary_files_present = True
                self.snapshot.last_error_code = None
                if probe.compatible:
                    await self._hass.async_add_executor_job(
                        _write_validation_marker,
                        self._root / "state" / _VALIDATION_MARKER,
                    )
                    if not self._retain_application:
                        await self._hass.async_add_executor_job(
                            _delete_uploaded_archives, self._root / "uploads"
                        )
                        self.snapshot.application_status = "extracted_upload_deleted"
                self._set_status("ready")
                return probe
            except OwletRuntimeError as err:
                self._raise_if_stopped()
                self._record_error(err.code, libraries_failed=True)
                raise
            except OwletArchiveError as err:
                self._raise_if_stopped()
                self._record_error(err.code, libraries_failed=True)
                raise OwletRuntimeError(
                    err.code, "The user-supplied application is invalid"
                ) from err
            except ElfInspectionError as err:
                self._raise_if_stopped()
                self._record_error("library_incompatible", libraries_failed=True)
                raise OwletRuntimeError(
                    "library_incompatible", "A native library is incompatible"
                ) from err
            except (
                OwletHelperProcessError,
                OwletHelperProtocolError,
                OwletHelperReportedError,
            ) as err:
                self._raise_if_stopped()
                self._record_error("library_probe_failed", libraries_failed=True)
                raise OwletRuntimeError(
                    "library_probe_failed", "Native libraries could not be loaded"
                ) from err

    async def _async_prepare_runtime_files(
        self,
    ) -> tuple[PreparedRuntime, bytearray]:
        """Prepare local files, fetching only the exact missing release runtime."""
        try:
            prepared = cast(
                tuple[PreparedRuntime, bytearray],
                await self._hass.async_add_executor_job(self._prepare_sync),
            )
        except OwletRuntimeError as err:
            if err.code not in {
                "missing_runtime",
                "invalid_runtime_manifest",
                "runtime_checksum_mismatch",
            }:
                raise
            await self._async_install_release_runtime()
            return cast(
                tuple[PreparedRuntime, bytearray],
                await self._hass.async_add_executor_job(self._prepare_sync),
            )
        manifest = prepared[0].manifest
        if (
            manifest.version != EXPECTED_HELPER_VERSION
            and not manifest.version.endswith("-test")
        ):
            await self._async_install_release_runtime()
            return cast(
                tuple[PreparedRuntime, bytearray],
                await self._hass.async_add_executor_job(self._prepare_sync),
            )
        return prepared

    async def _async_install_release_runtime(self) -> None:
        """Install a checksum-verified release without exposing URLs or details."""
        from .downloader import (
            OwletRuntimeDownloadError,
            OwletRuntimeInstallError,
            async_ensure_release_runtime,
        )

        try:
            await async_ensure_release_runtime(
                self._hass,
                async_get_clientsession(self._hass),
                version=EXPECTED_HELPER_VERSION,
                architecture=SUPPORTED_MACHINE,
                runtime_parent=self._root / "runtime",
            )
        except OwletRuntimeInstallError as err:
            code = (
                "runtime_checksum_mismatch"
                if "checksum" in str(err).casefold()
                else "runtime_download_failed"
            )
            raise OwletRuntimeError(
                code, "The helper runtime release failed its integrity gates"
            ) from err
        except OwletRuntimeDownloadError as err:
            raise OwletRuntimeError(
                "runtime_download_failed",
                "The helper runtime release could not be installed",
            ) from err

    async def async_run_frame_probe(self) -> FrameProbeResult:
        """Fetch fresh credentials and receive a bounded set of real frames."""
        async with self._lock:
            self._raise_if_stopped()
            if self._prepared is None or self._sdk_key is None:
                raise OwletRuntimeError(
                    "runtime_not_ready", "Run the runtime probe first"
                )
            if self._stream_requested:
                raise OwletRuntimeError(
                    "stream_active", "Stop the live stream before running a probe"
                )
            self._set_status("frame_probe_running")
            try:
                credentials = await self._client.async_get_camera_credentials(
                    self._camera_identifier
                )
                payload = _secret_json_payload(
                    sdk_key=self._sdk_key,
                    uid=credentials.uid,
                    auth_key=credentials.auth_key,
                    av_password=credentials.av_password,
                )
                del credentials
                command, environment = self._helper_invocation(
                    self._prepared, "frame_probe"
                )
                result = await self._runner.async_run(
                    command,
                    stdin=payload,
                    timeout_seconds=_FRAME_PROBE_TIMEOUT,
                    cwd=self._prepared.manifest.root,
                    environment=environment,
                )
                probe = parse_frame_probe_output(result.stdout)
                if result.returncode != 0:
                    raise OwletRuntimeError(
                        "frame_probe_failed", "The camera frame probe failed"
                    )
                self._raise_if_stopped()
                self.snapshot.last_frame_probe = probe
                self.snapshot.last_frame_probe_at = datetime.now(UTC)
                self.snapshot.last_error_code = None
                self._set_status("ready")
                return probe
            except OwletHelperReportedError as err:
                self._raise_if_stopped()
                self._record_error(f"native_{err.stage}_{err.native_code}")
                raise OwletRuntimeError(
                    "frame_probe_failed", "The camera frame probe failed"
                ) from err
            except (OwletHelperProcessError, OwletHelperProtocolError) as err:
                self._raise_if_stopped()
                self._record_error("frame_probe_failed")
                raise OwletRuntimeError(
                    "frame_probe_failed", "The camera frame probe failed"
                ) from err
            except OwletCamError as err:
                self._raise_if_stopped()
                code = _cloud_error_code(err)
                self._record_error(code)
                raise OwletRuntimeError(
                    code, "Camera connection credentials could not be refreshed"
                ) from err

    async def async_capture_snapshot(
        self, decoder: Callable[[Path], Awaitable[bytes | None]]
    ) -> bytes:
        """Capture one decodable access unit and decode it before cleanup."""
        async with self._lock:
            self._raise_if_stopped()
            if self._prepared is None or self._sdk_key is None:
                raise OwletRuntimeError(
                    "runtime_not_ready", "Run the runtime probe first"
                )
            if self._stream_requested:
                raise OwletRuntimeError(
                    "stream_active", "Use the live stream for still images"
                )
            self._set_status("snapshot_capture_running")
            descriptor = -1
            capture_path: Path | None = None
            try:
                descriptor, capture_path = await self._hass.async_add_executor_job(
                    _create_snapshot_file, self._root / "tmp"
                )
                credentials = await self._client.async_get_camera_credentials(
                    self._camera_identifier
                )
                payload = _secret_json_payload(
                    sdk_key=self._sdk_key,
                    uid=credentials.uid,
                    auth_key=credentials.auth_key,
                    av_password=credentials.av_password,
                    output_fd=descriptor,
                )
                del credentials
                command, environment = self._helper_invocation(
                    self._prepared, "snapshot_capture"
                )
                result = await self._runner.async_run(
                    command,
                    stdin=payload,
                    timeout_seconds=_SNAPSHOT_CAPTURE_TIMEOUT,
                    cwd=self._prepared.manifest.root,
                    environment=environment,
                    pass_fds=(descriptor,),
                )
                await self._hass.async_add_executor_job(os.close, descriptor)
                descriptor = -1
                capture = parse_snapshot_capture_output(result.stdout)
                if result.returncode != 0:
                    raise OwletRuntimeError(
                        "snapshot_capture_failed", "The camera snapshot capture failed"
                    )
                await self._hass.async_add_executor_job(
                    _verify_snapshot_file, capture_path, capture.capture_bytes
                )
                image = await decoder(capture_path)
                if image is None:
                    raise OwletRuntimeError(
                        "snapshot_decode_failed",
                        "The camera snapshot could not be decoded",
                    )
                self._raise_if_stopped()
                self.snapshot.last_snapshot_at = datetime.now(UTC)
                self.snapshot.last_snapshot_width = capture.width
                self.snapshot.last_snapshot_height = capture.height
                self.snapshot.last_error_code = None
                self._set_status("ready")
                return image
            except OwletRuntimeError as err:
                self._raise_if_stopped()
                self._record_snapshot_error(err.code)
                raise
            except OwletHelperReportedError as err:
                self._raise_if_stopped()
                self._record_snapshot_error(f"native_{err.stage}_{err.native_code}")
                raise OwletRuntimeError(
                    "snapshot_capture_failed", "The camera snapshot capture failed"
                ) from err
            except (OwletHelperProcessError, OwletHelperProtocolError) as err:
                self._raise_if_stopped()
                self._record_snapshot_error("snapshot_capture_failed")
                raise OwletRuntimeError(
                    "snapshot_capture_failed", "The camera snapshot capture failed"
                ) from err
            except OwletCamError as err:
                self._raise_if_stopped()
                code = _cloud_error_code(err)
                self._record_snapshot_error(code)
                raise OwletRuntimeError(
                    code, "Camera snapshot credentials could not be refreshed"
                ) from err
            except TimeoutError as err:
                self._raise_if_stopped()
                self._record_snapshot_error("snapshot_decode_timeout")
                raise OwletRuntimeError(
                    "snapshot_decode_timeout", "The camera snapshot decode timed out"
                ) from err
            finally:
                if descriptor >= 0:
                    await self._hass.async_add_executor_job(os.close, descriptor)
                if capture_path is not None:
                    await self._hass.async_add_executor_job(capture_path.unlink, True)

    async def async_get_stream_source(self) -> str:
        """Start the loopback listener without opening a camera session."""
        self._raise_if_stopped()
        if not self.stream_available:
            raise OwletRuntimeError(
                "stream_runtime_missing", "The live stream helper is unavailable"
            )
        return await self._stream_server.async_start()

    async def async_run_stream_probe(self) -> MediaProbeResult:
        """Inspect bounded real media from inside Home Assistant Core."""
        async with self._media_probe_lock:
            self._raise_if_stopped()
            if not self.stream_available:
                raise OwletRuntimeError(
                    "stream_runtime_missing", "The live stream helper is unavailable"
                )
            had_consumers = self._stream_server.client_count > 0
            source = await self.async_get_stream_source()
            started = time.monotonic()
            frames_before = self.snapshot.stream_frames
            bytes_before = self.snapshot.stream_bytes
            self._set_status("stream_probe_running")
            process: asyncio.subprocess.Process | None = None
            failure_code = "stream_probe_failed"
            try:
                binary = ffprobe_binary(get_ffmpeg_manager(self._hass).binary)
                process = await asyncio.create_subprocess_exec(
                    binary,
                    "-v",
                    "error",
                    "-rw_timeout",
                    str(int(_STREAM_PROBE_TIMEOUT * 1_000_000)),
                    "-count_frames",
                    "-read_intervals",
                    f"%+{_STREAM_PROBE_SECONDS:g}",
                    "-show_entries",
                    (
                        "stream=codec_type,codec_name,profile,level,width,height,"
                        "avg_frame_rate,nb_read_frames,sample_rate,channels:"
                        "format=format_name"
                    ),
                    "-of",
                    "json",
                    source,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                self._media_probe_process = process
                try:
                    async with asyncio.timeout(_STREAM_PROBE_TIMEOUT):
                        stdout, _stderr = await process.communicate()
                except TimeoutError:
                    await self._async_stop_media_probe()
                    raise
                elapsed = max(time.monotonic() - started, 0.001)
                if process.returncode != 0:
                    failure_code = ffprobe_failure_code(_stderr)
                    raise MediaProbeError("FFprobe could not inspect the live stream")
                self.snapshot.last_stream_probe_observation = (
                    safe_media_probe_observation(stdout)
                )
                probe = parse_media_probe_output(
                    stdout,
                    observed_frames=self.snapshot.stream_frames - frames_before,
                    observed_bytes=self.snapshot.stream_bytes - bytes_before,
                    observed_seconds=elapsed,
                    expect_audio=self._audio_enabled,
                )
                self._raise_if_stopped()
                self.snapshot.last_stream_probe = probe
                self.snapshot.last_stream_probe_at = datetime.now(UTC)
                self.snapshot.last_error_code = None
                self._set_status("ready")
                return probe
            except MediaProbeError as err:
                self._raise_if_stopped()
                if failure_code == "stream_probe_failed":
                    failure_code = media_probe_error_code(err)
                self._record_error(failure_code)
                raise OwletRuntimeError(
                    failure_code, "The Core-local stream probe failed"
                ) from err
            except (OSError, TimeoutError, ValueError) as err:
                self._raise_if_stopped()
                self._record_error(failure_code)
                raise OwletRuntimeError(
                    failure_code, "The Core-local stream probe failed"
                ) from err
            finally:
                if self._media_probe_process is process:
                    self._media_probe_process = None
                if not had_consumers:
                    await asyncio.sleep(0)
                    if self._stream_server.client_count == 0:
                        await self.async_stop_stream()

    def async_schedule_previous_validation_restore(self) -> None:
        """Restore a runtime only after an earlier explicit probe consented."""
        if self._restore_task is not None or self._shutdown:
            return
        self._restore_task = self._hass.async_create_background_task(
            self._async_restore_previous_validation(),
            "Owlet Cam validated runtime restore",
        )

    async def _async_restore_previous_validation(self) -> None:
        try:
            marker = self._root / "state" / _VALIDATION_MARKER
            previously_validated = await self._hass.async_add_executor_job(
                _has_validation_marker, marker
            )
            if not previously_validated or self._shutdown:
                return
            await self._async_wait_until_home_assistant_started()
            await self.async_prepare_and_probe_libraries()
        except OwletRuntimeError:
            # The manager has already retained a redacted, entity-safe error.
            return
        finally:
            if self._restore_task is asyncio.current_task():
                self._restore_task = None

    async def _async_wait_until_home_assistant_started(self) -> None:
        """Avoid competing with Core startup for constrained Yellow resources."""
        if self._hass.state is CoreState.running:
            return
        started = asyncio.Event()

        @callback
        def async_mark_started(_event: Event[Any]) -> None:
            started.set()

        remove_listener = self._hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, async_mark_started
        )
        try:
            if self._hass.state is not CoreState.running:
                await started.wait()
        finally:
            if not started.is_set():
                remove_listener()

    async def async_stop_stream(self) -> None:
        """Stop the one native producer while leaving snapshots usable."""
        async with self._stream_lock:
            had_stream = (
                self._stream_task is not None
                or self.snapshot.stream_active
                or self._runner.running
            )
            self._stream_requested = False
            self._cancel_idle_disconnect()
            task = self._stream_task
            await self._runner.async_stop()
        if task is not None and task is not asyncio.current_task():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=7)
            except TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._stream_task = None
        self.snapshot.stream_active = False
        self.snapshot.stream_healthy = False
        self.snapshot.stream_status = "idle"
        if self._audio_enabled:
            self.snapshot.audio_status = "idle"
        if had_stream:
            self.snapshot.stream_stop_count += 1
            self.snapshot.stream_last_stopped_at = datetime.now(UTC)
        self._notify_listeners()

    async def _async_stream_client_connected(self) -> None:
        """Start one producer for the first loopback consumer."""
        async with self._stream_lock:
            self._raise_if_stopped()
            if not self._stream_runtime_configured:
                raise OwletRuntimeError(
                    "stream_runtime_missing", "The live stream helper is unavailable"
                )
            self._cancel_idle_disconnect()
            self._stream_requested = True
            if self._stream_task is None or self._stream_task.done():
                # The listener survives idle disconnects so Home Assistant keeps
                # one stable source URL. Cached media and its timestamp origin
                # must not survive into the next native camera session.
                self._stream_server.reset_media()
                self._stream_task = self._hass.async_create_background_task(
                    self._async_stream_loop(),
                    "Owlet Cam H.264 producer",
                )

    async def _async_stream_client_disconnected(self) -> None:
        """Schedule idle teardown after the final local consumer leaves."""
        if self._keep_warm or self._shutdown:
            return
        self._cancel_idle_disconnect()
        self._idle_disconnect_task = self._hass.async_create_background_task(
            self._async_idle_disconnect(),
            "Owlet Cam idle stream disconnect",
        )

    async def _async_idle_disconnect(self) -> None:
        try:
            await asyncio.sleep(self._idle_disconnect_timeout)
            if self._stream_server.client_count == 0:
                await self.async_stop_stream()
        except asyncio.CancelledError:
            raise
        finally:
            if self._idle_disconnect_task is asyncio.current_task():
                self._idle_disconnect_task = None

    async def _async_stream_loop(self) -> None:
        attempt = 0
        while self._stream_requested and not self._shutdown:
            self.snapshot.stream_status = "connecting" if attempt == 0 else "recovering"
            self.snapshot.stream_active = False
            self.snapshot.stream_healthy = False
            if self._audio_enabled:
                self.snapshot.audio_status = "starting"
            self._notify_listeners()
            try:
                prepared = self._prepared
                sdk_key = self._sdk_key
                if prepared is None or sdk_key is None:
                    raise OwletRuntimeError(
                        "runtime_not_ready", "Run the runtime probe first"
                    )
                credentials = await self._client.async_get_camera_credentials(
                    self._camera_identifier
                )
                audio_pipe: tuple[int, int] | None = (
                    os.pipe() if self._audio_enabled else None
                )
                sensor_pipe: tuple[int, int] | None = (
                    os.pipe() if self._local_sensors_enabled else None
                )
                payload = _secret_json_payload(
                    sdk_key=sdk_key,
                    uid=credentials.uid,
                    auth_key=credentials.auth_key,
                    av_password=credentials.av_password,
                    output_fd=audio_pipe[1] if audio_pipe is not None else 3,
                    audio_enabled=self._audio_enabled,
                    sensor_fd=sensor_pipe[1] if sensor_pipe is not None else 3,
                    sensors_enabled=self._local_sensors_enabled,
                )
                del credentials
                command, environment = self._helper_invocation(
                    prepared, "stream_capture"
                )
                self.snapshot.stream_session_count += 1
                self.snapshot.stream_last_started_at = datetime.now(UTC)
                self.snapshot.stream_active = True
                self._notify_listeners()
                await self._runner.async_stream(
                    command,
                    stdin=payload,
                    no_frame_timeout=self._no_frame_timeout,
                    on_frame=self._async_publish_stream_frame,
                    audio_pipe=audio_pipe,
                    on_audio_frame=(
                        self._async_publish_stream_audio
                        if audio_pipe is not None
                        else None
                    ),
                    on_audio_error=(
                        self._async_record_audio_error
                        if audio_pipe is not None
                        else None
                    ),
                    sensor_pipe=sensor_pipe,
                    on_sensor_values=(
                        self._async_publish_sensor_values
                        if sensor_pipe is not None
                        else None
                    ),
                    cwd=prepared.manifest.root,
                    environment=environment,
                )
                if not self._stream_requested:
                    break
                raise OwletRuntimeError(
                    "stream_helper_stopped", "The live stream helper stopped"
                )
            except asyncio.CancelledError:
                raise
            except OwletCamError as err:
                self._record_stream_interruption(_cloud_error_code(err))
            except OwletHelperProcessError as err:
                self._record_stream_interruption(err.code)
            except OwletRuntimeError as err:
                self._record_stream_interruption(err.code)
            finally:
                self.snapshot.stream_active = False
                self.snapshot.stream_healthy = False
                if self._audio_enabled and self.snapshot.audio_status == "streaming":
                    self.snapshot.audio_status = "idle"
                self._notify_listeners()
            if not self._stream_requested or self._shutdown:
                break
            self.snapshot.stream_reconnect_count += 1
            attempt += 1
            if attempt >= _STREAM_REPAIR_THRESHOLD:
                self.snapshot.last_error_code = "stream_recovery_failed"
                _LOGGER.error(
                    "Owlet Cam stream recovery repeatedly failed; review redacted "
                    "diagnostics"
                )
                self._notify_listeners()
            delay = min(
                self._reconnect_backoff * (2 ** min(attempt - 1, 8)),
                _MAX_RECONNECT_BACKOFF,
            )
            if delay:
                await asyncio.sleep(delay)
        self.snapshot.stream_status = "idle"
        self.snapshot.stream_active = False
        self.snapshot.stream_healthy = False
        self._notify_listeners()

    async def _async_publish_stream_frame(self, frame: bytes) -> None:
        was_healthy = self.snapshot.stream_healthy
        await self._stream_server.async_publish(frame)
        now = datetime.now(UTC)
        self.snapshot.stream_frames += 1
        self.snapshot.stream_bytes += len(frame)
        self.snapshot.stream_last_frame_at = now
        self.snapshot.stream_healthy = self._stream_server.healthy
        if self.snapshot.stream_healthy:
            self.snapshot.stream_status = "streaming"
            self.snapshot.last_error_code = None
            interrupted_at = self.snapshot.stream_last_interruption_at
            recovered_at = self.snapshot.stream_last_recovery_at
            if interrupted_at is not None and (
                recovered_at is None or recovered_at < interrupted_at
            ):
                self.snapshot.stream_last_recovery_at = now
                _LOGGER.info("Owlet Cam stream recovered after a safe interruption")
        if self.snapshot.stream_healthy != was_healthy:
            self._notify_listeners()

    async def _async_publish_stream_audio(self, codec_id: int, frame: bytes) -> None:
        """Mux one optional audio frame while keeping video independent."""
        # Codec identifiers are public protocol metadata, not credentials. Keep
        # the observed value even when unsupported so redacted diagnostics can
        # distinguish camera formats without requiring native debug logging.
        self.snapshot.audio_codec_id = codec_id
        if len(frame) >= 2 and frame[0] == 0xFF and frame[1] & 0xF6 == 0xF0:
            self.snapshot.audio_native_framing = "adts"
        elif len(frame) >= 2 and frame[0] == 0x56 and frame[1] & 0xE0 == 0xE0:
            self.snapshot.audio_native_framing = "loas"
        else:
            self.snapshot.audio_native_framing = "bare"
        published = await self._stream_server.async_publish_audio(
            frame, codec_id=codec_id
        )
        if not published:
            if codec_id not in (0x86, 0x87, 0x88):
                await self._async_record_audio_error("audio_codec_unsupported")
            return
        self.snapshot.audio_frames += 1
        self.snapshot.audio_bytes += len(frame)
        self.snapshot.audio_last_frame_at = datetime.now(UTC)
        self.snapshot.audio_last_error_code = None
        if self.snapshot.audio_status != "streaming":
            self.snapshot.audio_status = "streaming"
            self._notify_listeners()

    async def _async_record_audio_error(self, code: str) -> None:
        """Record an audio-only failure without interrupting H.264 video."""
        if not self._audio_enabled or self._shutdown:
            return
        changed = (
            self.snapshot.audio_status != "unavailable"
            or self.snapshot.audio_last_error_code != code
        )
        self.snapshot.audio_status = "unavailable"
        self.snapshot.audio_last_error_code = code
        if changed:
            _LOGGER.warning(
                "Owlet Cam audio became unavailable; video continues (code: %s)",
                code,
            )
            self._notify_listeners()

    async def _async_publish_sensor_values(self, values: dict[str, int]) -> None:
        """Cache validated local telemetry received from the isolated helper."""
        accepted = False
        ranges = {
            "temperature": (-20, 60),
            "humidity": (0, 100),
            "sound_level": (0, 200),
            "illuminance": (0, 200_000),
            "wifi_signal": (-150, 0),
        }
        for key, (minimum, maximum) in ranges.items():
            value = values.get(key)
            if (
                value is None
                or isinstance(value, bool)
                or not minimum <= value <= maximum
            ):
                continue
            setattr(self.snapshot, key, value)
            accepted = True
        if accepted:
            self.snapshot.last_sensor_update_at = datetime.now(UTC)
            self._notify_listeners()

    def _record_stream_interruption(self, code: str) -> None:
        """Cache and log one redacted recovery reason when viewing should continue."""
        if not self._stream_requested or self._shutdown:
            return
        now = datetime.now(UTC)
        self.snapshot.last_error_code = (
            "stream_recovery_failed"
            if self.snapshot.stream_reconnect_count >= _STREAM_REPAIR_THRESHOLD
            else code
        )
        self.snapshot.stream_last_interruption_at = now
        self.snapshot.stream_last_interruption_code = code
        _LOGGER.warning(
            "Owlet Cam stream interrupted; bounded recovery scheduled (code: %s)",
            code,
        )

    def _cancel_idle_disconnect(self) -> None:
        task = self._idle_disconnect_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self._idle_disconnect_task = None

    async def _async_stop_media_probe(self) -> None:
        """Terminate one bounded FFprobe process owned by this entry."""
        process = self._media_probe_process
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            async with asyncio.timeout(_STREAM_PROBE_TERMINATE_TIMEOUT):
                await process.wait()
        except TimeoutError:
            process.kill()
            await process.wait()

    async def async_shutdown(self) -> None:
        """Stop children, scrub SDK material, and release runtime state."""
        self._shutdown = True
        await self._async_stop_media_probe()
        await self.async_stop_stream()
        restore_task = self._restore_task
        if restore_task is not None and restore_task is not asyncio.current_task():
            restore_task.cancel()
            await asyncio.gather(restore_task, return_exceptions=True)
        await self._stream_server.async_stop()
        self._replace_sdk_key(None)
        self._prepared = None
        self.snapshot.libraries_compatible = None
        self._set_status("stopped")

    def _raise_if_stopped(self) -> None:
        if self._shutdown:
            raise asyncio.CancelledError

    def diagnostics(self) -> dict[str, Any]:
        """Return safe cached facts without filesystem or network I/O."""
        probe = self.snapshot.last_frame_probe
        process_diagnostics = self._runner.diagnostics()
        if not isinstance(process_diagnostics, dict):
            process_diagnostics = {
                "active": None,
                "started_count": None,
                "reaped_count": None,
                "all_reaped": None,
                "forced_kill_count": None,
                "last_exit_reason": None,
            }
        return {
            "status": self.snapshot.status,
            "helper_version": self.snapshot.helper_version,
            "detected_apk_version": self.snapshot.detected_apk_version,
            "detected_apk_package": (
                self._prepared.package_name if self._prepared is not None else None
            ),
            "detected_abi": ("arm64-v8a" if self._prepared is not None else None),
            "sdk_key_found": self._prepared is not None and self._sdk_key is not None,
            "native_libraries_compatible": self.snapshot.libraries_compatible,
            "last_safe_error_code": self.snapshot.last_error_code,
            "application": {
                "status": self.snapshot.application_status,
                "last_upload_at": _optional_isoformat(
                    self.snapshot.last_application_upload_at
                ),
                "last_upload_size": self.snapshot.last_application_upload_size,
                "proprietary_files_present": self.snapshot.proprietary_files_present,
                "retain_uploaded_archive": self._retain_application,
            },
            "last_frame_probe_at": (
                self.snapshot.last_frame_probe_at.isoformat()
                if self.snapshot.last_frame_probe_at is not None
                else None
            ),
            "last_frame_probe": asdict(probe) if probe is not None else None,
            "last_snapshot_at": (
                self.snapshot.last_snapshot_at.isoformat()
                if self.snapshot.last_snapshot_at is not None
                else None
            ),
            "last_snapshot_resolution": (
                f"{self.snapshot.last_snapshot_width}x{self.snapshot.last_snapshot_height}"
                if self.snapshot.last_snapshot_width is not None
                and self.snapshot.last_snapshot_height is not None
                else None
            ),
            "last_stream_probe_at": (
                self.snapshot.last_stream_probe_at.isoformat()
                if self.snapshot.last_stream_probe_at is not None
                else None
            ),
            "last_stream_probe": (
                asdict(self.snapshot.last_stream_probe)
                if self.snapshot.last_stream_probe is not None
                else None
            ),
            "last_stream_probe_observation": (
                self.snapshot.last_stream_probe_observation
            ),
            "stream": {
                "status": self.snapshot.stream_status,
                "active": self.snapshot.stream_active,
                "healthy": self.snapshot.stream_healthy,
                "frames": self.snapshot.stream_frames,
                "bytes": self.snapshot.stream_bytes,
                "reconnect_count": self.snapshot.stream_reconnect_count,
                "session_count": self.snapshot.stream_session_count,
                "stop_count": self.snapshot.stream_stop_count,
                "last_started_at": _optional_isoformat(
                    self.snapshot.stream_last_started_at
                ),
                "last_frame_at": _optional_isoformat(
                    self.snapshot.stream_last_frame_at
                ),
                "last_interruption_at": _optional_isoformat(
                    self.snapshot.stream_last_interruption_at
                ),
                "last_interruption_code": (self.snapshot.stream_last_interruption_code),
                "last_recovery_at": _optional_isoformat(
                    self.snapshot.stream_last_recovery_at
                ),
                "last_stopped_at": _optional_isoformat(
                    self.snapshot.stream_last_stopped_at
                ),
                "consumers": self._stream_server.client_count,
                "binding": "127.0.0.1" if self._stream_server.url else None,
                "audio": {
                    "enabled": self._audio_enabled,
                    "status": self.snapshot.audio_status,
                    "codec_id": (
                        f"0x{self.snapshot.audio_codec_id:04x}"
                        if self.snapshot.audio_codec_id is not None
                        else None
                    ),
                    "codec": (
                        "aac_raw"
                        if self.snapshot.audio_codec_id == 0x86
                        else "aac_adts"
                        if self.snapshot.audio_codec_id == 0x87
                        else "aac_kalay"
                        if self.snapshot.audio_codec_id == 0x88
                        else None
                    ),
                    "native_framing": self.snapshot.audio_native_framing,
                    "sample_rate": (
                        8000
                        if self.snapshot.audio_codec_id in (0x86, 0x87, 0x88)
                        else None
                    ),
                    "channels": (
                        1
                        if self.snapshot.audio_codec_id in (0x86, 0x87, 0x88)
                        else None
                    ),
                    "frames": self.snapshot.audio_frames,
                    "bytes": self.snapshot.audio_bytes,
                    "last_frame_at": _optional_isoformat(
                        self.snapshot.audio_last_frame_at
                    ),
                    "last_error_code": self.snapshot.audio_last_error_code,
                },
                "local_sensors": {
                    "enabled": self._local_sensors_enabled,
                    "temperature": self.snapshot.temperature,
                    "humidity": self.snapshot.humidity,
                    "sound_level": self.snapshot.sound_level,
                    "illuminance": self.snapshot.illuminance,
                    "wifi_signal": self.snapshot.wifi_signal,
                    "last_update_at": _optional_isoformat(
                        self.snapshot.last_sensor_update_at
                    ),
                },
            },
            "helper_process": process_diagnostics,
            "libraries": (
                [asdict(report) for report in self._prepared.libraries]
                if self._prepared is not None
                else []
            ),
        }

    def _prepare_sync(self) -> tuple[PreparedRuntime, bytearray]:
        if _normalized_machine() != SUPPORTED_MACHINE:
            raise OwletRuntimeError(
                "unsupported_architecture", "Embedded mode requires AArch64"
            )
        _prepare_directories(self._root)
        runtime_manifest = _verify_runtime(self._root / "runtime" / RUNTIME_CURRENT)
        try:
            archive = _select_archive(self._root / "uploads")
        except OwletRuntimeError as err:
            if err.code != "missing_apk":
                raise
            extracted = _load_persisted_application(self._root / "extracted")
            reports = _inspect_libraries(extracted)
            if extracted.sdk_key is None:
                raise OwletRuntimeError(
                    "missing_sdk_key", "Stored application SDK key is missing"
                ) from err
            return (
                PreparedRuntime(
                    manifest=runtime_manifest,
                    library_directory=(
                        next(iter(extracted.libraries.values())).path.parent
                    ),
                    libraries=reports,
                    source_sha256=extracted.source_sha256,
                    package_name=extracted.package_name,
                    app_version=extracted.app_version,
                    stream_helper_available=(
                        "bin/stream_capture" in runtime_manifest.files
                    ),
                ),
                bytearray(extracted.sdk_key),
            )
        archive.chmod(0o600)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f"extract-{_PROCESS_SESSION}-", dir=self._root / "tmp"
            )
        )
        try:
            extracted = extract_owlet_application(archive, temporary)
            reports = _inspect_libraries(extracted)
            if extracted.sdk_key is None:
                raise OwletRuntimeError(
                    "missing_sdk_key", "The application does not contain an SDK key"
                )
            final_root = self._root / "extracted" / extracted.source_sha256
            final_library_directory = final_root / extracted.abi
            if final_root.exists():
                _verify_extraction_root(final_root, self._root / "extracted")
                _verify_persisted_libraries(final_library_directory, extracted)
            else:
                os.replace(temporary, final_root)
            _persist_sdk_key(final_root / ".sdk-key", extracted.sdk_key)
            _persist_extraction_metadata(final_root / "application.json", extracted)
            for path in final_library_directory.iterdir():
                path.chmod(0o500)
            return (
                PreparedRuntime(
                    manifest=runtime_manifest,
                    library_directory=final_library_directory,
                    libraries=reports,
                    source_sha256=extracted.source_sha256,
                    package_name=extracted.package_name,
                    app_version=extracted.app_version,
                    stream_helper_available=(
                        "bin/stream_capture" in runtime_manifest.files
                    ),
                ),
                bytearray(extracted.sdk_key),
            )
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _helper_invocation(
        prepared: PreparedRuntime, helper_name: str
    ) -> tuple[tuple[str, ...], dict[str, str]]:
        root = prepared.manifest.root
        linker = root / "runtime/bin/linker64"
        library_path = f"{root / 'runtime/lib64'}:{prepared.library_directory}"
        return (
            (str(linker), str(root / "bin" / helper_name)),
            {"LD_LIBRARY_PATH": library_path},
        )

    def _replace_sdk_key(self, value: bytearray | None) -> None:
        if self._sdk_key is not None:
            self._sdk_key[:] = b"\0" * len(self._sdk_key)
        self._sdk_key = value

    def _record_error(self, code: str, *, libraries_failed: bool = False) -> None:
        self.snapshot.last_error_code = code
        if libraries_failed:
            self.snapshot.libraries_compatible = False
        self._set_status("error")

    def _record_snapshot_error(self, code: str) -> None:
        """Record a request failure while leaving the validated path retryable."""
        self.snapshot.last_error_code = code
        self._set_status("ready")

    def _set_status(self, status: str) -> None:
        self.snapshot.status = status
        self._notify_listeners()

    def _notify_listeners(self) -> None:
        for listener in tuple(self._listeners):
            listener()


def _normalized_machine() -> str:
    machine = platform.machine().strip().lower()
    return "aarch64" if machine in {"aarch64", "arm64"} else machine


def _cloud_error_code(error: OwletCamError) -> str:
    if isinstance(error, OwletAuthenticationError):
        return "reauthentication_required"
    if isinstance(error, OwletRateLimitError):
        return "cloud_rate_limited"
    if isinstance(error, OwletCameraNotFoundError):
        return "camera_unavailable"
    if isinstance(error, OwletConnectionError):
        return "cloud_connection_failed"
    return "cloud_request_failed"


def _optional_isoformat(value: datetime | None) -> str | None:
    """Serialize one cached timestamp without adding identifying data."""
    return value.isoformat() if value is not None else None


def _prepare_directories(root: Path) -> None:
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise OwletRuntimeError(
            "invalid_runtime_storage", "Runtime storage path is unsafe"
        )
    root.chmod(0o700)
    for name in ("uploads", "extracted", "runtime", "logs", "state", "tmp"):
        path = root / name
        path.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise OwletRuntimeError(
                "invalid_runtime_storage", "Runtime storage path is unsafe"
            )
        path.chmod(0o700)
    _remove_stale_extractions(root / "tmp")


def _persist_sdk_key(path: Path, sdk_key: bytes | None) -> None:
    """Atomically retain the user-supplied key for archive-free restarts."""
    if sdk_key is None:
        raise OwletRuntimeError("missing_sdk_key", "Application SDK key is missing")
    descriptor, raw_path = tempfile.mkstemp(prefix=".sdk-key-", dir=path.parent)
    temporary = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(sdk_key)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("SDK key write did not make progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        path.chmod(0o600)
    except OSError as err:
        raise OwletRuntimeError(
            "runtime_state_write_failed", "Application runtime state could not be saved"
        ) from err
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _persist_extraction_metadata(
    path: Path, extracted: ExtractedOwletApplication
) -> None:
    """Persist only non-secret application metadata beside private libraries."""
    document = {
        "schema_version": 1,
        "source_sha256": extracted.source_sha256,
        "abi": extracted.abi,
        "package_name": extracted.package_name,
        "app_version": extracted.app_version,
    }
    _atomic_private_write(
        path, json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    )


def _atomic_private_write(path: Path, content: bytes) -> None:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(content)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("Private metadata write did not make progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        path.chmod(0o600)
    except OSError as err:
        raise OwletRuntimeError(
            "runtime_state_write_failed", "Application runtime state could not be saved"
        ) from err
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _load_persisted_application(root: Path) -> ExtractedOwletApplication:
    """Load only private, structurally verified files previously extracted by us."""
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and len(path.name) == 64
    ]
    if not candidates:
        raise OwletRuntimeError("missing_apk", "Upload an Owlet application package")
    selected = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    library_directory = selected / "arm64-v8a"
    sdk_path = selected / ".sdk-key"
    if library_directory.is_symlink() or not library_directory.is_dir():
        raise OwletRuntimeError(
            "missing_arm64_split", "Stored ARM64 application libraries are missing"
        )
    _verify_private_secret_file(sdk_path, selected)
    sdk_key = sdk_path.read_bytes()
    if not 32 <= len(sdk_key) <= 512 or not sdk_key.isascii():
        raise OwletRuntimeError(
            "missing_sdk_key", "Stored application SDK key is invalid"
        )
    libraries: dict[str, ExtractedLibrary] = {}
    for name in sorted(REQUIRED_LIBRARIES):
        path = library_directory / name
        try:
            _verify_regular_file(path, library_directory)
            metadata = path.stat()
        except (OSError, OwletRuntimeError) as err:
            raise OwletRuntimeError(
                "missing_library", "A stored native library is missing"
            ) from err
        libraries[name] = ExtractedLibrary(
            name=name,
            path=path,
            sha256=_sha256(path),
            size=metadata.st_size,
        )
    package_name, app_version = _load_extraction_metadata(
        selected / "application.json", selected.name
    )
    return ExtractedOwletApplication(
        source_sha256=selected.name,
        abi="arm64-v8a",
        libraries=libraries,
        package_name=package_name,
        app_version=app_version,
        sdk_key=sdk_key,
    )


def _load_extraction_metadata(
    path: Path, source_sha256: str
) -> tuple[str | None, str | None]:
    try:
        _verify_private_secret_file(path, path.parent)
        document: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, OwletRuntimeError):
        return None, None
    if not isinstance(document, dict) or document.get("source_sha256") != source_sha256:
        return None, None
    package = document.get("package_name")
    version = document.get("app_version")
    return (
        package if isinstance(package, str) else None,
        version if isinstance(version, str) else None,
    )


def _verify_private_secret_file(path: Path, root: Path) -> None:
    _verify_regular_file(path, root)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise OwletRuntimeError(
            "invalid_extracted_files", "Stored application files are not private"
        )


def _verify_extraction_root(path: Path, root: Path) -> None:
    try:
        metadata = path.lstat()
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as err:
        raise OwletRuntimeError(
            "invalid_extracted_files", "Extracted application path is unsafe"
        ) from err
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise OwletRuntimeError(
            "invalid_extracted_files", "Extracted application path is unsafe"
        )


def _delete_uploaded_archives(directory: Path) -> None:
    """Delete only supported regular application archives from uploads."""
    if not directory.exists() or directory.is_symlink():
        return
    for path in directory.iterdir():
        if (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in SUPPORTED_ARCHIVE_SUFFIXES
        ):
            path.unlink()


def _delete_proprietary_files(root: Path) -> None:
    """Remove only integration-owned proprietary directories and state."""
    _prepare_directories(root)
    _delete_uploaded_archives(root / "uploads")
    for name in ("extracted", "tmp"):
        directory = root / name
        if directory.is_symlink():
            directory.unlink()
        elif directory.is_dir():
            shutil.rmtree(directory)
        directory.mkdir(mode=0o700)
    (root / "state" / _VALIDATION_MARKER).unlink(missing_ok=True)


def _proprietary_files_present(root: Path) -> bool:
    _prepare_directories(root)
    uploads = any(
        path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in SUPPORTED_ARCHIVE_SUFFIXES
        for path in (root / "uploads").iterdir()
    )
    extracted = any(
        path.is_dir() and not path.is_symlink()
        for path in (root / "extracted").iterdir()
    )
    return uploads or extracted


def _has_validation_marker(path: Path) -> bool:
    """Return whether an exact private marker records prior explicit consent."""
    try:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_size != len(_VALIDATION_MARKER_CONTENT)
        ):
            return False
        return path.read_bytes() == _VALIDATION_MARKER_CONTENT
    except OSError:
        return False


def _write_validation_marker(path: Path) -> None:
    """Atomically persist only the fact of a successful explicit native gate."""
    temporary_path: Path | None = None
    descriptor = -1
    try:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.parent.chmod(0o700)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".native-validation-", dir=path.parent
        )
        temporary_path = Path(raw_path)
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(_VALIDATION_MARKER_CONTENT)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("Validation marker write did not make progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as err:
        raise OwletRuntimeError(
            "runtime_state_write_failed", "Runtime validation state could not be saved"
        ) from err
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _remove_stale_extractions(directory: Path) -> None:
    """Remove only extraction directories owned by a previous Core process."""
    current_prefix = f"extract-{_PROCESS_SESSION}-"
    for path in directory.iterdir():
        if not path.name.startswith("extract-") or path.name.startswith(current_prefix):
            continue
        if path.is_symlink() or not path.is_dir():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path)


def _select_archive(uploads: Path) -> Path:
    candidates = [
        path
        for path in uploads.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in SUPPORTED_ARCHIVE_SUFFIXES
    ]
    if not candidates:
        raise OwletRuntimeError(
            "missing_apk", "Place an Owlet application package in uploads"
        )
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _verify_runtime(root: Path) -> RuntimeManifest:
    if root.is_symlink() or not root.is_dir():
        raise OwletRuntimeError("missing_runtime", "Helper runtime is not installed")
    manifest_path = root / RUNTIME_MANIFEST
    try:
        manifest: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as err:
        raise OwletRuntimeError(
            "invalid_runtime_manifest", "Helper runtime manifest is invalid"
        ) from err
    if not isinstance(manifest, dict):
        raise OwletRuntimeError(
            "invalid_runtime_manifest", "Helper runtime manifest is invalid"
        )
    if manifest.get("schema_version") != RUNTIME_LAYOUT_VERSION:
        raise OwletRuntimeError(
            "invalid_runtime_manifest", "Helper runtime manifest is incompatible"
        )
    version = manifest.get("version")
    architecture = manifest.get("architecture")
    files = manifest.get("files")
    if (
        not isinstance(version, str)
        or not version
        or architecture != SUPPORTED_MACHINE
        or not isinstance(files, dict)
        or not _REQUIRED_RUNTIME_FILES.issubset(files)
    ):
        raise OwletRuntimeError(
            "invalid_runtime_manifest", "Helper runtime manifest is invalid"
        )
    for relative, expected_sha256 in files.items():
        member = PurePosixPath(relative) if isinstance(relative, str) else None
        if (
            member is None
            or member.is_absolute()
            or any(part in {"", ".", ".."} for part in member.parts)
            or "\\" in relative
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha256)
        ):
            raise OwletRuntimeError(
                "invalid_runtime_manifest", "Helper runtime manifest is invalid"
            )
        path = root.joinpath(*member.parts)
        _verify_regular_file(path, root)
        if _sha256(path) != expected_sha256.lower():
            raise OwletRuntimeError(
                "runtime_checksum_mismatch", "Helper runtime checksum failed"
            )
    return RuntimeManifest(
        version=version,
        architecture=architecture,
        root=root,
        files=frozenset(files),
    )


def _verify_regular_file(path: Path, root: Path) -> None:
    try:
        metadata = path.lstat()
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as err:
        raise OwletRuntimeError(
            "invalid_runtime_manifest", "Helper runtime contains an unsafe path"
        ) from err
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise OwletRuntimeError(
            "invalid_runtime_manifest", "Helper runtime contains an unsafe file"
        )


def _inspect_libraries(
    extracted: ExtractedOwletApplication,
) -> tuple[NativeLibraryReport, ...]:
    reports: list[NativeLibraryReport] = []
    for name in sorted(REQUIRED_LIBRARIES):
        library = extracted.libraries[name]
        report = inspect_elf(
            library.path, required_symbols=_REQUIRED_SYMBOLS.get(name, frozenset())
        )
        if (
            not report.required_symbols_present
            or report.has_writable_executable_segment
        ):
            raise ElfInspectionError("Native library failed its structural gate")
        reports.append(
            NativeLibraryReport(
                name=name,
                sha256=library.sha256,
                architecture=report.architecture,
                required_symbols_present=report.required_symbols_present,
                writable_executable_segment=report.has_writable_executable_segment,
            )
        )
    return tuple(reports)


def _verify_persisted_libraries(
    directory: Path, extracted: ExtractedOwletApplication
) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise OwletRuntimeError(
            "invalid_extracted_files", "Extracted native libraries are invalid"
        )
    for name, library in extracted.libraries.items():
        path = directory / name
        _verify_regular_file(path, directory)
        if _sha256(path) != library.sha256:
            raise OwletRuntimeError(
                "invalid_extracted_files", "Extracted native library checksum failed"
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _secret_json_payload(
    *,
    sdk_key: bytearray,
    uid: str,
    auth_key: str,
    av_password: str,
    output_fd: int | None = None,
    audio_enabled: bool | None = None,
    sensor_fd: int | None = None,
    sensors_enabled: bool | None = None,
) -> bytearray:
    # JSON encoding creates one short-lived in-memory string, never a file,
    # environment variable, command argument, diagnostic value, or log record.
    values = {
        "sdk_key": sdk_key.decode("ascii"),
        "uid": uid,
        "auth_key": auth_key,
        "av_password": av_password,
    }
    if output_fd is not None:
        values["output_fd"] = str(output_fd)
    if audio_enabled is not None:
        values["audio_enabled"] = "1" if audio_enabled else "0"
    if sensor_fd is not None:
        values["sensor_fd"] = str(sensor_fd)
    if sensors_enabled is not None:
        values["sensors_enabled"] = "1" if sensors_enabled else "0"
    payload = json.dumps(
        values,
        separators=(",", ":"),
    )
    return bytearray(payload.encode("utf-8") + b"\n")


def _create_snapshot_file(directory: Path) -> tuple[int, Path]:
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f"snapshot-{_PROCESS_SESSION}-", suffix=".h264", dir=directory
    )
    os.fchmod(descriptor, 0o600)
    return descriptor, Path(raw_path)


def _verify_snapshot_file(path: Path, expected_size: int) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or expected_size < 1
        or expected_size > MAX_SNAPSHOT_CAPTURE
        or metadata.st_size != expected_size
    ):
        raise OwletRuntimeError(
            "snapshot_capture_failed", "The camera snapshot capture failed"
        )
