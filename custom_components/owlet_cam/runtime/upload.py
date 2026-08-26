"""Private, bounded storage for user-supplied Owlet application uploads."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from homeassistant.core import HomeAssistant

from .apk import SUPPORTED_ARCHIVE_SUFFIXES, ArchiveLimits

MAXIMUM_UPLOAD_SIZE: Final = ArchiveLimits().maximum_archive_size


class OwletUploadError(ValueError):
    """Raised when an authenticated upload fails a storage safety gate."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class StoredUpload:
    """Non-secret metadata for one atomically stored application archive."""

    size: int
    sha256: str


async def async_store_upload(
    hass: HomeAssistant,
    uploads: Path,
    content: AsyncIterable[bytes],
    *,
    suffix: str,
    content_length: int | None,
) -> StoredUpload:
    """Stream an authenticated request to a private, generated disk path."""
    normalized_suffix = suffix.strip().lower()
    if normalized_suffix not in SUPPORTED_ARCHIVE_SUFFIXES:
        raise OwletUploadError("unsupported_archive", "Unsupported archive type")
    if content_length is not None and (
        content_length <= 0 or content_length > MAXIMUM_UPLOAD_SIZE
    ):
        raise OwletUploadError("upload_too_large", "Upload exceeds the size limit")

    descriptor, temporary = await hass.async_add_executor_job(
        _open_private_temporary, uploads, normalized_suffix
    )
    digest = hashlib.sha256()
    written = 0
    try:
        async for chunk in content:
            if not chunk:
                continue
            written += len(chunk)
            if written > MAXIMUM_UPLOAD_SIZE:
                raise OwletUploadError(
                    "upload_too_large", "Upload exceeds the size limit"
                )
            digest.update(chunk)
            await hass.async_add_executor_job(_write_all, descriptor, chunk)
        if written == 0:
            raise OwletUploadError("empty_upload", "Application upload is empty")
        sha256 = digest.hexdigest()
        await hass.async_add_executor_job(
            _finish_upload,
            descriptor,
            temporary,
            uploads / f"application-{sha256[:16]}{normalized_suffix}",
        )
        await hass.async_add_executor_job(os.close, descriptor)
        descriptor = -1
        return StoredUpload(size=written, sha256=sha256)
    finally:
        if descriptor >= 0:
            await hass.async_add_executor_job(os.close, descriptor)
        await hass.async_add_executor_job(temporary.unlink, True)


def store_uploaded_path(source: Path, uploads: Path) -> StoredUpload:
    """Copy a Home Assistant file-selector upload into private runtime storage.

    This synchronous function is intended to run in Home Assistant's executor.
    The source is owned and removed by ``file_upload.process_uploaded_file``.
    """
    try:
        source_stat = source.lstat()
    except OSError as err:
        raise OwletUploadError(
            "upload_unavailable", "Uploaded runtime package is unavailable"
        ) from err
    if source.is_symlink() or not source.is_file():
        raise OwletUploadError(
            "unsafe_upload", "Uploaded runtime package is not a regular file"
        )
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_ARCHIVE_SUFFIXES:
        raise OwletUploadError("unsupported_archive", "Unsupported archive type")
    if source_stat.st_size <= 0 or source_stat.st_size > MAXIMUM_UPLOAD_SIZE:
        raise OwletUploadError("upload_too_large", "Upload exceeds the size limit")

    descriptor, temporary = _open_private_temporary(uploads, suffix)
    digest = hashlib.sha256()
    written = 0
    try:
        with source.open("rb") as source_file:
            while chunk := source_file.read(1024 * 1024):
                written += len(chunk)
                if written > MAXIMUM_UPLOAD_SIZE:
                    raise OwletUploadError(
                        "upload_too_large", "Upload exceeds the size limit"
                    )
                digest.update(chunk)
                _write_all(descriptor, chunk)
        if written == 0:
            raise OwletUploadError("empty_upload", "Runtime package is empty")
        sha256 = digest.hexdigest()
        _finish_upload(
            descriptor,
            temporary,
            uploads / f"application-{sha256[:16]}{suffix}",
        )
        os.close(descriptor)
        descriptor = -1
        return StoredUpload(size=written, sha256=sha256)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _open_private_temporary(directory: Path, suffix: str) -> tuple[int, Path]:
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise OwletUploadError(
            "unsafe_upload_storage", "Application upload storage is unsafe"
        )
    directory.chmod(0o700)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=".application-upload-", suffix=f"{suffix}.partial", dir=directory
    )
    os.fchmod(descriptor, 0o600)
    return descriptor, Path(raw_path)


def _write_all(descriptor: int, chunk: bytes) -> None:
    remaining = memoryview(chunk)
    while remaining:
        count = os.write(descriptor, remaining)
        if count <= 0:
            raise OSError("Application upload write did not make progress")
        remaining = remaining[count:]


def _finish_upload(descriptor: int, temporary: Path, final: Path) -> None:
    os.fsync(descriptor)
    os.replace(temporary, final)
    final.chmod(0o600)
    for candidate in final.parent.iterdir():
        if (
            candidate != final
            and candidate.is_file()
            and not candidate.is_symlink()
            and candidate.suffix.lower() in SUPPORTED_ARCHIVE_SUFFIXES
        ):
            candidate.unlink()
