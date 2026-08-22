"""Embedded runtime preparation, capability probes, and lifecycle ownership."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import secrets
import shutil
import stat
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final

from homeassistant.core import HomeAssistant

from ..api.cloud import OwletCloudClient
from .apk import (
    REQUIRED_LIBRARIES,
    SUPPORTED_ARCHIVE_SUFFIXES,
    ExtractedOwletApplication,
    OwletArchiveError,
    extract_owlet_application,
)
from .elf import ElfInspectionError, inspect_elf
from .process import OwletHelperProcessError, OwletHelperProcessRunner
from .protocol import (
    FrameProbeResult,
    LibraryProbeResult,
    OwletHelperProtocolError,
    OwletHelperReportedError,
    parse_frame_probe_output,
    parse_library_probe_output,
)

RUNTIME_LAYOUT_VERSION: Final = 1
RUNTIME_MANIFEST: Final = "runtime-manifest.json"
RUNTIME_CURRENT: Final = "current"
SUPPORTED_MACHINE: Final = "aarch64"
_FRAME_PROBE_TIMEOUT: Final = 75.0
_LIBRARY_PROBE_TIMEOUT: Final = 20.0
_PROCESS_SESSION: Final = secrets.token_hex(8)
_REQUIRED_RUNTIME_FILES: Final = frozenset(
    {
        "bin/frame_probe",
        "bin/probe_libraries",
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
    ) -> None:
        self._hass = hass
        self._root = root
        self._client = client
        self._camera_identifier = camera_identifier
        self._runner = runner or OwletHelperProcessRunner()
        self._lock = asyncio.Lock()
        self._listeners: set[Callable[[], None]] = set()
        self._prepared: PreparedRuntime | None = None
        self._sdk_key: bytearray | None = None
        self.snapshot = RuntimeSnapshot()

    @property
    def supported_architecture(self) -> bool:
        """Return the cached machine capability without filesystem I/O."""
        return _normalized_machine() == SUPPORTED_MACHINE

    @property
    def frame_probe_available(self) -> bool:
        """Return whether every earlier gate has passed."""
        return self._prepared is not None and self.snapshot.libraries_compatible is True

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a synchronous state listener."""
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    async def async_prepare_and_probe_libraries(self) -> LibraryProbeResult:
        """Extract, inspect, verify, then dlopen without contacting a camera."""
        async with self._lock:
            self._set_status("preparing")
            try:
                prepared, sdk_key = await self._hass.async_add_executor_job(
                    self._prepare_sync
                )
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
                self._prepared = prepared
                self.snapshot.helper_version = prepared.manifest.version
                self.snapshot.libraries_compatible = probe.compatible
                self.snapshot.last_error_code = None
                self._set_status("ready")
                return probe
            except OwletRuntimeError as err:
                self._record_error(err.code, libraries_failed=True)
                raise
            except OwletArchiveError as err:
                self._record_error("invalid_apk", libraries_failed=True)
                raise OwletRuntimeError(
                    "invalid_apk", "The user-supplied application is invalid"
                ) from err
            except ElfInspectionError as err:
                self._record_error("library_incompatible", libraries_failed=True)
                raise OwletRuntimeError(
                    "library_incompatible", "A native library is incompatible"
                ) from err
            except (
                OwletHelperProcessError,
                OwletHelperProtocolError,
                OwletHelperReportedError,
            ) as err:
                self._record_error("library_probe_failed", libraries_failed=True)
                raise OwletRuntimeError(
                    "library_probe_failed", "Native libraries could not be loaded"
                ) from err

    async def async_run_frame_probe(self) -> FrameProbeResult:
        """Fetch fresh credentials and receive a bounded set of real frames."""
        async with self._lock:
            if self._prepared is None or self._sdk_key is None:
                raise OwletRuntimeError(
                    "runtime_not_ready", "Run the runtime probe first"
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
                self.snapshot.last_frame_probe = probe
                self.snapshot.last_frame_probe_at = datetime.now(UTC)
                self.snapshot.last_error_code = None
                self._set_status("ready")
                return probe
            except OwletHelperReportedError as err:
                self._record_error(f"native_{err.stage}_{err.native_code}")
                raise OwletRuntimeError(
                    "frame_probe_failed", "The camera frame probe failed"
                ) from err
            except (OwletHelperProcessError, OwletHelperProtocolError) as err:
                self._record_error("frame_probe_failed")
                raise OwletRuntimeError(
                    "frame_probe_failed", "The camera frame probe failed"
                ) from err

    async def async_shutdown(self) -> None:
        """Stop children, scrub SDK material, and release runtime state."""
        await self._runner.async_stop()
        self._replace_sdk_key(None)
        self._prepared = None
        self.snapshot.libraries_compatible = None
        self._set_status("stopped")

    def diagnostics(self) -> dict[str, Any]:
        """Return safe cached facts without filesystem or network I/O."""
        probe = self.snapshot.last_frame_probe
        return {
            "status": self.snapshot.status,
            "helper_version": self.snapshot.helper_version,
            "detected_apk_version": self.snapshot.detected_apk_version,
            "native_libraries_compatible": self.snapshot.libraries_compatible,
            "last_safe_error_code": self.snapshot.last_error_code,
            "last_frame_probe_at": (
                self.snapshot.last_frame_probe_at.isoformat()
                if self.snapshot.last_frame_probe_at is not None
                else None
            ),
            "last_frame_probe": asdict(probe) if probe is not None else None,
        }

    def _prepare_sync(self) -> tuple[PreparedRuntime, bytearray]:
        if _normalized_machine() != SUPPORTED_MACHINE:
            raise OwletRuntimeError(
                "unsupported_architecture", "Embedded mode requires AArch64"
            )
        _prepare_directories(self._root)
        archive = _select_archive(self._root / "uploads")
        archive.chmod(0o600)
        runtime_manifest = _verify_runtime(self._root / "runtime" / RUNTIME_CURRENT)
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
                _verify_persisted_libraries(final_library_directory, extracted)
            else:
                os.replace(temporary, final_root)
            for path in final_library_directory.iterdir():
                path.chmod(0o500)
            return (
                PreparedRuntime(
                    manifest=runtime_manifest,
                    library_directory=final_library_directory,
                    libraries=reports,
                    source_sha256=extracted.source_sha256,
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

    def _set_status(self, status: str) -> None:
        self.snapshot.status = status
        for listener in tuple(self._listeners):
            listener()


def _normalized_machine() -> str:
    machine = platform.machine().strip().lower()
    return "aarch64" if machine in {"aarch64", "arm64"} else machine


def _prepare_directories(root: Path) -> None:
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    root.chmod(0o700)
    for name in ("uploads", "extracted", "runtime", "logs", "state", "tmp"):
        path = root / name
        path.mkdir(mode=0o700, exist_ok=True)
        path.chmod(0o700)
    _remove_stale_extractions(root / "tmp")


def _remove_stale_extractions(directory: Path) -> None:
    """Remove only extraction directories owned by a previous Core process."""
    current_prefix = f"extract-{_PROCESS_SESSION}-"
    for path in directory.iterdir():
        if not path.name.startswith("extract-") or path.name.startswith(
            current_prefix
        ):
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
    return RuntimeManifest(version=version, architecture=architecture, root=root)


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
    *, sdk_key: bytearray, uid: str, auth_key: str, av_password: str
) -> bytearray:
    # JSON encoding creates one short-lived in-memory string, never a file,
    # environment variable, command argument, diagnostic value, or log record.
    payload = json.dumps(
        {
            "sdk_key": sdk_key.decode("ascii"),
            "uid": uid,
            "auth_key": auth_key,
            "av_password": av_password,
        },
        separators=(",", ":"),
    )
    return bytearray(payload.encode("utf-8") + b"\n")
