"""Checksum-pinned helper release download and atomic installation."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import stat
import tarfile
import tempfile
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Final, cast

from aiohttp import ClientError, ClientResponse, ClientSession
from homeassistant.core import HomeAssistant

from .manager import (
    RUNTIME_CURRENT,
    RUNTIME_MANIFEST,
    OwletRuntimeError,
    RuntimeManifest,
    _verify_runtime,
)

MAX_RUNTIME_ARCHIVE_SIZE: Final = 64 * 1024 * 1024
MAX_RUNTIME_UNCOMPRESSED_SIZE: Final = 128 * 1024 * 1024
MAX_RUNTIME_FILE_COUNT: Final = 64
MAX_CHECKSUMS_SIZE: Final = 64 * 1024
RUNTIME_DOWNLOAD_TIMEOUT: Final = 120.0
RELEASE_BASE_URL: Final = "https://github.com/ohlsont/ha-owlet-cam/releases/download"
_ALLOWED_FILES: Final = frozenset(
    {
        "LICENSES/AOSP-NOTICE.html.gz",
        "LICENSES/OWLET-CAM-MIT.txt",
        "bin/frame_probe",
        "bin/probe_libraries",
        "bin/snapshot_capture",
        "bin/stream_capture",
        "runtime/bin/linker64",
        "runtime/lib64/libc.so",
        "runtime/lib64/libdl.so",
        "runtime/lib64/libm.so",
        RUNTIME_MANIFEST,
    }
)
_EXECUTABLES: Final = frozenset(
    {
        "bin/frame_probe",
        "bin/probe_libraries",
        "bin/snapshot_capture",
        "bin/stream_capture",
        "runtime/bin/linker64",
    }
)
_NATIVE_LIBRARIES: Final = frozenset(
    {
        "runtime/lib64/libc.so",
        "runtime/lib64/libdl.so",
        "runtime/lib64/libm.so",
    }
)


class OwletRuntimeInstallError(ValueError):
    """Raised when a runtime archive fails integrity or extraction gates."""


class OwletRuntimeDownloadError(ValueError):
    """Raised with a redacted message when a release download fails."""


async def async_ensure_release_runtime(
    hass: HomeAssistant,
    session: ClientSession,
    *,
    version: str,
    architecture: str,
    runtime_parent: Path,
) -> RuntimeManifest:
    """Download and install the exact helper asset for this integration release."""
    asset_name = f"owlet-cam-helper-{architecture}.tar.gz"
    release_root = f"{RELEASE_BASE_URL}/v{version}"
    try:
        checksum_document = await _async_read_bounded(
            session, f"{release_root}/checksums.txt", MAX_CHECKSUMS_SIZE
        )
        expected_sha256 = _checksum_for_asset(checksum_document, asset_name)
        await hass.async_add_executor_job(_prepare_runtime_parent, runtime_parent)
        descriptor, temporary_name = await hass.async_add_executor_job(
            partial(
                tempfile.mkstemp,
                prefix=f".{asset_name}.",
                suffix=".partial",
                dir=runtime_parent,
            )
        )
        temporary = Path(temporary_name)
        try:
            await hass.async_add_executor_job(os.fchmod, descriptor, 0o600)
            await _async_download_to_descriptor(
                hass,
                session,
                f"{release_root}/{asset_name}",
                descriptor,
            )
            await hass.async_add_executor_job(os.fsync, descriptor)
            await hass.async_add_executor_job(os.close, descriptor)
            descriptor = -1
            manifest = cast(
                RuntimeManifest,
                await hass.async_add_executor_job(
                    partial(
                        install_runtime_archive,
                        temporary,
                        expected_sha256=expected_sha256,
                        runtime_parent=runtime_parent,
                        expected_version=version,
                        expected_architecture=architecture,
                    )
                ),
            )
            return manifest
        finally:
            if descriptor >= 0:
                await hass.async_add_executor_job(os.close, descriptor)
            await hass.async_add_executor_job(
                partial(temporary.unlink, missing_ok=True)
            )
    except OwletRuntimeInstallError:
        raise
    except (ClientError, TimeoutError, OSError, ValueError) as err:
        raise OwletRuntimeDownloadError(
            "The helper runtime release could not be downloaded"
        ) from err


async def _async_read_bounded(
    session: ClientSession, url: str, maximum_size: int
) -> bytes:
    """Read a small release metadata asset with strict status and size bounds."""
    content = bytearray()
    async with asyncio.timeout(RUNTIME_DOWNLOAD_TIMEOUT):
        async with session.get(url) as response:
            _raise_for_release_status(response)
            async for chunk in response.content.iter_chunked(16 * 1024):
                content.extend(chunk)
                if len(content) > maximum_size:
                    raise OwletRuntimeDownloadError(
                        "The helper release metadata is too large"
                    )
    return bytes(content)


async def _async_download_to_descriptor(
    hass: HomeAssistant,
    session: ClientSession,
    url: str,
    descriptor: int,
) -> None:
    """Stream one bounded helper asset to a private inherited descriptor."""
    received = 0
    async with asyncio.timeout(RUNTIME_DOWNLOAD_TIMEOUT):
        async with session.get(url) as response:
            _raise_for_release_status(response)
            async for chunk in response.content.iter_chunked(256 * 1024):
                received += len(chunk)
                if received > MAX_RUNTIME_ARCHIVE_SIZE:
                    raise OwletRuntimeDownloadError(
                        "The helper runtime archive is too large"
                    )
                await hass.async_add_executor_job(_write_all, descriptor, chunk)
    if received == 0:
        raise OwletRuntimeDownloadError("The helper runtime archive is empty")


def _raise_for_release_status(response: ClientResponse) -> None:
    if response.status != 200:
        raise OwletRuntimeDownloadError("The helper runtime release is unavailable")


def _checksum_for_asset(document: bytes, asset_name: str) -> str:
    try:
        lines = document.decode("ascii").splitlines()
    except UnicodeDecodeError as err:
        raise OwletRuntimeDownloadError(
            "The helper release checksums are invalid"
        ) from err
    matches: list[str] = []
    for line in lines:
        parts = line.split()
        if len(parts) == 2 and parts[1].removeprefix("*") == asset_name:
            matches.append(parts[0])
    if len(matches) != 1:
        raise OwletRuntimeDownloadError("The helper asset checksum is missing")
    checksum = matches[0].lower()
    if len(checksum) != 64 or any(
        character not in "0123456789abcdef" for character in checksum
    ):
        raise OwletRuntimeDownloadError("The helper asset checksum is invalid")
    return checksum


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("Runtime download did not make progress")
        remaining = remaining[written:]


def _prepare_runtime_parent(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise OSError("Runtime download directory is unsafe")
    path.chmod(0o700)


def install_runtime_archive(
    archive: Path,
    *,
    expected_sha256: str,
    runtime_parent: Path,
    expected_version: str | None = None,
    expected_architecture: str | None = None,
) -> RuntimeManifest:
    """Verify and atomically install one already-downloaded release asset."""
    _validate_archive_file(archive, expected_sha256)
    runtime_parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    runtime_parent.chmod(0o700)
    staging = Path(tempfile.mkdtemp(prefix=".runtime-install-", dir=runtime_parent))
    backup: Path | None = None
    current = runtime_parent / RUNTIME_CURRENT
    try:
        _extract_runtime_tar(archive, staging)
        manifest = _verify_runtime(staging)
        if (expected_version is not None and manifest.version != expected_version) or (
            expected_architecture is not None
            and manifest.architecture != expected_architecture
        ):
            raise OwletRuntimeInstallError(
                "Helper runtime release metadata does not match this installation"
            )
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise OwletRuntimeInstallError("Existing helper runtime path is unsafe")
            backup = runtime_parent / f".runtime-previous-{os.getpid()}"
            if backup.exists():
                raise OwletRuntimeInstallError("Runtime backup path already exists")
            os.replace(current, backup)
        try:
            os.replace(staging, current)
        except Exception:
            if backup is not None and backup.exists() and not current.exists():
                os.replace(backup, current)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return RuntimeManifest(
            version=manifest.version,
            architecture=manifest.architecture,
            root=current,
        )
    except OwletRuntimeInstallError:
        raise
    except (OSError, OwletRuntimeError, tarfile.TarError, ValueError) as err:
        raise OwletRuntimeInstallError("Helper runtime installation failed") from err
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _validate_archive_file(archive: Path, expected_sha256: str) -> None:
    try:
        metadata = archive.lstat()
    except OSError as err:
        raise OwletRuntimeInstallError("Helper runtime archive cannot be read") from err
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise OwletRuntimeInstallError("Helper runtime archive is not a regular file")
    if metadata.st_size > MAX_RUNTIME_ARCHIVE_SIZE:
        raise OwletRuntimeInstallError("Helper runtime archive exceeds the size limit")
    if (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or _sha256(archive) != expected_sha256
    ):
        raise OwletRuntimeInstallError("Helper runtime checksum mismatch")


def _extract_runtime_tar(archive: Path, destination: Path) -> None:
    total_size = 0
    files = 0
    seen: set[str] = set()
    with tarfile.open(archive, mode="r:gz") as source:
        members = source.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
                or "\\" in member.name
                or member.name not in _ALLOWED_FILES
                or not member.isfile()
                or member.name in seen
            ):
                raise OwletRuntimeInstallError(
                    "Helper runtime archive contains an unsafe member"
                )
            files += 1
            total_size += member.size
            if (
                files > MAX_RUNTIME_FILE_COUNT
                or total_size > MAX_RUNTIME_UNCOMPRESSED_SIZE
            ):
                raise OwletRuntimeInstallError(
                    "Helper runtime archive expands beyond the safety limit"
                )
            seen.add(member.name)
        if seen != _ALLOWED_FILES:
            raise OwletRuntimeInstallError("Helper runtime archive is incomplete")

        for member in members:
            extracted = source.extractfile(member)
            if extracted is None:
                raise OwletRuntimeInstallError("Helper runtime member cannot be read")
            output = destination.joinpath(*PurePosixPath(member.name).parts)
            output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            temporary = output.with_name(f".{output.name}.partial")
            written = 0
            try:
                with temporary.open("xb") as target:
                    while chunk := extracted.read(1024 * 1024):
                        written += len(chunk)
                        if written > member.size:
                            raise OwletRuntimeInstallError(
                                "Helper runtime member exceeded its declared size"
                            )
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                if written != member.size:
                    raise OwletRuntimeInstallError(
                        "Helper runtime member ended before its declared size"
                    )
                temporary.chmod(_installed_mode(member.name))
                os.replace(temporary, output)
            finally:
                temporary.unlink(missing_ok=True)


def _installed_mode(relative: str) -> int:
    if relative in _EXECUTABLES:
        return 0o700
    if relative in _NATIVE_LIBRARIES:
        return 0o500
    return 0o400


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
