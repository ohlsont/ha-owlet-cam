"""Safe extraction of user-supplied Owlet application archives."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Final

SUPPORTED_ARCHIVE_SUFFIXES: Final = frozenset({".apk", ".apkm", ".xapk", ".zip"})
TARGET_ABI: Final = "arm64-v8a"
REQUIRED_LIBRARIES: Final = frozenset(
    {
        "libAVAPIs.so",
        "libIOTCAPIs.so",
        "libP2PTunnelAPIs.so",
        "libRDTAPIs.so",
        "libTUTKGlobalAPIs.so",
    }
)

# Kalay application licence strings are printable base64-like values. Matching is
# deliberately broad: the actual key is user-supplied material and must never be
# hard-coded into this repository.
_SDK_KEY_RE: Final = re.compile(rb"(?<![A-Za-z0-9+/=_-])AQ[A-Za-z0-9+/=_-]{30,510}")
_SCAN_SUFFIXES: Final = frozenset({".dex", ".so"})
_COPY_CHUNK: Final = 1024 * 1024
_SCAN_OVERLAP: Final = 520


class OwletArchiveError(ValueError):
    """Raised when an application archive fails a safety or content gate."""


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Resource limits applied across the outer archive and all nested APKs."""

    maximum_archive_size: int = 512 * 1024 * 1024
    maximum_uncompressed_size: int = 2 * 1024 * 1024 * 1024
    maximum_file_count: int = 50_000
    maximum_nested_archive_size: int = 512 * 1024 * 1024
    maximum_nesting_depth: int = 2


@dataclass(frozen=True, slots=True)
class ExtractedLibrary:
    """Non-secret metadata for one extracted native library."""

    name: str
    path: Path
    sha256: str
    size: int


@dataclass(slots=True, repr=False)
class ExtractedOwletApplication:
    """Result of an allowlisted extraction.

    ``sdk_key`` is intentionally excluded from ``repr``. Callers must pass it to
    the isolated helper over stdin and then discard it; it must not be logged or
    serialized into diagnostics.
    """

    source_sha256: str
    abi: str
    libraries: dict[str, ExtractedLibrary]
    sdk_key: bytes | None = field(default=None, repr=False)

    @property
    def sdk_key_found(self) -> bool:
        """Return whether exactly one plausible SDK licence key was found."""
        return self.sdk_key is not None


@dataclass(slots=True)
class _Budget:
    limits: ArchiveLimits
    files: int = 0
    uncompressed: int = 0

    def account(self, info: zipfile.ZipInfo) -> None:
        self.files += 1
        self.uncompressed += info.file_size
        if self.files > self.limits.maximum_file_count:
            raise OwletArchiveError("Application archive contains too many files")
        if self.uncompressed > self.limits.maximum_uncompressed_size:
            raise OwletArchiveError(
                "Application archive expands beyond the safety limit"
            )


@dataclass(slots=True)
class _ExtractionState:
    destination: Path
    target_abi: str
    budget: _Budget
    libraries: dict[str, ExtractedLibrary] = field(default_factory=dict)
    sdk_candidates: set[bytes] = field(default_factory=set)


def extract_owlet_application(
    archive: Path,
    destination: Path,
    *,
    target_abi: str = TARGET_ABI,
    limits: ArchiveLimits | None = None,
) -> ExtractedOwletApplication:
    """Extract only required libraries and detect the user APK's SDK key.

    The destination may exist but must be empty. Nothing from the archive is
    executed, and nested split APKs are spooled to mode-0600 temporary files
    under the same global file-count and uncompressed-size budget.
    """
    limits = limits or ArchiveLimits()
    _validate_source(archive, limits)
    _prepare_destination(destination)

    source_sha256 = _hash_file(archive)
    state = _ExtractionState(
        destination=destination,
        target_abi=target_abi,
        budget=_Budget(limits),
    )
    try:
        with archive.open("rb") as source:
            _process_zip(source, state, depth=0)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as err:
        raise OwletArchiveError(
            "Application archive is not a valid ZIP archive"
        ) from err

    missing = sorted(REQUIRED_LIBRARIES - state.libraries.keys())
    if missing:
        raise OwletArchiveError(
            "Application archive is missing required ARM64 libraries: "
            + ", ".join(missing)
        )
    if len(state.sdk_candidates) > 1:
        raise OwletArchiveError("Application archive contains ambiguous SDK keys")

    sdk_key = next(iter(state.sdk_candidates), None)
    return ExtractedOwletApplication(
        source_sha256=source_sha256,
        abi=target_abi,
        libraries=dict(sorted(state.libraries.items())),
        sdk_key=sdk_key,
    )


