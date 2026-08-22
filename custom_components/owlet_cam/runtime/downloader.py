"""Checksum-pinned, atomic helper runtime archive installation."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Final

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
_ALLOWED_FILES: Final = frozenset(
    {
        "LICENSES/AOSP-NOTICE.html.gz",
        "LICENSES/OWLET-CAM-MIT.txt",
        "bin/frame_probe",
        "bin/probe_libraries",
        "runtime/bin/linker64",
        "runtime/lib64/libc.so",
        "runtime/lib64/libdl.so",
        "runtime/lib64/libm.so",
        RUNTIME_MANIFEST,
    }
)
_EXECUTABLES: Final = frozenset(
    {"bin/frame_probe", "bin/probe_libraries", "runtime/bin/linker64"}
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


def install_runtime_archive(
    archive: Path,
    *,
    expected_sha256: str,
    runtime_parent: Path,
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