def _validate_source(archive: Path, limits: ArchiveLimits) -> None:
    try:
        source_stat = archive.lstat()
    except OSError as err:
        raise OwletArchiveError("Application archive cannot be read") from err
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise OwletArchiveError("Application archive must be a regular file")
    if archive.suffix.lower() not in SUPPORTED_ARCHIVE_SUFFIXES:
        raise OwletArchiveError("Unsupported application archive type")
    if source_stat.st_size > limits.maximum_archive_size:
        raise OwletArchiveError("Application archive exceeds the size limit")


def _prepare_destination(destination: Path) -> None:
    try:
        destination.mkdir(parents=True, mode=0o700, exist_ok=True)
        if any(destination.iterdir()):
            raise OwletArchiveError("Extraction destination must be empty")
        destination.chmod(0o700)
    except OwletArchiveError:
        raise
    except OSError as err:
        raise OwletArchiveError("Extraction destination cannot be prepared") from err


def _process_zip(source: IO[bytes], state: _ExtractionState, *, depth: int) -> None:
    if depth > state.budget.limits.maximum_nesting_depth:
        raise OwletArchiveError("Application archive nesting exceeds the safety limit")
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            _validate_member(info)
            if info.is_dir():
                continue
            state.budget.account(info)
            member = PurePosixPath(info.filename)
            basename = member.name

            if _is_target_library(member, basename, state.target_abi):
                with archive.open(info, "r") as data:
                    _extract_library(data, basename, info.file_size, state)
                continue

            if member.suffix.lower() == ".apk":
                if info.file_size > state.budget.limits.maximum_nested_archive_size:
                    raise OwletArchiveError("Nested APK exceeds the size limit")
                with tempfile.TemporaryFile(
                    mode="w+b", dir=state.destination
                ) as nested:
                    os.fchmod(nested.fileno(), 0o600)
                    with archive.open(info, "r") as data:
                        _copy_limited(
                            data,
                            nested,
                            state.budget.limits.maximum_nested_archive_size,
                        )
                    nested.seek(0)
                    _process_zip(nested, state, depth=depth + 1)
                continue

            if member.suffix.lower() in _SCAN_SUFFIXES:
                with archive.open(info, "r") as data:
                    _scan_sdk_key(data, state.sdk_candidates)


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if "\\" in name or "\x00" in name:
        raise OwletArchiveError("Application archive contains an unsafe path")
    member = PurePosixPath(name)
    if member.is_absolute() or any(part in {"", ".", ".."} for part in member.parts):
        raise OwletArchiveError("Application archive contains path traversal")
    if member.parts and ":" in member.parts[0]:
        raise OwletArchiveError("Application archive contains an absolute path")

    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise OwletArchiveError("Application archive contains a link or special file")


def _is_target_library(member: PurePosixPath, basename: str, target_abi: str) -> bool:
    if basename not in REQUIRED_LIBRARIES:
        return False
    parts = tuple(part.lower().replace("_", "-") for part in member.parts)
    return target_abi.lower() in parts


def _extract_library(
    source: IO[bytes],
    name: str,
    expected_size: int,
    state: _ExtractionState,
) -> None:
    library_dir = state.destination / state.target_abi
    library_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    output = library_dir / name
    temporary = library_dir / f".{name}.partial"
    digest = hashlib.sha256()
    written = 0
    scan_overlap = b""
    try:
        with temporary.open("xb") as target:
            os.chmod(target.fileno(), 0o500)
            while chunk := source.read(_COPY_CHUNK):
                written += len(chunk)
                if written > expected_size:
                    raise OwletArchiveError("Library entry exceeded its declared size")
                digest.update(chunk)
                scan_data = scan_overlap + chunk
                state.sdk_candidates.update(
                    match.group(0) for match in _SDK_KEY_RE.finditer(scan_data)
                )
                scan_overlap = scan_data[-_SCAN_OVERLAP:]
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if written != expected_size:
            raise OwletArchiveError("Library entry ended before its declared size")
        sha256 = digest.hexdigest()
        previous = state.libraries.get(name)
        if previous is not None:
            if previous.sha256 != sha256:
                raise OwletArchiveError(
                    "Application archive contains conflicting libraries"
                )
            temporary.unlink(missing_ok=True)
            return
        os.replace(temporary, output)
        output.chmod(0o500)
        state.libraries[name] = ExtractedLibrary(
            name=name,
            path=output,
            sha256=sha256,
            size=written,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _scan_sdk_key(source: IO[bytes], candidates: set[bytes]) -> None:
    overlap = b""
    while chunk := source.read(_COPY_CHUNK):
        data = overlap + chunk
        candidates.update(match.group(0) for match in _SDK_KEY_RE.finditer(data))
        overlap = data[-_SCAN_OVERLAP:]


def _copy_limited(source: IO[bytes], target: IO[bytes], maximum: int) -> None:
    written = 0
    while chunk := source.read(_COPY_CHUNK):
        written += len(chunk)
        if written > maximum:
            raise OwletArchiveError("Nested APK exceeds the size limit")
        target.write(chunk)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_COPY_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
